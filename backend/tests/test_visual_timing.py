import pytest

from core.schemas.browser_visual_plan import VisualAction, VisualBeat


def beat(windows):
    return VisualBeat.model_validate({
        "narration_beat_id": "b",
        "actions": [{"id": f"a{i}", "kind": "hold", "target_ids": ["x"], **window}
                    for i, window in enumerate(windows)],
        "evidence": [{"claim_ids": ["c"], "object_ids": ["x"], "kind": "label"}],
    })


@pytest.mark.unit
@pytest.mark.parametrize("window", [
    {"start_fraction": .2}, {"end_fraction": .4},
    {"start_fraction": .5, "end_fraction": .5},
    {"start_fraction": -.1, "end_fraction": .5},
    {"start_fraction": .1, "end_fraction": 1.1},
    {"start_fraction": float("nan"), "end_fraction": .5},
])
def test_invalid_cue_windows_rejected(window):
    with pytest.raises(ValueError):
        VisualAction(kind="hold", target_ids=["x"], **window)


@pytest.mark.unit
def test_mixed_or_overlapping_cues_rejected():
    with pytest.raises(ValueError, match="all actions"):
        beat([{"start_fraction": 0, "end_fraction": .5}, {}])
    with pytest.raises(ValueError, match="nonoverlapping"):
        beat([{"start_fraction": 0, "end_fraction": .6},
              {"start_fraction": .5, "end_fraction": .8}])


@pytest.mark.unit
def test_cues_resolve_against_measured_audio_and_preserve_gaps():
    planned = beat([{"start_fraction": .1, "end_fraction": .3},
                    {"start_fraction": .6, "end_fraction": .8}])
    assert planned.timeline(10) == [(1, 3), (6, 8)]
    assert planned.timeline(20) == [(2, 6), (12, 16)]


@pytest.mark.unit
def test_old_actions_keep_equal_duration_fallback():
    assert beat([{}, {}]).timeline(6) == [(0, 3), (3, 6)]


@pytest.mark.unit
@pytest.mark.parametrize("duration", [0, -1, float("nan"), float("inf")])
def test_bad_audio_duration_rejected(duration):
    with pytest.raises(ValueError, match="audio duration"):
        beat([{}]).timeline(duration)


@pytest.mark.unit
def test_visibility_normaliser_does_not_insert_untimed_actions():
    from planner.browser_visual_plan import _normalise_v2_visibility

    data = {"objects": [{"id": "x"}], "opening_visible_ids": [],
            "closing_visible_ids": ["x"], "beats": [{
                "narration_beat_id": "b", "actions": [{"kind": "hold", "target_ids": ["x"],
                    "start_fraction": .1, "end_fraction": .5}],
                "evidence": [{"object_ids": ["x"]}],
            }]}
    assert _normalise_v2_visibility(data)["beats"][0]["actions"] == data["beats"][0]["actions"]
    assert len(data["beats"][0]["actions"]) == 1
