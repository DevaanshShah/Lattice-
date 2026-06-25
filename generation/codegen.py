"""FR-2 / FR-8 — SceneSpec -> Manim CE code, gated by the guardrails.

Generation is retried with guardrail violations fed back until the code is clean (no CE/GL
mixing, no deprecated calls, has the GeneratedScene/construct shape) or attempts run out.
Whether it actually *renders* is M2's job (compile-repair loop); here we only guarantee the
code is well-formed CE that targets the pinned version.
"""
from __future__ import annotations

from core.config import settings
from core.llm import LLMClient, get_client
from core.schemas.scene_spec import SCENE_CLASS, SceneSpec
from core.textutil import strip_code_fences
from generation import guardrails, lattice_scene
from prompts.loader import load


class CodegenError(RuntimeError):
    pass


def _finalize(code: str, structural: bool) -> str:
    """In structural mode, prepend the LatticeScene base so the generated GeneratedScene resolves it."""
    return (lattice_scene.LATTICE_SCENE_SRC + "\n\n" + code) if structural else code


def generate(spec: SceneSpec, *, attempts: int = 3, client: LLMClient | None = None,
             style=None) -> str:
    client = client or get_client()
    structural = settings.structural_layout
    system = load("manim-conventions") + "\n\n---\n\n" + load("lattice-codegen" if structural else "codegen")
    if style is not None:
        system += "\n\n---\n\n" + style.as_prompt()
    user = (
        "Scene spec (JSON):\n" + spec.model_dump_json(indent=2)
        + f"\n\nGenerate the complete Manim CE file. The Scene subclass MUST be named `{SCENE_CLASS}`."
    )
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]

    last: list[guardrails.Issue] = []
    for _ in range(attempts):
        raw = client.chat(messages)
        code = strip_code_fences(raw)
        issues = guardrails.check(code, structural=structural)
        if not issues:
            return _finalize(code, structural)
        last = issues
        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content": (
            "Fix these guardrail violations and resend the FULL file (code only):\n"
            + "\n".join(f"- {i.message}" for i in issues)
        )})
    raise CodegenError(f"guardrails not satisfied after {attempts} attempts: {[i.rule for i in last]}")


def generate_narrated(spec: SceneSpec, beats_audio: list[tuple[str, str, float]], *,
                      attempts: int = 3, client: LLMClient | None = None, style=None) -> str:
    """SceneSpec + per-beat (narration, audio_path, duration) -> narrated Manim code (M4).

    Same guardrails as `generate`, plus it must wire the audio: the code must call
    `self.add_sound(...)` (else the scene would be silent), and is regenerated until it does.
    A `style` (M5) is injected so narrated multi-scene videos stay visually consistent too.
    """
    client = client or get_client()
    structural = settings.structural_layout
    system = load("manim-conventions") + "\n\n---\n\n" + load(
        "lattice-codegen-narrated" if structural else "codegen-narrated")
    if style is not None:
        system += "\n\n---\n\n" + style.as_prompt()
    rows = "\n".join(
        f"Beat {i + 1}: narration={line!r} audio={path!r} duration={dur:.2f}s"
        for i, (line, path, dur) in enumerate(beats_audio)
    )
    user = (
        "Scene spec (JSON):\n" + spec.model_dump_json(indent=2)
        + f"\n\nNarration + audio per beat:\n{rows}\n\n"
        f"Generate the complete narrated Manim file. The Scene subclass MUST be named `{SCENE_CLASS}`."
    )
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]

    last: list[guardrails.Issue] = []
    for _ in range(attempts):
        raw = client.chat(messages)
        code = strip_code_fences(raw)
        issues = guardrails.check(code, structural=structural)
        if "add_sound" not in code:
            issues = issues + [guardrails.Issue("no-audio", "must call self.add_sound(...) for each beat's audio")]
        if not issues:
            return _finalize(code, structural)
        last = issues
        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content": (
            "Fix these and resend the FULL file (code only):\n"
            + "\n".join(f"- {i.message}" for i in issues)
        )})
    raise CodegenError(f"narrated codegen failed after {attempts} attempts: {[i.rule for i in last]}")
