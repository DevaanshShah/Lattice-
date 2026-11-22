"""FR-2 / FR-8 — SceneSpec -> Manim CE code, gated by the guardrails.

Generation is retried with guardrail violations fed back until the code is clean (no CE/GL
mixing, no deprecated calls, has the GeneratedScene/construct shape) or attempts run out.
Whether it actually *renders* is M2's job (compile-repair loop); here we only guarantee the
code is well-formed CE that targets the pinned version.
"""
from __future__ import annotations

import re

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


def _pattern_prompt(spec: SceneSpec) -> str:
    """Small recipe-to-existing-Lattice mapping; it adds no renderer or primitives."""
    patterns = {
        "architecture_map": "Use an architecture map: named systems are `self.node(...)` or "
                            "`self.labeled_box(...)` groups, each label owned by its group; connect them "
                            "with `self.connect(...)` arrows that show the actual data/control direction.",
        "workflow_flow": "Use one `self.flow([...])` for the ordered steps, placed as a single group. "
                         "Do not hand-place a sequence of sibling boxes and arrows.",
        "funnel": "Use a clear narrowing funnel: three to five labeled boxes, widest at the first stage "
                  "and narrower toward the outcome, each in its own grid area with directional connectors.",
        "metric_hero": "Use one large central metric label as the visual hero, with at most two supporting "
                       "labels. Do not turn this into a busy system diagram.",
        "before_after": "Use two clearly separated labeled groups: BEFORE on the left and AFTER on the right. "
                        "Keep labels inside their owning groups and animate the comparison in sequence.",
    }
    return "\n\nRECIPE VISUAL PATTERN — " + patterns.get(spec.visual_pattern, "") if spec.visual_pattern else ""


def _continuity_prompt(spec: SceneSpec) -> str:
    continuity = spec.continuity
    if not continuity or not continuity.anchor_layouts:
        return ""
    anchors = ", ".join(continuity.carryover_ids)
    layout_contract = ", ".join(
        f"{object_id} at {layout.cell}, w={layout.width}, h={layout.height}"
        for object_id, layout in continuity.anchor_layouts.items()
    )
    incoming = (
        f"Carryover object ids: {anchors}. Create and place every carryover object FIRST, then call "
        "`self.add(...)` on it BEFORE the first self.add_sound/self.play so it is already visible in frame one. "
        "Do NOT Create/Write/FadeIn/Grow a carryover anchor again. "
        if continuity.carryover_ids else ""
    )
    return (
        "\n\nVISUAL CONTINUITY — this scene continues the prior scene. "
        f"Opening state: {continuity.opening_state}. Closing state: {continuity.closing_state}. {incoming}"
        f"Stable layout contract: {layout_contract}. Preserve each anchor's label and visual identity. "
        "For every boxed anchor, construct it with the exact `w=` and `h=` values in this contract. For an "
        "incoming anchor, use `self.place(anchor, \"cell\")` with its exact contract cell before self.add. "
        "For an outgoing anchor, finish the scene at its exact contract cell; if it moves, animate it to "
        "`self.cell(\"cell\")`. Do not resize a carryover anchor at the cut. Use a later "
        "Indicate/Transform/ReplacementTransform/move/highlight beat to extend the previous visual state."
    )


def continuity_issues(code: str, spec: SceneSpec) -> list[guardrails.Issue]:
    """Cheap source-level gate: a carryover cell must survive every generation/repair pass."""
    continuity = spec.continuity
    if not continuity or not continuity.anchor_layouts:
        return []
    issues: list[guardrails.Issue] = []
    for object_id, layout in continuity.anchor_layouts.items():
        cell = re.escape(layout.cell)
        placed = re.search(
            rf"self\.place\s*\(\s*{re.escape(object_id)}\s*,\s*['\"]{cell}['\"]", code
        )
        referenced = re.search(rf"self\.cell\s*\(\s*['\"]{cell}['\"]", code)
        if not placed and not referenced:
            issues.append(guardrails.Issue(
                "continuity-layout",
                f"anchor '{object_id}' must use its contracted grid cell '{layout.cell}'",
            ))
        for name, value in (("w", layout.width), ("h", layout.height)):
            if not re.search(rf"\b{name}\s*=\s*{re.escape(str(value))}\b", code):
                issues.append(guardrails.Issue(
                    "continuity-size",
                    f"anchor '{object_id}' must use its contracted {name}={value}",
                ))
    return issues


def generate(spec: SceneSpec, *, attempts: int = 3, client: LLMClient | None = None,
             style=None, structural: bool | None = None) -> str:
    client = client or get_client()
    use_structural = settings.structural_layout if structural is None else structural
    system = (lattice_scene.structural_system_prompt() if use_structural   # + icon catalog
              else load("manim-conventions") + "\n\n---\n\n" + load("codegen"))
    system += _pattern_prompt(spec)
    system += _continuity_prompt(spec)
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
        issues = guardrails.check(code, structural=use_structural) + continuity_issues(code, spec)
        if not issues:
            return _finalize(code, use_structural)
        last = issues
        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content": (
            "Fix these guardrail violations and resend the FULL file (code only):\n"
            + "\n".join(f"- {i.message}" for i in issues)
        )})
    raise CodegenError(f"guardrails not satisfied after {attempts} attempts: {[i.rule for i in last]}")


def generate_narrated(spec: SceneSpec, beats_audio: list[tuple[str, str, float]], *,
                      attempts: int = 3, client: LLMClient | None = None, style=None,
                      structural: bool | None = None) -> str:
    """SceneSpec + per-beat (narration, audio_path, duration) -> narrated Manim code (M4).

    Same guardrails as `generate`, plus it must wire the audio: the code must call
    `self.add_sound(...)` (else the scene would be silent), and is regenerated until it does.
    A `style` (M5) is injected so narrated multi-scene videos stay visually consistent too.
    """
    client = client or get_client()
    use_structural = settings.structural_layout if structural is None else structural
    system = (lattice_scene.structural_system_prompt(narrated=True) if use_structural   # + icon catalog
              else load("manim-conventions") + "\n\n---\n\n" + load("codegen-narrated"))
    system += _pattern_prompt(spec)
    system += _continuity_prompt(spec)
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
        issues = guardrails.check(code, structural=use_structural) + continuity_issues(code, spec)
        if "add_sound" not in code:
            issues = issues + [guardrails.Issue("no-audio", "must call self.add_sound(...) for each beat's audio")]
        if not issues:
            return _finalize(code, use_structural)
        last = issues
        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content": (
            "Fix these and resend the FULL file (code only):\n"
            + "\n".join(f"- {i.message}" for i in issues)
        )})
    raise CodegenError(f"narrated codegen failed after {attempts} attempts: {[i.rule for i in last]}")
