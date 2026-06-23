"""M5 orchestrator — topic -> approved outline -> styled, narrated, parallel-rendered scenes
-> one stitched video. Composes the planner + style + M1–M4 build + DAG + bounded pool + stitch.

`build_scene` (expand -> narrate one scene with the shared style) is the unit both the parallel
build and isolated regeneration (regen.py) reuse.
"""
from __future__ import annotations

from pathlib import Path

from composition import pool, stitch
from composition.scene_dag import SceneNode, VideoProject
from core.config import settings
from core.llm import LLMClient, get_client
from core.schemas.outline import Outline, OutlineItem
from generation import style as style_gen
from narration import narrate
from planner import expand as planner_expand
from planner import outline as planner_outline


def _outline_of(project: VideoProject) -> Outline:
    return Outline(topic=project.topic,
                   items=[OutlineItem(title=s.title, intent=s.intent) for s in project.scenes])


def _story_context(project: VideoProject, idx: int) -> str:
    """The narration's story arc: where this scene sits in the whole video + what's around it, so
    the narrator links scenes into one continuous lesson (callbacks/bridges) instead of isolated clips.
    Uses the outline (titles+intents — known up front, so it works during parallel build)."""
    n = len(project.scenes)
    if n <= 1:
        return ""
    arc = "\n".join(f"  {i + 1}. {s.title} — {s.intent}" for i, s in enumerate(project.scenes))
    lines = [f'STORY CONTEXT — this is scene {idx + 1} of {n} in ONE continuous explainer video on '
             f'"{project.topic}". It is part of a flowing lesson, not a standalone clip.',
             "Full arc, in order:", arc]
    prev = [s.title for s in project.scenes[:idx]]
    if prev:
        lines.append(f'Scenes BEFORE this one already covered: {", ".join(prev)}. OPEN by connecting to '
                     'what the viewer just saw (e.g. "Now that we have a single neuron, ..."); do NOT '
                     're-introduce those ideas from scratch.')
    if idx + 1 < n:
        lines.append(f'The NEXT scene is "{project.scenes[idx + 1].title}". END with a short bridge that '
                     'leads into it, so the video flows.')
    lines.append("Write it like a great explainer-YouTube narrator teaching a story: warm, connected, "
                 "building on what we already know.")
    return "\n".join(lines)


def build_scene(node: SceneNode, project: VideoProject, *, scenes_dir: Path,
                quality: str, client: LLMClient, log=print) -> SceneNode:
    """Build one scene: (expand if needed) -> narrate+render with the shared style.

    Mutates and returns `node`. Reuses `node.spec` when it already exists (so re-time/tweak/regen
    are deterministic and don't silently re-author the scene); only expands a fresh scene. The
    work dir is keyed off the IMMUTABLE `node.sid`, so reorder/insert never collide. Each call
    uses its own dir, so parallel builds don't clash.
    """
    if node.spec is None:
        item = OutlineItem(title=node.title, intent=node.intent)
        spec = planner_expand.expand(item, _outline_of(project), node.index, client=client)
    else:
        spec = node.spec
    wd = scenes_dir / f"scene_{node.sid}"
    res = narrate.build(spec, work_dir=wd, quality=quality, client=client,
                        style=project.style, context=_story_context(project, node.index), log=log)
    node.spec = spec
    node.code = res.code
    node.compiled = res.compiled
    node.mp4 = str(res.mp4) if res.mp4 else None
    node.srt = str(res.srt) if res.srt else None
    node.script = list(res.lines)   # persist narration text (rollback reproducibility, FR-21)
    return node


def build_project(project: VideoProject, *, quality: str = "preview",
                  out_dir: str | Path, client: LLMClient | None = None, cap: int | None = None,
                  log=print, on_scene=None) -> VideoProject:
    """Build all scenes of an already-planned project (style set) in parallel, stitch, persist.

    The post-approval half of generate_video, factored out so the web layer (M7) can drive it
    after its own outline-approval gate WITHOUT re-planning. `on_scene(index, status)` fires with
    status in {"rendering","done","failed"} around each scene so a UI can show live per-scene
    state (FR-24/FR-29). Failure isolation is unchanged: a scene failing doesn't abort the rest.
    """
    client = client or get_client()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    say = log or (lambda _m: None)
    scenes_dir = out / "scenes"

    def work(node: SceneNode, _i: int) -> SceneNode:
        if on_scene:
            on_scene(node.index, "rendering")
        try:
            build_scene(node, project, scenes_dir=scenes_dir, quality=quality, client=client, log=say)
        except Exception:
            if on_scene:
                on_scene(node.index, "failed")
            raise
        if on_scene:
            on_scene(node.index, "done" if node.mp4 else "failed")
        return node

    say(f"-> building {len(project.scenes)} scenes in parallel (cap={cap or settings.concurrency_cap})")
    pool.run_bounded(project.scenes, work, cap=cap)  # build_scene mutates each node in place

    ready = project.ordered_mp4s()
    say(f"   {len(ready)}/{len(project.scenes)} scene(s) rendered")
    if ready:
        say("-> stitching final video")
        project.final_mp4 = str(stitch.stitch(ready, work_dir=out, out_name="final.mp4"))

    project.save(out / "project.json")
    return project


def generate_video(topic: str, *, approve_fn=None, quality: str = "preview",
                   out_dir: str | Path | None = None, client: LLMClient | None = None,
                   cap: int | None = None, log=print, on_scene=None) -> VideoProject:
    client = client or get_client()
    out = Path(out_dir) if out_dir else settings.out_dir / "video"
    out.mkdir(parents=True, exist_ok=True)
    say = log or (lambda _m: None)

    say(f"-> planning outline for: {topic!r}")
    outline = planner_outline.generate(topic, client=client)
    if approve_fn is not None:
        outline = approve_fn(outline)          # the approval gate, BEFORE any render
    say(f"   {len(outline.items)} scene(s) approved")

    say("-> style spec (one per video)")
    style = style_gen.generate(topic, outline, client=client)

    project = VideoProject.from_outline(outline, style=style)
    return build_project(project, quality=quality, out_dir=out, client=client, cap=cap,
                         log=say, on_scene=on_scene)
