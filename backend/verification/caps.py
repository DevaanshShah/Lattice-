"""FR-7 — the hard caps that guarantee no loop ever hangs.

One place to read the limits from so compile-repair, the vision critic, and best-of-N all
agree. Defaults come from `core/config` (env-overridable) but a caller can pass a tighter
`Caps` for a single run (tests do exactly this to prove graceful failure quickly).
"""
from __future__ import annotations

from dataclasses import dataclass

from core.config import settings


@dataclass(frozen=True)
class Caps:
    max_repair_attempts: int = settings.max_repair_attempts  # renders per compile-repair loop
    max_critic_iters: int = settings.max_critic_iters        # critic→fix rounds per scene
    best_of_n: int = settings.best_of_n                      # candidates when falling back

    def __post_init__(self) -> None:
        # A cap of 0 would mean "never even try"; clamp so the loops always run at least once.
        for name in ("max_repair_attempts", "max_critic_iters", "best_of_n"):
            if getattr(self, name) < 1:
                object.__setattr__(self, name, 1)
