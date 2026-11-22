"""FR-16 — regenerate ONE scene in isolation, reuse the rest, re-stitch.

Touches only scene `index`; every other scene's clip is reused from disk unchanged. This is
the seam M6's editing (reorder/tweak/rollback) builds on — isolation is the whole game.
"""
from __future__ import annotations

from pathlib import Path

from composition import stitch, video
from composition.scene_dag import VideoProject
from core.config import settings
from core.llm import LLMClient, get_client


def regenerate_scene(project: VideoProject, index: int, *, out_dir: str | Path,
                     quality: str = "preview", client: LLMClient | None = None,
                     log=print) -> VideoProject:
    client = client or get_client()
    out = Path(out_dir)
    scenes_dir = out / "scenes"
    say = log or (lambda _m: None)

    node = project.scene(index)
    say(f"-> regenerating scene {index}: {node.title} (others reused)")

    # failure-safety: keep the prior good render if the rebuild doesn't produce a clip, so a
    # failed regen never drops the scene from the stitch or persists a regression.
    prior = node.model_copy(deep=True)
    video.build_scene(node, project, scenes_dir=scenes_dir, quality=quality, client=client, log=say)
    if not node.mp4:
        say(f"[regen] scene {index} did not render; keeping the prior good clip")
        project.scenes[index] = prior
        return project

    ready = project.ordered_mp4s()
    if ready:
        say("-> re-stitching")
        project.final_mp4 = str(stitch.stitch(ready, work_dir=out, out_name="final.mp4",
                                              timeout=settings.render_timeout_s))
    project.save(out / "project.json")
    return project
