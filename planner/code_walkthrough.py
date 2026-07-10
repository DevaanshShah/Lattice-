"""Code snippet -> a segment-by-segment walkthrough Outline (one scene per line/block).

Unlike planner.outline (topic string -> generic outline), this segments a code snippet into an
ordered teaching sequence and builds the Outline DIRECTLY — each OutlineItem's intent instructs the
downstream scene generator to render one literal code line as a single Text and teach it. The Outline
schema is reused unchanged (intents are just strings), so expand/scene_spec/decoupled are untouched.

The rendered-line contract matches generation.lattice_scene: ONE LINE = ONE Text (with t2c token
colors / a brace), NEVER Code() (which renders as an invisible dark-on-dark box).
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core.config import settings
from core.llm import LLMClient, get_client
from core.schemas.outline import Outline, OutlineItem
from core.textutil import extract_json
from prompts.loader import load

MAX_CODE_CHARS = 20_000


class CodeWalkthroughError(RuntimeError):
    pass


# --- model output shape (tolerant of drift; extras ignored) --------------------------------
class _Segment(BaseModel):
    model_config = ConfigDict(extra="ignore")
    code: str = ""                                   # literal line(s); "" = the overview scene
    title: str = Field(..., min_length=1)
    teach: str = Field(..., min_length=1)
    highlight: list[str] = Field(default_factory=list)


class _Walkthrough(BaseModel):
    model_config = ConfigDict(extra="ignore")
    summary: str = Field(..., min_length=1)
    language: str | None = None
    segments: list[_Segment] = Field(..., min_length=1)


def _intent_for(seg: _Segment, language: str | None) -> str:
    """Compose an OutlineItem.intent that drives one walkthrough scene through expand/scene_spec.

    The layout rules are deliberately strict: the Phase 0 prototype showed freeform annotation
    (multiple arrows crossing the text, highlight rectangles splitting words) is the main defect,
    while code-as-Text itself renders fine. So we pin down HOW a line may be emphasised / pointed at.
    """
    if not seg.code.strip():
        # opening overview: explain the whole snippet with a diagram, do NOT dump the code
        return (f"{seg.teach} This is the opening overview scene: explain what the whole snippet does "
                f"using a simple labelled diagram (boxes / arrows / a number line); do NOT show the "
                f"full code listing or any source line.")
    lang = f"{language} " if language else ""
    hi = ", ".join(f"`{h}`" for h in seg.highlight if h.strip())
    hi_clause = (f"Emphasise the token(s) {hi} by COLORING those characters via Text(..., t2c=...). "
                 if hi else "Color the one or two most important tokens via t2c. ")
    return (f"Teach this {lang}code line: `{seg.code}`. {seg.teach}\n"
            f"Layout (follow exactly): render the line as ONE large centered monospace Text "
            f"(never Code()), with generous empty space around it. {hi_clause}"
            f"Do NOT draw any rectangle, box, or underline around the text or any substring, and do "
            f"NOT split the line into separate pieces. If you point at part of the line, use at most "
            f"ONE short brace or arrow placed clearly BELOW the line with a visible gap; it must not "
            f"touch, cross, or overlap any character. Keep the scene to this one line's idea.")


def plan(code: str, language: str | None = None, *, client: LLMClient | None = None,
         target_seconds: int | None = None, attempts: int = 3) -> Outline:
    """Segment `code` into a walkthrough Outline (overview + one scene per line/block).

    target_seconds is accepted for API parity with Engine.plan; segment count is code-driven and
    clamped to settings.scene_cap (the model is also told the maximum).
    """
    code = (code or "").strip()
    if not code:
        raise CodeWalkthroughError("code snippet is empty")
    if len(code) > MAX_CODE_CHARS:
        raise CodeWalkthroughError(f"code too long ({len(code)} chars; max {MAX_CODE_CHARS})")

    client = client or get_client()
    max_segments = settings.scene_cap
    hint = f"Language hint: {language}\n" if language else ""
    messages = [
        {"role": "system", "content": load("code-walkthrough")},
        {"role": "user", "content": (f"{hint}Maximum segments: {max_segments}\n\n"
                                     f"Code:\n```\n{code}\n```\n\nReturn the walkthrough JSON now.")},
    ]
    last: Exception | None = None
    for _ in range(attempts):
        raw = client.chat(messages)
        try:
            wt = _Walkthrough.model_validate(extract_json(raw))
            segments = wt.segments[:max_segments]  # documented cap, never a silent overrun
            items = [OutlineItem(title=s.title, intent=_intent_for(s, wt.language or language))
                     for s in segments]
            return Outline(topic=wt.summary, items=items)
        except (ValueError, ValidationError) as e:
            last = e
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": (
                f'That was invalid ({type(e).__name__}). Return ONLY JSON matching '
                '{"summary":...,"language":...,"segments":[{"code":...,"title":...,"teach":...,'
                '"highlight":[...]}]} — no prose, no markdown.'
            )})
    raise CodeWalkthroughError(f"walkthrough invalid after {attempts} attempts: {last}")
