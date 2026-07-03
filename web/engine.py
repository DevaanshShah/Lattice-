"""The engine facade the web layer talks to — a THIN adapter over the M1–M6 modules.

FR-28's rule: the frontend re-implements no scene logic; it calls these methods, which delegate
straight to the existing engine (planner, composition.decoupled for build, composition.regen,
editing.*, composition.export). The only thing this layer adds that the CLI didn't need is MULTI-PROJECT
workspaces: each project lives in its own `out/web/<pid>/` dir (project.json + scenes/ + final.mp4),
so many users' videos coexist. State persistence is the M6 VideoProject.save/load — unchanged.

Methods that render accept `log`/`on_scene` callbacks so a Job can stream progress (FR-29);
methods that don't render (reorder/delete/rollback/history) return immediately.
"""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from composition import decoupled
from composition import export as export_mod
from composition.scene_dag import SceneNode, VideoProject
from core.config import settings
from core.llm import LLMClient, get_client
from core.schemas.outline import Outline, OutlineItem
from editing import arrange, history, tweak
from editing._common import restitch_and_save
from planner import approval
from planner import outline as planner_outline


class ProjectNotFound(KeyError):
    pass


class Engine:
    """Stateless-ish facade: all durable state is on disk under `root` (one dir per project)."""

    def __init__(self, *, root: str | Path | None = None, client: LLMClient | None = None) -> None:
        self.root = Path(root) if root else settings.out_dir / "web"
        self.root.mkdir(parents=True, exist_ok=True)
        self._client = client  # injectable (tests); None -> real get_client() at call time

    # --- workspace helpers ------------------------------------------------------------------
    def _client_or_default(self) -> LLMClient:
        return self._client or get_client()

    def workspace(self, pid: str) -> Path:
        return self.root / pid

    def _project_path(self, pid: str) -> Path:
        return self.workspace(pid) / "project.json"

    def exists(self, pid: str) -> bool:
        return self._project_path(pid).exists()

    def load(self, pid: str) -> VideoProject:
        path = self._project_path(pid)
        if not path.exists():
            raise ProjectNotFound(pid)
        return VideoProject.load(path)

    def save(self, pid: str, project: VideoProject) -> None:
        project.save(self._project_path(pid))

    def list_projects(self) -> list[dict]:
        out: list[dict] = []
        for d in sorted(self.root.iterdir() if self.root.exists() else []):
            pj = d / "project.json"
            if pj.exists():
                try:
                    p = VideoProject.load(pj)
                    out.append({"id": d.name, "topic": p.topic, "scenes": len(p.scenes),
                                "built": bool(p.final_mp4)})
                except Exception:
                    continue  # a half-written project shouldn't break the listing
        return out

    # --- planning + build (the outline-approval gate, then render) ---------------------------
    def plan(self, topic: str, *, max_scenes: int | None = None, log=print) -> tuple[str, VideoProject]:
        """Plan an outline and persist a DRAFT project (scenes listed, nothing rendered yet).

        Returns (project_id, project). The build step happens later, after the user approves/edits
        the outline — so we never pay to render scenes the user would have cut.
        """
        say = log or (lambda _m: None)
        say(f"-> planning outline for: {topic!r}")
        outline = planner_outline.generate(topic, max_scenes=max_scenes, client=self._client_or_default())
        pid = uuid4().hex[:8]
        self.workspace(pid).mkdir(parents=True, exist_ok=True)
        project = VideoProject.from_outline(outline)  # no style/render yet
        self.save(pid, project)
        say(f"   draft project {pid} with {len(outline.items)} scene(s)")
        return pid, project

    def _outline_of(self, project: VideoProject) -> Outline:
        return Outline(topic=project.topic,
                       items=[OutlineItem(title=s.title, intent=s.intent) for s in project.scenes])

    def build(self, pid: str, *, keep: list[int] | None = None, quality: str = "preview",
              cap: int | None = None, log=print, on_scene=None) -> VideoProject:
        """Apply any outline edits, then render every scene through the DECOUPLED STRUCTURAL pipeline
        (the finalized path: LatticeScene grid + geometry primitives + grounded/paced narration +
        silent-render->gTTS->mux reliability), stitch, and persist. Populates the VideoProject so
        preview/download/script keep working. (`cap` is accepted for API compat; the approved outline
        already fixes the scene count.)"""
        project = self.load(pid)
        outline = self._outline_of(project)
        if keep is not None:
            outline = approval.apply_edits(outline, keep=keep)   # reorder/cut BEFORE spend
        client = self._client_or_default()
        say = log or (lambda _m: None)
        workspace = self.workspace(pid)
        built = VideoProject.from_outline(outline)
        final = decoupled.build_video(
            project.topic, outline=outline, client=client, quality=quality,
            out_dir=workspace, out_name="final.mp4", on_scene=on_scene, log=say)
        self._populate_from_decoupled(built, workspace, final)
        self.save(pid, built)
        return built

    @staticmethod
    def _fill_node_from_dir(node: SceneNode, sdir: Path) -> bool:
        """Load one scene's decoupled outputs (narrated.mp4 / scene.py / spec.json / narration.txt)
        from `sdir` into the node. Returns True iff a rendered clip exists."""
        mp4 = Path(sdir) / "narrated.mp4"
        if not mp4.exists():
            return False
        node.mp4 = str(mp4)
        node.compiled = True
        scene_py = Path(sdir) / "scene.py"
        if scene_py.exists():
            node.code = scene_py.read_text(encoding="utf-8", errors="replace")
        spec_json = Path(sdir) / "spec.json"
        if spec_json.exists():
            from core.schemas.scene_spec import SceneSpec
            try:
                node.spec = SceneSpec.model_validate_json(spec_json.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 — a malformed spec shouldn't fail the whole op
                pass
        ntxt = Path(sdir) / "narration.txt"
        if ntxt.exists():
            text = ntxt.read_text(encoding="utf-8", errors="replace").strip()
            node.script = [text] if text else []
        return True

    def _populate_from_decoupled(self, built: VideoProject, workspace: Path, final: Path | None) -> None:
        """Fill the VideoProject after a full build from the decoupled layout (scenes/scene_<i>/). Scene
        i corresponds to outline.items[i] == built.scenes[i] (index-aligned)."""
        scenes_dir = Path(workspace) / "scenes"
        for node in built.scenes:
            self._fill_node_from_dir(node, scenes_dir / f"scene_{node.index}")
        built.final_mp4 = str(final) if final else None

    # --- single-scene render ops (each touches ONE scene via the decoupled STRUCTURAL path) ---
    def _render_node(self, pid: str, project: VideoProject, node: SceneNode, *, quality: str, log,
                     spec=None, base_code=None, narration_override=None, use_critic: bool = True) -> bool:
        """Render ONE node through the decoupled STRUCTURAL pipeline into its sid-keyed dir
        (scenes/scene_<sid>/, matching the versions layout), then load it back into the node. Returns
        True on success. spec=None -> fresh expand+codegen (regenerate/insert); a given spec drives it
        (tweak passes a revised spec); base_code+override re-renders identical visuals with new words."""
        outline = self._outline_of(project)
        item = outline.items[node.index]
        sdir = self.workspace(pid) / "scenes" / f"scene_{node.sid}"
        try:
            decoupled.build_scene(item, outline, node.index, work_dir=sdir,
                                  client=self._client_or_default(), structural=True, quality=quality,
                                  spec=spec, base_code=base_code, narration_override=narration_override,
                                  use_critic=use_critic)
        except Exception as e:  # noqa: BLE001 — a failed render must not half-mutate the project
            (log or (lambda _m: None))(f"[edit] scene {node.index} render failed: {type(e).__name__}: {e}")
            return False
        return self._fill_node_from_dir(node, sdir)

    def _single_scene_render(self, pid: str, index: int, fn, *, on_scene=None, log=print) -> VideoProject:
        """Shared wrapper: flip the scene's status around an isolated render op."""
        if on_scene:
            on_scene(index, "rendering")
        project = fn(self.load(pid))
        ok = bool(project.scenes[index].mp4) if 0 <= index < len(project.scenes) else False
        if on_scene:
            on_scene(index, "done" if ok else "failed")
        return project

    def regenerate(self, pid: str, index: int, *, quality: str = "preview", log=print,
                   on_scene=None) -> VideoProject:
        return self._single_scene_render(
            pid, index,
            lambda p: self._regen_scene(pid, p, index, quality=quality, log=log),
            on_scene=on_scene, log=log)

    def _regen_scene(self, pid: str, project: VideoProject, index: int, *, quality: str, log) -> VideoProject:
        node = project.scene(index)
        prior = node.model_copy(deep=True)   # keep the prior good clip if the rebuild fails
        if self._render_node(pid, project, node, quality=quality, log=log, spec=node.spec):
            restitch_and_save(project, self.workspace(pid), log=log)
        else:
            project.scenes[index] = prior
            self.save(pid, project)
        return project

    def tweak(self, pid: str, index: int, instruction: str, *, quality: str = "preview", log=print,
              on_scene=None) -> VideoProject:
        return self._single_scene_render(
            pid, index,
            lambda p: self._tweak_scene(pid, p, index, instruction, quality=quality, log=log),
            on_scene=on_scene, log=log)

    def _tweak_scene(self, pid: str, project: VideoProject, index: int, instruction: str, *,
                     quality: str, log) -> VideoProject:
        node = project.scene(index)
        if node.spec is None:
            raise ValueError(f"scene {index} hasn't been generated yet — build it before tweaking")
        history.snapshot(node, out_dir=self.workspace(pid), label=f"pre-tweak: {instruction[:40]}")
        prior = node.model_copy(deep=True)
        revised = tweak.apply_tweak(node.spec, instruction, client=self._client_or_default())  # revise SPEC
        if self._render_node(pid, project, node, quality=quality, log=log, spec=revised):
            restitch_and_save(project, self.workspace(pid), log=log)
        else:
            project.scenes[index] = prior
            self.save(pid, project)
        return project

    def edit_narration(self, pid: str, index: int, lines: list[str], *, quality: str = "preview",
                       log=print, on_scene=None) -> VideoProject:
        return self._single_scene_render(
            pid, index,
            lambda p: self._edit_narration(pid, p, index, lines, quality=quality, log=log),
            on_scene=on_scene, log=log)

    def _edit_narration(self, pid: str, project: VideoProject, index: int, lines: list[str], *,
                        quality: str, log) -> VideoProject:
        node = project.scene(index)
        if node.spec is None:
            raise ValueError(f"scene {index} hasn't been generated yet — build it before editing narration")
        if not lines or not any(s.strip() for s in lines):
            raise ValueError("narration cannot be empty")
        if not node.code:
            raise ValueError(f"scene {index} has no code to re-render")
        history.snapshot(node, out_dir=self.workspace(pid), label="pre-narration-edit")
        prior = node.model_copy(deep=True)
        # re-render the EXACT visuals with the user's words; no critic so the visuals can't drift
        if self._render_node(pid, project, node, quality=quality, log=log, spec=node.spec,
                             base_code=node.code, narration_override=list(lines), use_critic=False):
            restitch_and_save(project, self.workspace(pid), log=log)
        else:
            project.scenes[index] = prior
            self.save(pid, project)
        return project

    def insert(self, pid: str, pos: int, title: str, intent: str, *, quality: str = "preview",
               log=print, on_scene=None) -> VideoProject:
        if on_scene:
            on_scene(pos, "rendering")
        project = self.load(pid)
        pos = max(0, min(pos, len(project.scenes)))
        node = SceneNode(index=pos, title=title, intent=intent)   # fresh sid -> own work dir
        project.scenes.insert(pos, node)
        project.reindex()
        if self._render_node(pid, project, node, quality=quality, log=log, spec=None):
            restitch_and_save(project, self.workspace(pid), log=log)
            ok = True
        else:
            project.scenes.remove(node)   # failure atomicity: undo the insert
            project.reindex()
            self.save(pid, project)
            ok = False
        if on_scene:
            on_scene(pos, "done" if ok else "failed")
        return project

    # --- structural ops (NO render: reuse clips + re-stitch) --------------------------------
    def reorder(self, pid: str, frm: int, to: int, *, log=print) -> VideoProject:
        return arrange.reorder(self.load(pid), frm, to, out_dir=self.workspace(pid), log=log)

    def delete(self, pid: str, index: int, *, log=print) -> VideoProject:
        return arrange.delete(self.load(pid), index, out_dir=self.workspace(pid), log=log)

    def rollback(self, pid: str, index: int, version: int, *, log=print) -> VideoProject:
        return history.rollback(self.load(pid), index, version, out_dir=self.workspace(pid), log=log)

    def scene_history(self, pid: str, index: int) -> list[dict]:
        node = self.load(pid).scene(index)
        return [{"version": v.version, "label": v.label, "score": v.score} for v in node.versions]

    # --- export / download (FR-30) ----------------------------------------------------------
    def export(self, pid: str, *, subtitles: str = "none", log=print) -> dict:
        return export_mod.export(self.load(pid), out_dir=self.workspace(pid) / "export",
                                 subtitles=subtitles, log=log)

    def scene_script(self, pid: str, index: int) -> str:
        """One scene's narration lines as plain text (for per-scene review/download)."""
        node = self.load(pid).scene(index)
        return "\n".join(node.script) if node.script else ""

    def full_script(self, pid: str) -> str:
        """The whole video's narration as a readable, scene-by-scene transcript."""
        p = self.load(pid)
        out = [f"# {p.topic}", ""]
        for s in p.scenes:
            out.append(f"## Scene {s.index + 1} — {s.title}")
            out.extend(s.script or ["(no narration generated yet)"])
            out.append("")
        return "\n".join(out).rstrip() + "\n"

    def scene_mp4(self, pid: str, index: int) -> Path | None:
        node = self.load(pid).scene(index)
        return Path(node.mp4) if node.mp4 and Path(node.mp4).exists() else None

    def final_mp4(self, pid: str) -> Path | None:
        p = self.load(pid)
        return Path(p.final_mp4) if p.final_mp4 and Path(p.final_mp4).exists() else None


# --- DTOs (plain dicts the API serializes; keeps pydantic models off the wire) --------------

def project_dto(pid: str, project: VideoProject) -> dict:
    return {
        "id": pid,
        "topic": project.topic,
        "final_ready": bool(project.final_mp4),
        "style": (project.style.model_dump() if project.style else None),
        "scenes": [scene_dto(s) for s in project.scenes],
    }


def scene_dto(node) -> dict:
    return {
        "index": node.index,
        "sid": node.sid,
        "title": node.title,
        "intent": node.intent,
        "built": bool(node.mp4),
        "score": node.score,
        "narration": list(node.script),
        "versions": len(node.versions),
    }
