"""FR-3 (the gate) — edit the outline BEFORE generating. Approve structure before spending.

`apply_edits` is the pure core (reorder/cut via a `keep` index list, or `drop` indices). The
interactive prompt lives in the CLI; this stays testable and side-effect-free.
"""
from __future__ import annotations

from core.schemas.outline import Outline


def apply_edits(outline: Outline, *, keep: list[int] | None = None,
                drop: list[int] | None = None) -> Outline:
    """Return a new Outline after edits.

    - `keep`: indices (of the original items) to keep, IN THE NEW ORDER — covers reorder + cut.
    - `drop`: indices to remove (ignored if `keep` is given).
    """
    items = list(outline.items)
    if keep is not None:
        items = [items[i] for i in keep]
    elif drop:
        dropped = set(drop)
        items = [it for i, it in enumerate(items) if i not in dropped]
    if not items:
        raise ValueError("outline cannot be empty after edits")
    return Outline(topic=outline.topic, items=items)


def render_for_review(outline: Outline) -> str:
    """A plain-text view of the outline for the approval prompt."""
    lines = [f"Outline for: {outline.topic}  ({len(outline.items)} scenes)"]
    for i, it in enumerate(outline.items):
        lines.append(f"  {i}. {it.title} — {it.intent}")
    return "\n".join(lines)
