"""Scores for the learning-video PLANNING battery (lesson + visual plan, nothing rendered).

Sibling of eval/score.py, which scores the Manim code path. Planning is where the learning-video
path spends its model calls and where it fails, so this is the number to watch when a prompt, a
validator rule or the model changes: did a topic plan at all, and how many scenes passed the
validator on the first try.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class SceneResult:
    scene_id: str
    accepted: bool
    tries: int


@dataclass
class TopicResult:
    topic: str
    lesson_ok: bool = False
    lesson_tries: int = 0
    lesson_words: int = 0
    planned: bool = False               # every scene accepted and the whole plan validated
    scenes: list[SceneResult] = field(default_factory=list)
    rejections: list[str] = field(default_factory=list)   # validator reasons sent back to the model
    error: str = ""
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class PlanBatteryReport:
    model: str
    results: list[TopicResult] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.results)

    @property
    def plan_rate(self) -> float:
        return sum(r.planned for r in self.results) / self.n if self.n else 0.0

    @property
    def scenes_tried(self) -> int:
        return sum(len(r.scenes) for r in self.results)

    @property
    def first_try_rate(self) -> float:
        """Share of attempted scenes the validator accepted on the model's first answer."""
        first = sum(s.accepted and s.tries == 1 for r in self.results for s in r.scenes)
        return first / self.scenes_tried if self.scenes_tried else 0.0

    @property
    def mean_tries(self) -> float:
        tries = [s.tries for r in self.results for s in r.scenes]
        return sum(tries) / len(tries) if tries else 0.0

    @property
    def total_cost(self) -> float:
        return sum(r.cost_usd for r in self.results)

    @property
    def total_calls(self) -> int:
        return sum(r.calls for r in self.results)

    def table(self) -> str:
        rows = ["| topic | lesson | words | scenes ok | first try | calls | cost | note |",
                "|---|---|---|---|---|---|---|---|"]
        for r in self.results:
            ok = sum(s.accepted for s in r.scenes)
            first = sum(s.accepted and s.tries == 1 for s in r.scenes)
            total = len(r.scenes)
            rows.append(
                f"| {r.topic[:44]} | {'ok' if r.lesson_ok else 'FAIL'} | {r.lesson_words} | "
                f"{ok}/{total}{'' if r.planned else ' (not planned)'} | {first}/{total} | {r.calls} | "
                f"${r.cost_usd:.4f} | {r.error[:70]} |")
        rows.append(
            f"\n{self.model}: planned {sum(r.planned for r in self.results)}/{self.n} "
            f"({self.plan_rate:.0%}) · first-try scenes {self.first_try_rate:.0%} · "
            f"mean tries {self.mean_tries:.2f} · {self.total_calls} calls · ${self.total_cost:.4f}")
        return "\n".join(rows)

    def to_dict(self) -> dict:
        return {"model": self.model, "results": [asdict(r) for r in self.results]}

    @classmethod
    def from_dict(cls, data: dict) -> "PlanBatteryReport":
        results = []
        for row in data.get("results", []):
            scenes = [SceneResult(**scene) for scene in row.get("scenes", [])]
            results.append(TopicResult(**{**row, "scenes": scenes}))
        return cls(model=data.get("model", ""), results=results)


def compare(current: PlanBatteryReport, baseline: PlanBatteryReport, *,
            rate_tol: float = 0.0) -> list[str]:
    """Reasons the current run is WORSE than the baseline (empty = no regression).

    With three topics one flaky answer moves a rate by a third, so read a single drop as a prompt
    to re-run with --repeat, not as proof.
    """
    reasons: list[str] = []
    d_plan = current.plan_rate - baseline.plan_rate
    d_first = current.first_try_rate - baseline.first_try_rate
    if d_plan < -rate_tol:
        reasons.append(f"plan rate dropped {d_plan:+.0%}")
    if d_first < -rate_tol:
        reasons.append(f"first-try scene rate dropped {d_first:+.0%}")
    planned_before = {r.topic for r in baseline.results if r.planned}
    planned_now = {r.topic for r in current.results if r.planned}
    ran_now = {r.topic for r in current.results}
    for topic in sorted((planned_before & ran_now) - planned_now):
        reasons.append(f"'{topic[:40]}' no longer plans")
    return reasons
