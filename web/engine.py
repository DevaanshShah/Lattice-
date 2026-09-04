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

import json
from pathlib import Path
from uuid import uuid4

from composition import decoupled
from composition import export as export_mod
from composition.scene_dag import SceneNode, VideoProject
from core import storage
from core.config import settings
from core.llm import LLMClient, get_client
from core.schemas.outline import Outline, OutlineItem
from editing import arrange, history, tweak
from editing._common import restitch_and_save
from planner import approval
from planner import outline as planner_outline
from web.devtrace import traced


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
    def plan(self, topic: str, *, max_scenes: int | None = None, target_seconds: int | None = None,
             pid: str | None = None, log=print) -> tuple[str, VideoProject]:
        """Plan an outline and persist a DRAFT project (scenes listed, nothing rendered yet).

        Returns (project_id, project). The build step happens later, after the user approves/edits
        the outline — so we never pay to render scenes the user would have cut.
        target_seconds: the user's duration pick (30s/60s/2min). Sets the outline SCOPE (how many
        ~15s beats fit) and is persisted so build() paces each scene's animation to budget/n.
        """
        say = log or (lambda _m: None)
        say(f"-> planning outline for: {topic!r}"
            + (f" (~{target_seconds}s budget)" if target_seconds else ""))
        outline = planner_outline.generate(topic, max_scenes=max_scenes,
                                           target_seconds=target_seconds,
                                           client=self._client_or_default())
        pid, project = self._persist_new(outline, target_seconds=target_seconds, pid=pid)
        say(f"   draft project {pid} with {len(outline.items)} scene(s)")
        return pid, project

    def _persist_new(self, outline: Outline, *, target_seconds: int | None = None,
                     pid: str | None = None) -> tuple[str, VideoProject]:
        """Materialise a DRAFT project (fresh pid + workspace) from an outline — the shared tail of
        every planning path (topic / image / code). No style/render yet; the build gate comes later."""
        # The caller may pre-mint the id (the web layer does, so the planning LLM call is already
        # tagged with the project it is paying for — attribute-after-the-fact loses that spend).
        pid = pid or uuid4().hex[:8]
        self.workspace(pid).mkdir(parents=True, exist_ok=True)
        # Generate the visual THEME (palette/fonts/object looks) up front so the user reviews it
        # alongside the outline BEFORE any render — and the approved theme is what build() uses,
        # instead of the build silently generating a different one. Safe: None if it errors.
        style = decoupled.style_gen_safe(outline.topic, outline, self._client_or_default())
        project = VideoProject.from_outline(outline, style=style)
        project.target_seconds = target_seconds
        self.save(pid, project)
        return pid, project

    def plan_from_image(self, image: str, *, target_seconds: int | None = None,
                        max_scenes: int | None = None, pid: str | None = None,
                        log=print) -> tuple[str, VideoProject]:
        """Derive a topic from an uploaded image, then plan an outline exactly like a typed topic.
        The vision step uses the critic client (vision-capable); planning reuses plan() unchanged."""
        from web import seed
        say = log or (lambda _m: None)
        say("-> reading image (vision)")
        res = seed.from_image(image, client=self._client)   # None -> get_critic_client(); test client honored
        say(f"   derived topic: {res.topic!r}")
        return self.plan(res.topic, max_scenes=max_scenes, target_seconds=target_seconds,
                         pid=pid, log=log)

    def plan_from_code(self, code: str, language: str | None = None, *, pid: str | None = None,
                       target_seconds: int | None = None, log=print) -> tuple[str, VideoProject]:
        """Plan a segment-by-segment code WALKTHROUGH (overview + one scene per line/block) and persist
        a draft project. Reuses the outline-approval gate + build path unchanged; only the outline is
        built differently (planner.code_walkthrough instead of the generic topic planner)."""
        from planner import code_walkthrough
        say = log or (lambda _m: None)
        say(f"-> planning code walkthrough ({language or 'auto'}, {len(code or '')} chars)")
        wt = code_walkthrough.plan_walkthrough(code, language, client=self._client_or_default(),
                                               target_seconds=target_seconds)
        outline = code_walkthrough.outline_of(wt)
        pid, project = self._persist_new(outline, target_seconds=target_seconds, pid=pid)
        # the manifest (full code lines + per-scene highlight/caption/narration) drives the scaffold
        # build; its presence is how build() knows to render the deterministic walkthrough, not freeform.
        (self.workspace(pid) / "walkthrough.json").write_text(
            json.dumps(wt.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        say(f"   draft project {pid} with {len(outline.items)} walkthrough scene(s)")
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
        if (self.workspace(pid) / "walkthrough.json").exists():
            return self._build_walkthrough(pid, keep=keep, quality=quality, log=log, on_scene=on_scene)
        project = self.load(pid)
        outline = self._outline_of(project)
        say = log or (lambda _m: None)
        if keep is not None:
            outline = approval.apply_edits(outline, keep=keep)   # reorder/cut BEFORE spend
        client = traced(self._client_or_default(), say)          # narrate every LLM hit into the job log
        workspace = self.workspace(pid)
        built = VideoProject.from_outline(outline, style=project.style)
        built.target_seconds = project.target_seconds
        final = decoupled.build_video(
            project.topic, outline=outline, client=client, quality=quality,
            style=project.style,   # render the THEME the user approved, not a freshly-rolled one
            target_seconds=project.target_seconds,   # per-scene pacing = budget / n_scenes
            out_dir=workspace, out_name="final.mp4", on_scene=on_scene, log=say)
        self._populate_from_decoupled(built, workspace, final)
        self.save(pid, built)
        # Durable copy: this container's disk does not survive a redeploy. No-op when R2 is unset.
        if final:
            storage.offload(final, storage.video_key(pid), log=say)
        return built

    def _build_walkthrough(self, pid: str, *, keep: list[int] | None = None, quality: str = "preview",
                           log=print, on_scene=None) -> VideoProject:
        """Render a code walkthrough via the DETERMINISTIC scaffold (composition.walkthrough): every scene
        shows the full snippet with one line highlighted + spoken narration. No codegen LLM call — the
        planner already fixed the content (walkthrough.json), so this is pure render + stitch."""
        from planner.code_walkthrough import Walkthrough
        from composition import walkthrough as wt_render
        say = log or (lambda _m: None)
        project = self.load(pid)
        outline = self._outline_of(project)
        manifest = Walkthrough.from_dict(json.loads(
            (self.workspace(pid) / "walkthrough.json").read_text(encoding="utf-8")))
        kept = list(range(len(manifest.scenes))) if keep is None else list(keep)
        if keep is not None:
            outline = approval.apply_edits(outline, keep=keep)   # reorder/cut BEFORE spend
        workspace = self.workspace(pid)
        built = VideoProject.from_outline(outline)
        built.target_seconds = project.target_seconds
        say(f"-> walkthrough build: {len(built.scenes)} scene(s)")
        for new_i, orig_i in enumerate(kept):
            if on_scene:
                on_scene(new_i, "rendering")
            ok = False
            if 0 <= orig_i < len(manifest.scenes) and new_i < len(built.scenes):
                wsc = manifest.scenes[orig_i]
                sdir = workspace / "scenes" / f"scene_{new_i}"
                try:
                    wt_render.render_scene(sdir, lines=manifest.code_lines, active=wsc.active,
                                           caption=wsc.caption, title=wsc.title,
                                           narration=wsc.narration, quality=quality, log=say)
                    ok = self._fill_node_from_dir(built.scenes[new_i], sdir)
                except Exception as e:  # noqa: BLE001 — one bad scene must not sink the whole build
                    say(f"[walkthrough] scene {new_i} failed: {type(e).__name__}: {e}")
            if on_scene:
                on_scene(new_i, "done" if ok else "failed")
        restitch_and_save(built, workspace, log=say)   # stitch the narrated clips + persist project.json
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

    # --- crash recovery (a build killed mid-run leaves clips on disk but an unsaved project) -----
    def _recover_project(self, pid: str, project: VideoProject) -> bool:
        """Reconcile project.json with what actually rendered on disk. A build that dies mid-run (e.g.
        the server is restarted while rendering) leaves finished scene clips in scenes/scene_<n>/ but
        never updates project.json — so the good scenes look 'unbuilt' and no final.mp4 gets stitched.
        This fills every unbuilt node from its scene dir (index- or sid-keyed) and, if all scenes are
        present but the video was never finalized, stitches it. Returns True if anything was recovered."""
        scenes_dir = self.workspace(pid) / "scenes"
        changed = False
        for node in project.scenes:
            if node.mp4 and Path(node.mp4).exists():
                continue
            for cand in (f"scene_{node.index}", f"scene_{node.sid}"):
                if self._fill_node_from_dir(node, scenes_dir / cand):
                    changed = True
                    break
        if changed:
            self.save(pid, project)
        if project.scenes and all(n.mp4 for n in project.scenes):
            final_ok = bool(project.final_mp4) and Path(project.final_mp4).exists()
            if not final_ok:
                try:
                    restitch_and_save(project, self.workspace(pid), log=lambda _m: None)
                    changed = True
                except Exception:  # noqa: BLE001 — recovery is best-effort; a stitch hiccup mustn't crash startup
                    pass
        return changed

    def recover_all(self) -> list[str]:
        """Scan every workspace once (e.g. at server startup) and recover any project left half-built by
        an interrupted run. Skips already-complete projects cheaply. Returns the recovered project ids."""
        recovered: list[str] = []
        for d in sorted(self.root.iterdir() if self.root.exists() else []):
            if not (d / "project.json").exists():
                continue
            try:
                project = self.load(d.name)
            except Exception:  # noqa: BLE001 — a half-written project shouldn't break recovery of the rest
                continue
            done = (bool(project.final_mp4) and Path(project.final_mp4).exists()
                    and bool(project.scenes) and all(n.mp4 for n in project.scenes))
            if done:
                continue
            try:
                if self._recover_project(d.name, project):
                    recovered.append(d.name)
            except Exception:  # noqa: BLE001
                continue
        return recovered

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
                                  client=traced(self._client_or_default(), log), structural=True, quality=quality,
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
    def export(self, pid: str, *, subtitles: str = "none", fmt: str = "youtube", log=print) -> dict:
        # per-format out_name: the two deliverables share a work dir and must not clobber each other
        return export_mod.export(self.load(pid), out_dir=self.workspace(pid) / "export",
                                 subtitles=subtitles, fmt=fmt, out_name=f"export-{fmt}.mp4", log=log)

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

    # --- developer inspection (the exact prompt + generated code for one scene) --------------
    def scene_source(self, pid: str, index: int) -> dict:
        """Everything a developer wants to see for ONE scene: the generated Manim code, the scene
        spec, the narration, and the EXACT system/user prompts the codegen used (reconstructed from
        the same builders the pipeline calls — structural is the finalized path). Read-only."""
        from core.schemas.scene_spec import SCENE_CLASS
        from generation import lattice_scene

        node = self.load(pid).scene(index)
        spec = node.spec
        system_prompt = lattice_scene.structural_system_prompt()
        if spec is not None:
            user_prompt = ("Scene spec (JSON):\n" + spec.model_dump_json(indent=2)
                           + f"\n\nGenerate the complete Manim CE file. The Scene subclass MUST be "
                             f"named `{SCENE_CLASS}`.")
            spec_json = spec.model_dump_json(indent=2)
        else:
            user_prompt = "(scene not generated yet — build it to see the codegen prompt)"
            spec_json = ""
        # show just the generated scene, not the ~300-line LatticeScene scaffold prepended to it
        code = node.code or ""
        marker = f"class {SCENE_CLASS}"
        scene_only = code[code.index(marker):] if marker in code else code
        return {
            "index": index,
            "title": node.title,
            "built": bool(node.mp4),
            "score": node.score,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "spec": spec_json,
            "code": scene_only,
            "code_full": code,
            "narration": list(node.script),
        }

    def scene_mp4(self, pid: str, index: int) -> Path | None:
        node = self.load(pid).scene(index)
        return Path(node.mp4) if node.mp4 and Path(node.mp4).exists() else None

    def final_mp4(self, pid: str) -> Path | None:
        p = self.load(pid)
        return Path(p.final_mp4) if p.final_mp4 and Path(p.final_mp4).exists() else None

    def ensure_final(self, pid: str) -> Path | None:
        """The stitched video ON THIS DISK, pulled back from object storage if the container no
        longer has it (a redeploy wiped `out/`, or r2_delete_local freed it). Export/burn-in/reframe
        all read the file, so they need it local — this is what makes those survive a restart."""
        local = self.final_mp4(pid)
        if local:
            return local
        project = self.load(pid)
        dest = (Path(project.final_mp4) if project.final_mp4
                else self.workspace(pid) / "final" / "final.mp4")
        return storage.get(storage.video_key(pid), dest)


# --- DTOs (plain dicts the API serializes; keeps pydantic models off the wire) --------------

def project_dto(pid: str, project: VideoProject) -> dict:
    return {
        "id": pid,
        "topic": project.topic,
        "final_ready": bool(project.final_mp4),
        "target_seconds": project.target_seconds,
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
