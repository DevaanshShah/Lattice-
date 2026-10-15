"""Offline coverage for Jev's optional, fail-safe recipe routing."""
from __future__ import annotations

import json

import pytest

from planner import jev_router, product_recipe


class _Response:
    def __init__(self, body: dict):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return json.dumps(self.body).encode("utf-8")


@pytest.mark.unit
def test_jev_route_sends_existing_choices_and_parses_a_typed_answer():
    seen = {}

    def open_url(request, timeout):
        seen["body"] = json.loads(request.data.decode("utf-8"))
        seen["timeout"] = timeout
        return _Response({"answers": {"recipe": {"choice": "algorithm_explainer", "confidence": .91}}})

    decision = jev_router.route("Explain binary search", {"algorithm_explainer": "trace board"},
                                api_key="test", base_url="https://example.test/jev",
                                model="jev-1.13.0", timeout=3, open_url=open_url)
    assert decision == jev_router.RouteDecision("algorithm_explainer", .91)
    assert seen["body"]["questions"]["recipe"]["criteria"]["unsupported"]
    assert seen["timeout"] == 3


@pytest.mark.unit
def test_jev_route_rejects_unknown_or_malformed_answers():
    def open_url(request, timeout):
        return _Response({"answers": {"recipe": {"choice": "invented_board", "confidence": .9}}})

    assert jev_router.route("x", {"trace": "trace"}, api_key="test", base_url="https://example.test",
                            model="jev-1.13.0", timeout=1, open_url=open_url) is None

    def malformed_choice(request, timeout):
        return _Response({"answers": {"recipe": {"choice": ["trace"], "confidence": .9}}})

    assert jev_router.route("x", {"trace": "trace"}, api_key="test", base_url="https://example.test",
                            model="jev-1.13.0", timeout=1, open_url=malformed_choice) is None


@pytest.mark.unit
def test_high_confidence_jev_route_overrides_keyword_route(monkeypatch):
    monkeypatch.setattr(product_recipe.settings, "jev_enabled", True)
    monkeypatch.setattr(product_recipe.settings, "jev_api_key", "test")
    monkeypatch.setattr(product_recipe.settings, "jev_min_confidence", .8)
    monkeypatch.setattr(product_recipe, "jev_route", lambda *args, **kwargs:
                        jev_router.RouteDecision("metric_story", .9))
    recipe = product_recipe.pick_recipe("Explain binary search", "auto")
    assert recipe.id == "metric_story"


@pytest.mark.unit
def test_uncertain_or_unsupported_jev_route_keeps_keyword_fallback(monkeypatch):
    monkeypatch.setattr(product_recipe.settings, "jev_enabled", True)
    monkeypatch.setattr(product_recipe.settings, "jev_api_key", "test")
    monkeypatch.setattr(product_recipe.settings, "jev_min_confidence", .8)
    monkeypatch.setattr(product_recipe, "jev_route", lambda *args, **kwargs:
                        jev_router.RouteDecision(jev_router.UNSUPPORTED, .99))
    recipe = product_recipe.pick_recipe("Explain binary search", "auto")
    assert recipe.id == "algorithm_explainer"


@pytest.mark.unit
def test_low_confidence_jev_route_keeps_keyword_fallback(monkeypatch):
    monkeypatch.setattr(product_recipe.settings, "jev_enabled", True)
    monkeypatch.setattr(product_recipe.settings, "jev_api_key", "test")
    monkeypatch.setattr(product_recipe.settings, "jev_min_confidence", .8)
    monkeypatch.setattr(product_recipe, "jev_route", lambda *args, **kwargs:
                        jev_router.RouteDecision("metric_story", .79))
    recipe = product_recipe.pick_recipe("Explain binary search", "auto")
    assert recipe.id == "algorithm_explainer"


@pytest.mark.unit
def test_explicit_recipe_never_calls_jev(monkeypatch):
    monkeypatch.setattr(product_recipe.settings, "jev_enabled", True)
    monkeypatch.setattr(product_recipe.settings, "jev_api_key", "test")
    monkeypatch.setattr(product_recipe, "jev_route", lambda *args, **kwargs:
                        pytest.fail("an explicit recipe must stay offline"))
    recipe = product_recipe.pick_recipe("Explain binary search", "architecture_explainer")
    assert recipe.id == "architecture_explainer"
