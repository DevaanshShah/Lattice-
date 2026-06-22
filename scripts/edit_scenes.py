"""M6 — edit the current video at the scene level (operates on out/video/project.json).

    python -m scripts.edit_scenes list
    python -m scripts.edit_scenes reorder <from> <to>
    python -m scripts.edit_scenes delete <index>
    python -m scripts.edit_scenes insert <pos> --title T --intent I
    python -m scripts.edit_scenes edit-narration <index> --line "..." --line "..."
    python -m scripts.edit_scenes tweak <index> "<instruction>"
    python -m scripts.edit_scenes history <index>
    python -m scripts.edit_scenes rollback <index> <version>

reorder/delete/rollback re-render NOTHING (reuse clips + re-stitch). insert/edit-narration/tweak
re-render ONLY the affected scene. LIVE for the LLM ops; reorder/delete/rollback/list/history
need only Docker (ffmpeg) or nothing.
"""
from __future__ import annotations

import sys
from pathlib import Path

from composition.scene_dag import VideoProject
from core.config import settings
from core.console import enable_utf8


def _project_path() -> Path:
    return settings.out_dir / "video" / "project.json"


def _show(project: VideoProject) -> None:
    print(f"Video: {project.topic}  ({len(project.scenes)} scenes)  final={project.final_mp4}")
    for s in project.scenes:
        print(f"  {s.index}. {s.title}  [{len(s.versions)} versions]  mp4={'yes' if s.mp4 else 'NO'}")


def main(argv: list[str] | None = None) -> int:
    import argparse

    enable_utf8()
    ap = argparse.ArgumentParser(description="Scene-level editing of the current video (M6).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list")
    p = sub.add_parser("reorder"); p.add_argument("frm", type=int); p.add_argument("to", type=int)
    p = sub.add_parser("delete"); p.add_argument("index", type=int)
    p = sub.add_parser("insert"); p.add_argument("pos", type=int); p.add_argument("--title", required=True); p.add_argument("--intent", required=True)
    p = sub.add_parser("edit-narration"); p.add_argument("index", type=int); p.add_argument("--line", action="append", required=True, dest="lines")
    p = sub.add_parser("tweak"); p.add_argument("index", type=int); p.add_argument("instruction")
    p = sub.add_parser("history"); p.add_argument("index", type=int)
    p = sub.add_parser("rollback"); p.add_argument("index", type=int); p.add_argument("version", type=int)
    for name in ("reorder", "delete", "insert", "edit-narration", "tweak", "rollback"):
        sub.choices[name].add_argument("--quality", choices=["preview", "final"], default="preview")
    args = ap.parse_args(argv)

    path = _project_path()
    if not path.exists():
        print(f"[X] no project at {path} — run `python -m scripts.generate_video` first.")
        return 1
    project = VideoProject.load(path)
    out = path.parent

    if args.cmd == "list":
        _show(project)
        return 0
    if args.cmd == "history":
        node = project.scene(args.index)
        print(f"Scene {args.index} ({node.title}) — {len(node.versions)} version(s):")
        for v in node.versions:
            print(f"  v{v.version}: {v.label or '(unlabeled)'}  score={v.score}")
        return 0

    if args.cmd == "reorder":
        from editing import arrange
        arrange.reorder(project, args.frm, args.to, out_dir=out, log=print)
    elif args.cmd == "delete":
        from editing import arrange
        arrange.delete(project, args.index, out_dir=out, log=print)
    elif args.cmd == "insert":
        from editing import arrange
        arrange.insert(project, args.pos, args.title, args.intent, out_dir=out, quality=args.quality, log=print)
    elif args.cmd == "edit-narration":
        from editing import narration_edit
        narration_edit.edit_narration(project, args.index, args.lines, out_dir=out, quality=args.quality, log=print)
    elif args.cmd == "tweak":
        from editing import tweak
        tweak.tweak_scene(project, args.index, args.instruction, out_dir=out, quality=args.quality, log=print)
    elif args.cmd == "rollback":
        from editing import history
        history.rollback(project, args.index, args.version, out_dir=out, log=print)

    print("---")
    _show(project)
    return 0


if __name__ == "__main__":
    sys.exit(main())
