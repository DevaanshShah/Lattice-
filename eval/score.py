"""Scoring + regression comparison for the eval battery.

Per prompt we record the two un-conflated signals (compiled? critic-ok?) plus the critic
score and issue count. A run is a REGRESSION vs a saved baseline if the compile rate drops,
the mean critic score drops beyond tolerance, or any prompt that used to compile no longer
does. Without this, prompt tweaks silently regress quality.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class PromptResult:
    prompt: str
    compiled: bool      # free, deterministic signal
    ok: bool            # critic passed (paid signal) — never conflated with `compiled`
    score: int          # critic score 0–100 (-1 if it never compiled)
    n_issues: int


@dataclass
class BatteryReport:
    results: list[PromptResult] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.results)

    @property
    def compile_rate(self) -> float:
        return (sum(r.compiled for r in self.results) / self.n) if self.n else 0.0

    @property
    def pass_rate(self) -> float:
        return (sum(r.ok for r in self.results) / self.n) if self.n else 0.0

    @property
    def mean_score(self) -> float:
        compiled = [r.score for r in self.results if r.compiled]
        return (sum(compiled) / len(compiled)) if compiled else 0.0

    def table(self) -> str:
        lines = [f"{'compiled':>8} {'ok':>3} {'score':>5} {'issues':>6}  prompt", "-" * 64]
        for r in self.results:
            lines.append(
                f"{('yes' if r.compiled else 'NO'):>8} {('y' if r.ok else 'n'):>3} "
                f"{r.score:>5} {r.n_issues:>6}  {r.prompt[:48]}"
            )
        lines.append("-" * 64)
        lines.append(f"compile_rate={self.compile_rate:.0%}  pass_rate={self.pass_rate:.0%}  "
                     f"mean_score={self.mean_score:.1f}  (n={self.n})")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {"results": [asdict(r) for r in self.results]}

    @classmethod
    def from_dict(cls, d: dict) -> "BatteryReport":
        return cls([PromptResult(**x) for x in d.get("results", [])])

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "BatteryReport":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


@dataclass
class Regression:
    is_regression: bool
    reasons: list[str]
    deltas: dict


def compare(current: BatteryReport, baseline: BatteryReport, *,
            score_tol: float = 5.0, rate_tol: float = 0.0) -> Regression:
    reasons: list[str] = []
    d_compile = current.compile_rate - baseline.compile_rate
    d_pass = current.pass_rate - baseline.pass_rate
    d_score = current.mean_score - baseline.mean_score

    if d_compile < -rate_tol:
        reasons.append(f"compile rate dropped {d_compile:+.0%}")
    if d_score < -score_tol:
        reasons.append(f"mean score dropped {d_score:+.1f}")

    base = {r.prompt: r for r in baseline.results}
    for r in current.results:
        b = base.get(r.prompt)
        if b and b.compiled and not r.compiled:
            reasons.append(f"'{r.prompt[:30]}' no longer compiles")

    return Regression(bool(reasons), reasons,
                      {"compile_rate": d_compile, "pass_rate": d_pass, "mean_score": d_score})
