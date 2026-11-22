"""FR-12 — captions. Build an SRT subtitle track from the narration lines + their durations."""
from __future__ import annotations


def _ts(t: float) -> str:
    if t < 0:
        t = 0.0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int(round((t - int(t)) * 1000))
    if ms == 1000:  # rounding spillover
        s += 1
        ms = 0
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(lines: list[str], durations: list[float]) -> str:
    """SRT with cumulative timing: line i spans [sum(d[:i]), sum(d[:i+1]))."""
    blocks: list[str] = []
    t = 0.0
    for i, (line, dur) in enumerate(zip(lines, durations), start=1):
        start, end = t, t + dur
        blocks.append(f"{i}\n{_ts(start)} --> {_ts(end)}\n{line}\n")
        t = end
    return "\n".join(blocks)
