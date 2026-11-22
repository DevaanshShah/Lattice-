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
    compiled: bool      # free, deterministic signal (compiled after repair)
    ok: bool            # critic passed (paid signal) — never conflated with `compiled`
    score: int          # critic score 0–100 (-1 if it never compiled)
    n_issues: int
    # --- extended metrics (defaults keep old baseline.json loadable) ---
    first_try_compiled: bool = False   # compiled on attempt 1 (before any repair)
    compile_attempts: int = 0          # render attempts used (1 = first try)
    off_frame_issues: int = 0          # RESIDUAL off-frame issues in the shipped scene
    overlap_issues: int = 0            # RESIDUAL overlap issues (populated once the overlap lint lands)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0


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

    @property
    def first_try_rate(self) -> float:
        """Fraction that compiled on the FIRST render (no repair needed)."""
        return (sum(r.first_try_compiled for r in self.results) / self.n) if self.n else 0.0

    @property
    def mean_repair_attempts(self) -> float:
        used = [r.compile_attempts for r in self.results if r.compile_attempts]
        return (sum(used) / len(used)) if used else 0.0

    @property
    def off_frame_rate(self) -> float:
        """Fraction of prompts that SHIPPED with >=1 residual off-frame issue."""
        return (sum(1 for r in self.results if r.off_frame_issues) / self.n) if self.n else 0.0

    @property
    def overlap_rate(self) -> float:
        return (sum(1 for r in self.results if r.overlap_issues) / self.n) if self.n else 0.0

    @property
    def total_tokens(self) -> int:
        return sum(r.prompt_tokens + r.completion_tokens for r in self.results)

    @property
    def total_cost(self) -> float:
        return sum(r.cost_usd for r in self.results)

    @property
    def cost_per_video(self) -> float:
        return (self.total_cost / self.n) if self.n else 0.0

    def table(self) -> str:
        lines = [f"{'compiled':>8} {'1st':>4} {'ok':>3} {'score':>5} {'iss':>4} {'off':>4} {'$':>7}  prompt",
                 "-" * 78]
        for r in self.results:
            lines.append(
                f"{('yes' if r.compiled else 'NO'):>8} {('y' if r.first_try_compiled else 'n'):>4} "
                f"{('y' if r.ok else 'n'):>3} {r.score:>5} {r.n_issues:>4} {r.off_frame_issues:>4} "
                f"{r.cost_usd:>7.4f}  {r.prompt[:40]}"
            )
        lines.append("-" * 78)
        lines.append(
            f"compile_rate={self.compile_rate:.0%}  first-try={self.first_try_rate:.0%}  "
            f"pass_rate={self.pass_rate:.0%}  mean_score={self.mean_score:.1f}  "
            f"off-frame={self.off_frame_rate:.0%}  overlap={self.overlap_rate:.0%}")
        lines.append(
            f"repairs/scene={self.mean_repair_attempts:.2f}  tokens={self.total_tokens:,}  "
            f"cost=${self.total_cost:.4f}  $/video=${self.cost_per_video:.4f}  (n={self.n})")
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
    d_first = current.first_try_rate - baseline.first_try_rate
    d_off = current.off_frame_rate - baseline.off_frame_rate

    if d_compile < -rate_tol:
        reasons.append(f"compile rate dropped {d_compile:+.0%}")
    if d_first < -rate_tol:
        reasons.append(f"first-try compile rate dropped {d_first:+.0%}")
    if d_score < -score_tol:
        reasons.append(f"mean score dropped {d_score:+.1f}")
    if d_off > rate_tol:
        reasons.append(f"off-frame rate rose {d_off:+.0%}")

    base = {r.prompt: r for r in baseline.results}
    for r in current.results:
        b = base.get(r.prompt)
        if b and b.compiled and not r.compiled:
            reasons.append(f"'{r.prompt[:30]}' no longer compiles")

    return Regression(bool(reasons), reasons, {
        "compile_rate": d_compile, "pass_rate": d_pass, "mean_score": d_score,
        "first_try_rate": d_first, "off_frame_rate": d_off,
    })
