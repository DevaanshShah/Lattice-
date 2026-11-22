"""M1 driver - prompt -> scene spec -> Manim code (+ guardrails). Optionally render once.

    python -m scripts.gen_scene "<prompt>" [--render]

Writes out/m1/spec.json and out/m1/scene.py. With --render it attempts a single sandboxed
render (no repair loop yet — that's M2), so a failed render here is expected sometimes.
Needs LATTICE_LLM_API_KEY set (in .env).
"""
from __future__ import annotations

import argparse
import sys

from core.config import settings
from core.schemas.scene_spec import SCENE_CLASS
from generation import codegen, guardrails
from generation import scene_spec as ss


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("prompt")
    ap.add_argument("--render", action="store_true", help="attempt one sandboxed render (no repair)")
    args = ap.parse_args()

    out = settings.out_dir / "m1"
    out.mkdir(parents=True, exist_ok=True)

    print(f"-> generating scene spec for: {args.prompt!r}")
    spec = ss.generate(args.prompt)
    (out / "spec.json").write_text(spec.model_dump_json(indent=2), encoding="utf-8")
    print(f"[OK] scene spec: {len(spec.objects)} objects, {len(spec.beats)} beats -> {out / 'spec.json'}")
    print(f"     title: {spec.title}")

    print("-> generating Manim code...")
    code = codegen.generate(spec)
    (out / "scene.py").write_text(code, encoding="utf-8")
    issues = guardrails.check(code)
    verdict = "clean" if not issues else ", ".join(i.rule for i in issues)
    print(f"[OK] code -> {out / 'scene.py'} | guardrails: {verdict}")

    if args.render:
        from render import sandbox
        print("-> rendering once (no repair loop yet - that's M2)...")
        res = sandbox.render(out, "scene.py", SCENE_CLASS, quality="preview")
        if res.ok:
            mp4 = next((o for o in res.outputs if o.suffix == ".mp4"), None)
            print(f"[OK] rendered: {mp4}")
        else:
            print(res.stderr[-1500:])
            print("[!] render failed - expected sometimes at M1; M2 adds the auto-repair loop.")

    print("---")
    print("[OK] M1 generation path works.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
