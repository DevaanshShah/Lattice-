"""Generate a video into a MODEL-TAGGED test folder, for side-by-side model comparison.

    python -m scripts.test_video "<topic>" [--max-scenes N] [--quality preview|final]

Switch LATTICE_LLM_MODEL in .env between runs; each run saves under the model's own folder and
appends a row to the comparison index, so you can watch them back-to-back and pick the best.

Layout:
    out/model_tests/index.md                          <- comparison table (model | topic | scenes)
    out/model_tests/<model>/<topic>/final.mp4         <- the video for that model
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from composition import video
from core.config import settings
from core.console import enable_utf8


def _slug(s: str, n: int = 48) -> str:
    return (re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower())[:n] or "untitled"


def append_index(test_root: Path, *, model: str, topic: str, rendered: int, total: int,
                 quality: str, final_path: str | None) -> Path:
    idx = Path(test_root) / "index.md"
    if not idx.exists():
        idx.parent.mkdir(parents=True, exist_ok=True)
        idx.write_text("# Model comparison — test videos\n\n"
                       "| model | topic | scenes rendered | quality | video |\n"
                       "|---|---|---|---|---|\n", encoding="utf-8")
    rel = Path(final_path).relative_to(test_root).as_posix() if final_path else "(none)"
    with idx.open("a", encoding="utf-8") as f:
        f.write(f"| `{model}` | {topic} | {rendered}/{total} | {quality} | {rel} |\n")
    return idx


def main(argv: list[str] | None = None) -> int:
    import argparse

    enable_utf8()
    ap = argparse.ArgumentParser(description="Generate a model-tagged test video for comparison.")
    ap.add_argument("topic")
    ap.add_argument("--max-scenes", type=int, default=3)
    ap.add_argument("--quality", choices=["preview", "final"], default="preview")
    args = ap.parse_args(argv)

    from scripts.generate_video import _make_approver  # reuse the outline approver (auto + cap)

    model = settings.llm_model
    test_root = settings.out_dir / "model_tests"
    out_dir = test_root / _slug(model) / _slug(args.topic)

    print(f"-> testing model: {model}")
    proj = video.generate_video(
        args.topic, approve_fn=_make_approver(True, args.max_scenes),
        quality=args.quality, out_dir=out_dir, log=print,
    )
    rendered = sum(1 for s in proj.scenes if s.mp4)
    final = proj.final_mp4 if (proj.final_mp4 and Path(proj.final_mp4).exists()) else None

    idx = append_index(test_root, model=model, topic=args.topic, rendered=rendered,
                       total=len(proj.scenes), quality=args.quality, final_path=final)
    print("---")
    print(f"[{'OK' if final else 'X'}] {model}: {rendered}/{len(proj.scenes)} scenes -> {final or 'no video'}")
    print(f"-> comparison index: {idx}")
    return 0 if final else 1


if __name__ == "__main__":
    sys.exit(main())
