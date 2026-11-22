"""Phase-1 eval metrics: the process-wide token/cost accumulator (core/llm) and the new
BatteryReport aggregates / regression checks. All pure — no network/docker/model."""
import pytest

from core import llm
from eval.score import BatteryReport, PromptResult, compare


# --- token/cost accumulator (core/llm) -----------------------------------------------------

class _FakeUsage:
    def __init__(self, pt, ct):
        self.prompt_tokens = pt
        self.completion_tokens = ct


class _FakeResp:
    def __init__(self, pt, ct):
        self.usage = _FakeUsage(pt, ct)


@pytest.mark.unit
def test_estimate_cost_known_and_unknown():
    # gpt-4o-mini = (0.15, 0.60) per 1M
    c = llm.estimate_cost("openai/gpt-4o-mini", 1_000_000, 1_000_000)
    assert abs(c - (0.15 + 0.60)) < 1e-9
    assert llm.estimate_cost("some/unknown-model", 1_000_000, 1_000_000) == 0.0   # tokens still tracked


@pytest.mark.unit
def test_usage_accumulates_and_resets():
    llm.reset_usage()
    assert llm.usage_snapshot() == {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0, "cost_usd": 0.0}

    llm._record_usage("openai/gpt-4o-mini", _FakeResp(1000, 500))
    llm._record_usage("openai/gpt-4o-mini", _FakeResp(200, 100))
    snap = llm.usage_snapshot()
    assert snap["prompt_tokens"] == 1200 and snap["completion_tokens"] == 600 and snap["calls"] == 2
    assert snap["cost_usd"] > 0.0

    llm.reset_usage()
    assert llm.usage_snapshot()["calls"] == 0


@pytest.mark.unit
def test_record_usage_no_usage_field_is_noop():
    llm.reset_usage()
    llm._record_usage("openai/gpt-4o-mini", object())   # response with no .usage
    assert llm.usage_snapshot()["calls"] == 0


# --- BatteryReport aggregates --------------------------------------------------------------

@pytest.mark.unit
def test_first_try_and_off_frame_and_cost_aggregates():
    rep = BatteryReport([
        PromptResult("a", True, True, 90, 0, first_try_compiled=True, compile_attempts=1,
                     off_frame_issues=0, prompt_tokens=1000, completion_tokens=500, cost_usd=0.01),
        PromptResult("b", True, False, 60, 2, first_try_compiled=False, compile_attempts=3,
                     off_frame_issues=2, prompt_tokens=2000, completion_tokens=800, cost_usd=0.03),
        PromptResult("c", False, False, -1, 0, first_try_compiled=False, compile_attempts=4,
                     off_frame_issues=0, prompt_tokens=500, completion_tokens=100, cost_usd=0.005),
    ])
    assert abs(rep.first_try_rate - 1 / 3) < 1e-9
    assert abs(rep.off_frame_rate - 1 / 3) < 1e-9          # only "b" shipped an off-frame issue
    assert abs(rep.mean_repair_attempts - (1 + 3 + 4) / 3) < 1e-9
    assert rep.total_tokens == 1000 + 500 + 2000 + 800 + 500 + 100
    assert abs(rep.total_cost - 0.045) < 1e-9
    assert abs(rep.cost_per_video - 0.015) < 1e-9


@pytest.mark.unit
def test_old_baseline_json_still_loads():
    # a baseline saved BEFORE the new fields existed must still load (defaults fill in)
    old = {"results": [{"prompt": "a", "compiled": True, "ok": True, "score": 90, "n_issues": 0}]}
    rep = BatteryReport.from_dict(old)
    r = rep.results[0]
    assert r.prompt == "a" and r.first_try_compiled is False and r.cost_usd == 0.0


# --- regression on the new metrics ---------------------------------------------------------

@pytest.mark.unit
def test_compare_flags_first_try_drop():
    base = BatteryReport([PromptResult("a", True, True, 90, 0, first_try_compiled=True)])
    cur = BatteryReport([PromptResult("a", True, True, 90, 0, first_try_compiled=False)])
    reg = compare(cur, base)
    assert reg.is_regression and any("first-try" in r for r in reg.reasons)


@pytest.mark.unit
def test_compare_flags_off_frame_rise():
    base = BatteryReport([PromptResult("a", True, True, 90, 0, off_frame_issues=0)])
    cur = BatteryReport([PromptResult("a", True, True, 90, 0, off_frame_issues=3)])
    reg = compare(cur, base)
    assert reg.is_regression and any("off-frame" in r for r in reg.reasons)


@pytest.mark.unit
def test_compare_clean_when_metrics_hold():
    base = BatteryReport([PromptResult("a", True, True, 90, 0, first_try_compiled=True, off_frame_issues=0)])
    cur = BatteryReport([PromptResult("a", True, True, 92, 0, first_try_compiled=True, off_frame_issues=0)])
    assert compare(cur, base).is_regression is False
