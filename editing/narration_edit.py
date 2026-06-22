"""FR-18 — edit a scene's narration text and re-time, scene k ONLY.

Reuses the scene's EXISTING spec (build path reuses node.spec), so editing the words does not
re-author the visuals: only TTS + narrated-codegen + render + captions re-run for scene k, using
the supplied lines verbatim. Every other scene's clip is reused unchanged; then re-stitch.
"""
from __future__ import annotations

from pathlib import Path

from composition.scene_dag import VideoProject
from core.llm import LLMClient, get_client
from editing._common import restitch_and_save
from narration import narrate


def edit_narration(project: VideoProject, index: int, new_lines: list[str], *,
                   out_dir: str | Path, quality: str = "preview",
                   client: LLMClient | None = None, log=print) -> VideoProject:
    if not (0 <= index < len(project.scenes)):
        raise IndexError(f"scene index {index} out of range (have {len(project.scenes)})")
    node = project.scene(index)
    if node.spec is None:
        raise ValueError(f"scene {index} hasn't been generated yet — build it before editing narration")
    if not new_lines or not any(s.strip() for s in new_lines):
        raise ValueError("narration cannot be empty")

    client = client or get_client()
    say = log or (lambda _m: None)
    say(f"-> editing narration for scene {index} ({node.title}); re-timing scene {index} ONLY")

    wd = Path(out_dir) / "scenes" / f"scene_{node.sid}"
    res = narrate.build(node.spec, work_dir=wd, quality=quality, client=client,
                        style=project.style, lines=list(new_lines), log=say)
    if not res.mp4:
        # failure-safety: the failed re-render didn't overwrite the final clip; keep prior state
        say(f"[edit] scene {index} re-render failed; keeping the prior narration + clip")
        return project

    node.code = res.code
    node.compiled = res.compiled
    node.mp4 = str(res.mp4)
    node.srt = str(res.srt) if res.srt else node.srt
    node.script = list(res.lines)
    restitch_and_save(project, out_dir, log=say)
    return project
