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
                        style=project.style, log=log)
    node.spec = spec
    node.code = res.code
    node.compiled = res.compiled
    node.mp4 = str(res.mp4) if res.mp4 else None
    node.srt = str(res.srt) if res.srt else None
    node.script = list(res.lines)   # persist narration text (rollback reproducibility, FR-21)
    return node


def generate_video(topic: str, *, approve_fn=None, quality: str = "preview",
                   out_dir: str | Path | None = None, client: LLMClient | None = None,
                   cap: int | None = None, log=print) -> VideoProject:
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
    scenes_dir = out / "scenes"

    say(f"-> building {len(project.scenes)} scenes in parallel (cap={cap or settings.concurrency_cap})")
    pool.run_bounded(
        project.scenes,
        lambda node, _i: build_scene(node, project, scenes_dir=scenes_dir,
                                     quality=quality, client=client, log=say),
        cap=cap,
    )  # build_scene mutates each node in place

    ready = project.ordered_mp4s()
    say(f"   {len(ready)}/{len(project.scenes)} scene(s) rendered")
    if ready:
        say("-> stitching final video")
        project.final_mp4 = str(stitch.stitch(ready, work_dir=out, out_name="final.mp4"))

    project.save(out / "project.json")
    return project
