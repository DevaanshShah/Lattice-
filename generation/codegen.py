"""FR-2 / FR-8 — SceneSpec -> Manim CE code, gated by the guardrails.

Generation is retried with guardrail violations fed back until the code is clean (no CE/GL
mixing, no deprecated calls, has the GeneratedScene/construct shape) or attempts run out.
Whether it actually *renders* is M2's job (compile-repair loop); here we only guarantee the
code is well-formed CE that targets the pinned version.
"""
from __future__ import annotations

from core.llm import LLMClient, get_client
from core.schemas.scene_spec import SCENE_CLASS, SceneSpec
from core.textutil import strip_code_fences
from generation import guardrails
from prompts.loader import load


class CodegenError(RuntimeError):
    pass


def generate(spec: SceneSpec, *, attempts: int = 3, client: LLMClient | None = None) -> str:
    client = client or get_client()
    system = load("manim-conventions") + "\n\n---\n\n" + load("codegen")
    user = (
        "Scene spec (JSON):\n" + spec.model_dump_json(indent=2)
        + f"\n\nGenerate the complete Manim CE file. The Scene subclass MUST be named `{SCENE_CLASS}`."
    )
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]

    last: list[guardrails.Issue] = []
    for _ in range(attempts):
        raw = client.chat(messages)
        code = strip_code_fences(raw)
        issues = guardrails.check(code)
        if not issues:
            return code
        last = issues
        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content": (
            "Fix these guardrail violations and resend the FULL file (code only):\n"
            + "\n".join(f"- {i.message}" for i in issues)
        )})
    raise CodegenError(f"guardrails not satisfied after {attempts} attempts: {[i.rule for i in last]}")
