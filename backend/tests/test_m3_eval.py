"""M3 unit tests — eval scoring + regression compare (T-7). No network/docker.

The live battery run needs a key + Docker; here we assert the scoring/regression LOGIC that
makes the harness trustworthy, on synthetic results.
"""
import pytest

from eval.score import BatteryReport, PromptResult, compare


def mk(*rows) -> BatteryReport:
    return BatteryReport([PromptResult(*r) for r in rows])


@pytest.mark.unit
def test_rates_and_mean_score_over_compiled_only():
    rep = mk(("a", True, True, 90, 0), ("b", True, False, 60, 2), ("c", False, False, -1, 0))
    assert abs(rep.compile_rate - 2 / 3) < 1e-9
    assert abs(rep.pass_rate - 1 / 3) < 1e-9
    assert rep.mean_score == 75.0      # mean of compiled scores (90, 60); the failed one is excluded


@pytest.mark.unit
def test_table_renders_prompt_and_summary():
    t = mk(("explain X", True, True, 90, 0)).table()
    assert "explain X" in t and "compile_rate" in t and "mean_score" in t


@pytest.mark.unit
def test_save_load_roundtrip(tmp_path):
    rep = mk(("a", True, True, 90, 0))
    p = tmp_path / "r.json"
    rep.save(p)
    rep2 = BatteryReport.load(p)
    assert rep2.results[0].prompt == "a" and rep2.mean_score == 90


@pytest.mark.unit
def test_compare_flags_score_drop():
    base = mk(("a", True, True, 90, 0), ("b", True, True, 90, 0))   # mean 90
    cur = mk(("a", True, True, 90, 0), ("b", True, False, 50, 2))   # mean 70
    reg = compare(cur, base, score_tol=5)
    assert reg.is_regression and any("score" in r for r in reg.reasons)


@pytest.mark.unit
def test_compare_flags_lost_compile():
    base = mk(("a", True, True, 90, 0))
    cur = mk(("a", False, False, -1, 0))
    reg = compare(cur, base)
    assert reg.is_regression and any("compile" in r.lower() for r in reg.reasons)


@pytest.mark.unit
def test_compare_no_regression_when_improved():
    base = mk(("a", True, True, 70, 1))
    cur = mk(("a", True, True, 95, 0))
    assert compare(cur, base, score_tol=5).is_regression is False


@pytest.mark.unit
def test_battery_has_at_least_10_prompts():
    from eval.battery import BATTERY
    assert len(BATTERY) >= 10 and len(set(BATTERY)) == len(BATTERY)   # no dupes
