"""FR-17 — reorder / add / delete scenes. Scene-level, isolated, re-stitched.

- reorder/delete render NOTHING — every existing clip is reused from disk (isolation invariant).
- insert renders ONLY the new scene (inheriting the video's style), with failure-rollback so a
  failed render never leaves the project half-mutated.
- every op renumbers via project.reindex() (DAG consistency) and re-stitches from the
  (mostly reused) clips, then persists. "A list with a stitch button, not Premiere."
"""
from __future__ import annotations

from pathlib import Path

from composition import stitch, video
from composition.scene_dag import SceneNode, VideoProject
from core.llm import LLMClient, get_client


def _restitch_and_save(project: VideoProject, out_dir: str | Path, *, log) -> None:
    out = Path(out_dir)
    ready = project.ordered_mp4s()
    project.final_mp4 = str(stitch.stitch(ready, work_dir=out, out_name="final.mp4")) if ready else None
    project.save(out / "project.json")


def reorder(project: VideoProject, frm: int, to: int, *, out_dir: str | Path, log=print) -> VideoProject:
    n = len(project.scenes)
    if not (0 <= frm < n and 0 <= to < n):
        raise IndexError(f"reorder out of range: {frm}->{to} (have {n} scenes)")
    say = log or (lambda _m: None)
    node = project.scenes.pop(frm)
    project.scenes.insert(to, node)
    project.reindex()
    say(f"-> reordered scene {frm} -> {to}; re-stitching (no re-render)")
    _restitch_and_save(project, out_dir, log=say)
    return project


def delete(project: VideoProject, index: int, *, out_dir: str | Path, log=print) -> VideoProject:
    n = len(project.scenes)
    if not (0 <= index < n):
        raise IndexError(f"delete out of range: {index} (have {n} scenes)")
    if n == 1:
        raise ValueError("cannot delete the only scene")
    say = log or (lambda _m: None)
    removed = project.scenes.pop(index)
    project.reindex()
    say(f"-> deleted scene {index} ({removed.title}); re-stitching (no re-render)")
    _restitch_and_save(project, out_dir, log=say)
    return project


def insert(project: VideoProject, pos: int, title: str, intent: str, *, out_dir: str | Path,
           quality: str = "preview", client: LLMClient | None = None, log=print) -> VideoProject:
    client = client or get_client()
    say = log or (lambda _m: None)
    pos = max(0, min(pos, len(project.scenes)))
    node = SceneNode(index=pos, title=title, intent=intent)  # fresh sid -> own work dir
    project.scenes.insert(pos, node)
    project.reindex()

    say(f"-> inserting scene at {pos}: {title!r} (generating only this scene, inherits style)")
    video.build_scene(node, project, scenes_dir=Path(out_dir) / "scenes",
                      quality=quality, client=client, log=say)
    if not node.mp4:
        # failure atomicity: undo the insert so a failed render leaves the project unchanged
        say("[insert] new scene did not render; rolling back the insert")
        project.scenes.remove(node)
        project.reindex()
        return project

    _restitch_and_save(project, out_dir, log=say)
    return project
