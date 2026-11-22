"""Shared editing helper: re-stitch the (mostly reused) clips and persist the project."""
from __future__ import annotations

from pathlib import Path

from composition import stitch
from composition.scene_dag import VideoProject


def restitch_and_save(project: VideoProject, out_dir: str | Path, *, log=None) -> None:
    out = Path(out_dir)
    ready = project.ordered_mp4s()
    project.final_mp4 = str(stitch.stitch(ready, work_dir=out, out_name="final.mp4")) if ready else None
    project.save(out / "project.json")
