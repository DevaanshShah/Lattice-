"""FR-14 — bounded parallel scene building.

Scenes are independent, so build them concurrently — but through a worker pool with a hard
concurrency cap (not unbounded), to avoid model rate-limits and simultaneous cost/CPU spikes.
A scene that fails (after its own repair/critic caps) is captured as a failed TaskResult and
does NOT abort the others. Results come back in the ORIGINAL item order.

Threads are the right tool: the heavy work is Docker subprocesses + LLM HTTP calls (I/O bound),
which release the GIL.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Callable

from core.config import settings


@dataclass
class TaskResult:
    index: int
    ok: bool
    value: Any = None
    error: str | None = None


def run_bounded(items: list, work_fn: Callable[[Any, int], Any], *,
                cap: int | None = None) -> list[TaskResult]:
    """Run work_fn(item, index) over items, <=cap at a time. Never raises; failures captured."""
    cap = cap or settings.concurrency_cap
    results: list[TaskResult | None] = [None] * len(items)
    if not items:
        return []
    with ThreadPoolExecutor(max_workers=max(1, cap)) as ex:
        futures = {ex.submit(work_fn, item, i): i for i, item in enumerate(items)}
        for fut in as_completed(futures):
            i = futures[fut]
            try:
                results[i] = TaskResult(i, True, fut.result())
            except Exception as e:  # one scene's failure must not abort the others
                results[i] = TaskResult(i, False, None, f"{type(e).__name__}: {e}")
    return results  # type: ignore[return-value]  # every slot is filled above
