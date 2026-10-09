import json

import pytest

from eval.plan_score import PlanBatteryReport, SceneResult, TopicResult, compare
from scripts.plan_battery import run_battery
from scripts.video_regression import cases


class Replay:
    """Stands in for the model: returns queued answers in order."""
    model = "replay"

    def __init__(self, outputs):
        self.outputs = list(outputs)

    def chat(self, messages, **kwargs):
        return self.outputs.pop(0)


def _tool_flow():
    folder = cases()["tool_flow"]
    lesson = json.loads((folder / "lesson_plan.json").read_text(encoding="utf-8"))
    plan = json.loads((folder / "browser_visual_plan.json").read_text(encoding="utf-8"))
    return lesson["topic"], json.dumps(lesson), [json.dumps(scene) for scene in plan["scenes"]]


@pytest.mark.unit
def test_battery_scores_a_topic_that_plans_on_the_first_try(tmp_path):
    topic, lesson, scenes = _tool_flow()
    report = run_battery([topic], Replay([lesson, *scenes]), model="replay", out_dir=tmp_path,
                         max_calls=10, log=lambda _m: None)
    result = report.results[0]
    assert result.lesson_ok and result.planned and result.calls == 4
    assert [(scene.accepted, scene.tries) for scene in result.scenes] == [(True, 1)] * 3
    assert result.lesson_words > 30 and result.rejections == []
    assert report.plan_rate == 1.0 and report.first_try_rate == 1.0
    assert (tmp_path / "00_explain_an_agent_harness_to_a_beginner_u" / "browser_visual_plan.json").exists()


@pytest.mark.unit
def test_battery_counts_a_retry_and_keeps_the_validator_reason(tmp_path):
    topic, lesson, scenes = _tool_flow()
    faked = json.loads(scenes[0])
    for action in faked["beats"][0]["actions"]:
        if action["kind"] == "set_state":      # a glow in place of the real state change
            action["kind"], action["params"] = "highlight", {}
    report = run_battery([topic], Replay([lesson, json.dumps(faked), *scenes]), model="replay",
                         out_dir=tmp_path, max_calls=10, log=lambda _m: None)
    result = report.results[0]
    assert result.planned and result.scenes[0].tries == 2
    assert report.first_try_rate == pytest.approx(2 / 3)
    assert len(result.rejections) == 1 and "lacks sequence visual proof" in result.rejections[0]


@pytest.mark.unit
def test_battery_stops_at_the_call_cap_without_scoring_the_cut_topic(tmp_path):
    topic, lesson, scenes = _tool_flow()
    client = Replay([lesson, *scenes])
    lines = []
    report = run_battery([topic, topic], client, model="replay", out_dir=tmp_path, max_calls=2,
                         log=lines.append)
    assert report.results == [] and len(client.outputs) == 2      # exactly two answers were consumed
    assert any("call cap of 2 reached" in line for line in lines)


@pytest.mark.unit
def test_compare_reports_a_topic_that_stopped_planning():
    scenes = [SceneResult("s1", True, 1), SceneResult("s2", True, 2)]
    baseline = PlanBatteryReport("m", [TopicResult("binary search", lesson_ok=True, planned=True,
                                                   scenes=scenes)])
    current = PlanBatteryReport("m", [TopicResult("binary search", lesson_ok=True, planned=False,
                                                  scenes=[SceneResult("s1", False, 3)])])
    reasons = compare(current, baseline)
    assert "plan rate dropped -100%" in reasons
    assert "first-try scene rate dropped -50%" in reasons
    assert "'binary search' no longer plans" in reasons
    assert compare(baseline, baseline) == []


@pytest.mark.unit
def test_report_round_trips_through_json():
    report = PlanBatteryReport("m", [TopicResult("t", lesson_ok=True, planned=True, calls=4,
                                                 cost_usd=0.01, rejections=["why"],
                                                 scenes=[SceneResult("s1", True, 1)])])
    again = PlanBatteryReport.from_dict(json.loads(json.dumps(report.to_dict())))
    assert again == report
    assert "planned 1/1 (100%)" in again.table()
