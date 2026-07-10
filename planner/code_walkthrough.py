"""Code snippet -> a segment-by-segment walkthrough manifest (full code + one scene per line/block).

The walkthrough is rendered by the DETERMINISTIC scaffold (generation.code_scaffold): the whole snippet
stays on screen, the active line brightens, an arrow points to a short caption, and narration explains
it. So this planner's job is purely content: segment the code, and for each segment produce a title, a
short on-screen `caption`, and the spoken `narration`. Layout is not the model's concern (that is why it
is reliable on the cheap model).

`plan_walkthrough` returns the Walkthrough manifest (persisted as walkthrough.json and consumed by the
build). `plan` adapts it to an Outline for the existing approval gate (title + caption per scene).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

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
    code: str = ""                                   # literal source line(s); "" = the intro/overview scene
    title: str = Field(..., min_length=1)
    caption: str = Field(..., min_length=1)          # short on-screen right-panel text
    narration: str = Field(..., min_length=1)        # spoken explanation


class _Walkthrough(BaseModel):
    model_config = ConfigDict(extra="ignore")
    summary: str = Field(..., min_length=1)
    language: str | None = None
    segments: list[_Segment] = Field(..., min_length=1)


# --- manifest (persisted, consumed by the build) -------------------------------------------
@dataclass
class WScene:
    title: str
    active: list[int]        # indices into code_lines to highlight ([] = overview: whole code)
    caption: str
    narration: str


@dataclass
class Walkthrough:
    code_lines: list[str]
    language: str | None
    summary: str
    scenes: list[WScene] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Walkthrough":
        return cls(code_lines=list(d["code_lines"]), language=d.get("language"),
                   summary=d["summary"], scenes=[WScene(**s) for s in d["scenes"]])


def _map_active(code_lines: list[str], segments: list[_Segment]) -> list[list[int]]:
    """Map each segment's literal code to the line indices it highlights. Cursor-based so repeated
    lines (two `print(...)`) map in order; overview segments (code="") map to []."""
    stripped = [ln.strip() for ln in code_lines]
    cursor, out = 0, []
    for seg in segments:
        target = [ln.strip() for ln in seg.code.split("\n") if ln.strip()]
        if not target:
            out.append([]); continue
        found: list[int] = []
        for scan in (range(cursor, len(stripped)), range(0, len(stripped))):  # from cursor, else anywhere
            for start in scan:
                if stripped[start] != target[0]:
                    continue
                idxs, j, ok = [start], start + 1, True
                for t in target[1:]:
                    while j < len(stripped) and stripped[j] == "":
                        j += 1
                    if j < len(stripped) and stripped[j] == t:
                        idxs.append(j); j += 1
                    else:
                        ok = False; break
                if ok:
                    found = idxs; break
            if found:
                break
        out.append(found)
        if found:
            cursor = found[-1] + 1
    return out


def _request(code: str, language: str | None, *, client: LLMClient, attempts: int) -> _Walkthrough:
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
            wt.segments = wt.segments[:max_segments]   # documented cap, never a silent overrun
            return wt
        except (ValueError, ValidationError) as e:
            last = e
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": (
                f'That was invalid ({type(e).__name__}). Return ONLY JSON matching '
                '{"summary":...,"language":...,"segments":[{"code":...,"title":...,"caption":...,'
                '"narration":...}]} — no prose, no markdown.'
            )})
    raise CodeWalkthroughError(f"walkthrough invalid after {attempts} attempts: {last}")


def plan_walkthrough(code: str, language: str | None = None, *, client: LLMClient | None = None,
                     target_seconds: int | None = None, attempts: int = 3) -> Walkthrough:
    """Segment `code` into the walkthrough manifest (overview + one scene per line/block)."""
    code = (code or "").strip()
    if not code:
        raise CodeWalkthroughError("code snippet is empty")
    if len(code) > MAX_CODE_CHARS:
        raise CodeWalkthroughError(f"code too long ({len(code)} chars; max {MAX_CODE_CHARS})")

    client = client or get_client()
    wt = _request(code, language, client=client, attempts=attempts)
    code_lines = code.split("\n")
    active = _map_active(code_lines, wt.segments)
    scenes = [WScene(title=s.title, active=a, caption=s.caption, narration=s.narration)
              for s, a in zip(wt.segments, active)]
    return Walkthrough(code_lines=code_lines, language=wt.language or language,
                       summary=wt.summary, scenes=scenes)


def outline_of(wt: Walkthrough) -> Outline:
    """Adapt a manifest to an Outline for the approval gate (title + caption per scene)."""
    return Outline(topic=wt.summary,
                   items=[OutlineItem(title=s.title, intent=s.caption) for s in wt.scenes])


def plan(code: str, language: str | None = None, *, client: LLMClient | None = None,
         target_seconds: int | None = None, attempts: int = 3) -> Outline:
    """Back-compat: segment `code` and return just the Outline (approval view)."""
    return outline_of(plan_walkthrough(code, language, client=client,
                                       target_seconds=target_seconds, attempts=attempts))
