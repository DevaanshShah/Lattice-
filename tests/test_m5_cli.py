"""M5 unit tests — generate-video approval gate parsing (T-12 gate via CLI). No network."""
import pytest

from core.schemas.outline import Outline

FIVE = Outline.model_validate({"topic": "t", "items": [
    {"title": f"S{i}", "intent": "x"} for i in range(5)]})


@pytest.mark.unit
def test_auto_approver_caps_scenes():
    from scripts.generate_video import _make_approver
    out = _make_approver(auto=True, max_scenes=3)(FIVE)
    assert len(out.items) == 3 and out.titles() == ["S0", "S1", "S2"]


@pytest.mark.unit
def test_auto_approver_no_cap_keeps_all():
    from scripts.generate_video import _make_approver
    assert len(_make_approver(auto=True)(FIVE).items) == 5


@pytest.mark.unit
def test_interactive_keep_reorders(monkeypatch):
    from scripts.generate_video import _make_approver
    monkeypatch.setattr("builtins.input", lambda *a: "keep 4 0")
    out = _make_approver(auto=False)(FIVE)
    assert out.titles() == ["S4", "S0"]


@pytest.mark.unit
def test_interactive_abort_raises(monkeypatch):
    from scripts.generate_video import _make_approver
    monkeypatch.setattr("builtins.input", lambda *a: "q")
    with pytest.raises(SystemExit):
        _make_approver(auto=False)(FIVE)
