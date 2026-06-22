"""FR-27 — the `generate-scene` CLI. One command: prompt -> verified MP4.

Wraps the M2 verify pipeline (compile-repair + vision critic + best-of-N) and layers the
content-hash cache on top: the SAME prompt+model+quality re-runs with ZERO LLM/render calls
(a full cache hit). `--no-cache` forces a fresh run.

    python -m cli "<prompt>" [--quality preview|final] [--best-of N] [--no-cache]

`pipeline` and `cache` are injectable so the cache/orchestration logic is unit-testable
without Docker or a model.
"""
from __future__ import annotations

import sys
from pathlib import Path

from core import cache as cache_mod
from core.config import settings
from core.console import enable_utf8


def generate_scene(
    prompt: str,
    *,
    quality: str = "preview",
    best_of: int = 1,
    no_cache: bool = False,
    out_dir: str | Path | None = None,
    cache: cache_mod.Cache | None = None,
    pipeline=None,
    model: str | None = None,
    log=print,
) -> dict:
    cache = cache if cache is not None else cache_mod.default_cache()
    out = Path(out_dir) if out_dir else settings.out_dir / "scenes"
    out.mkdir(parents=True, exist_ok=True)
    model = model or settings.llm_model
    pkey = cache_mod.spec_key(prompt, model=model)

    # full hit: same prompt -> reuse the stored render, no LLM, no Docker
    if not no_cache and cache.has(pkey):
        man = cache.load(pkey) or {}
        mp4 = man.get("mp4")
        if mp4 and Path(mp4).exists():
            log(f"[cache] hit -> {mp4} (no LLM, no render)")
            return {**man, "cached": True}

    # miss: run the real pipeline (lazy import — needs the key + Docker)
    if pipeline is None:
        from verification.run import run_pipeline
        pipeline = run_pipeline
    pr = pipeline(prompt, best_of=best_of, quality=quality, out_dir=out, log=log)
    r = getattr(pr, "result", None)
    mp4 = str(r.mp4) if (r and getattr(r, "mp4", None)) else None
    manifest = {
        "prompt": prompt, "model": model, "quality": quality, "mp4": mp4,
        "passed": bool(r and getattr(r, "passed", False)),
        "score": (r.score() if (r and hasattr(r, "score")) else -1),
        "cached": False,
    }
    if not no_cache and mp4:
        manifest = {**cache.save(pkey, manifest, copy={"mp4": Path(mp4)}), "cached": False}
    return manifest


def main(argv: list[str] | None = None) -> int:
    import argparse

    enable_utf8()
    ap = argparse.ArgumentParser(prog="generate-scene",
                                 description="Prompt -> verified Manim scene MP4 (M3 CLI).")
    ap.add_argument("prompt")
    ap.add_argument("--quality", choices=["preview", "final"], default="preview")
    ap.add_argument("--best-of", type=int, default=1)
    ap.add_argument("--no-cache", action="store_true", help="bypass the content-hash cache")
    args = ap.parse_args(argv)

    res = generate_scene(args.prompt, quality=args.quality, best_of=args.best_of,
                         no_cache=args.no_cache)
    print("---")
    if res.get("mp4"):
        tag = "cache hit" if res.get("cached") else ("passed both layers" if res.get("passed") else "best attempt")
        print(f"[OK] {tag}: {res['mp4']}  (score={res.get('score')})")
        return 0
    print("[X] no scene produced.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
