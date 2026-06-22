"""FR-6 fallback — best-of-N. When the critic loop can't converge on one candidate, widen
the search instead of looping deeper: generate N independent candidates, run each through the
full verify pipeline (compile-repair → vision critic), and keep the highest-scoring one.

`generate_fn` / `evaluate_fn` are injectable so this is unit-testable with no Docker/model.
Ranking prefers candidates that COMPILED (the free signal) and, among those, the higher vision
score — the two signals stay separate, never conflated into one number.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from verification.caps import Caps
from verification.vision_critic import CritiqueResult

GenerateFn = Callable[[int], str]                 # index -> candidate code
EvaluateFn = Callable[[str, int], CritiqueResult]  # (code, index) -> verified result


@dataclass
class Candidate:
    index: int
    code: str
    result: CritiqueResult | None = None

    @property
    def compiled(self) -> bool:
        return bool(self.result and self.result.compiled)

    @property
    def score(self) -> int:
        return self.result.score() if self.result else -1

    @property
    def rank_key(self) -> tuple[int, int]:
        # compiled candidates always beat non-compiling ones; then higher vision score wins
        return (1 if self.compiled else 0, self.score)


@dataclass
class BestResult:
    best: Candidate | None
    candidates: list[Candidate] = field(default_factory=list)


def run(generate_fn: GenerateFn, evaluate_fn: EvaluateFn, *, n: int | None = None,
        caps: Caps | None = None, log: Callable[[str], None] | None = None) -> BestResult:
    caps = caps or Caps()
    n = caps.best_of_n if n is None else max(1, n)
    say = log or (lambda _m: None)

    candidates: list[Candidate] = []
    for i in range(n):
        say(f"[best-of-{n}] candidate {i + 1}/{n}: generating + verifying")
        code = generate_fn(i)
        result = evaluate_fn(code, i)
        cand = Candidate(i, code, result)
        say(f"[best-of-{n}] candidate {i + 1}: compiled={cand.compiled} score={cand.score}")
        candidates.append(cand)

    best = max(candidates, key=lambda c: c.rank_key, default=None)
    if best is not None:
        say(f"[best-of-{n}] kept candidate {best.index + 1} (compiled={best.compiled} score={best.score})")
    return BestResult(best, candidates)
