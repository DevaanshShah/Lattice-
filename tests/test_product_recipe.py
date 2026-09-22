"""Unit tests for deterministic recipe selection and browser-deck routing."""
import pytest

from planner import product_recipe


@pytest.mark.unit
def test_all_five_recipes_load_and_validate():
    recipes = product_recipe.load_recipes()
    expected_ids = {"architecture_explainer", "workflow_explainer", "funnel_explainer",
                    "metric_story", "before_after"}
    assert set(recipes) == expected_ids
    for recipe in recipes.values():
        assert recipe.keywords and recipe.outline_guidance and recipe.scene_guidance
        assert recipe.visual_pattern


@pytest.mark.unit
def test_direct_selection_ignores_keywords():
    # a topic full of funnel language, but a specific id always wins outright
    recipe = product_recipe.pick_recipe("our conversion funnel from leads to closed deals",
                                        "metric_story")
    assert recipe.id == "metric_story"


@pytest.mark.unit
def test_unknown_specific_id_raises():
    with pytest.raises(ValueError):
        product_recipe.pick_recipe("anything", "not_a_real_recipe")


@pytest.mark.unit
def test_auto_keyword_selection_picks_funnel():
    recipe = product_recipe.pick_recipe(
        "Show our conversion funnel: leads to MQL to SQL to closed deals", "auto")
    assert recipe.id == "funnel_explainer"


@pytest.mark.unit
def test_auto_keyword_selection_picks_architecture():
    recipe = product_recipe.pick_recipe(
        "Explain how Revenue Brain connects CRM, marketing, billing, and support data", "auto")
    assert recipe.id == "architecture_explainer"


@pytest.mark.unit
def test_auto_falls_back_to_workflow_explainer_on_no_keyword_match():
    recipe = product_recipe.pick_recipe("xyzzy plugh quux", "auto")
    assert recipe.id == product_recipe.FALLBACK_ID == "workflow_explainer"


@pytest.mark.unit
def test_deck_planner_passes_recipe_guidance_to_the_llm():
    from planner.slide_plan import plan_deck

    class Client:
        def __init__(self):
            self.messages = []

        def chat(self, messages):
            self.messages = messages
            return ('{"title":"Flow","slides":[{"kind":"title","title":"Flow",'
                    '"beats":[{"say":"A concrete fact.","focus":-1}]}]}')

    client = Client()
    plan_deck("Explain a funnel", client=client,
              recipe_guidance="Required visual pattern: funnel.")
    assert "PRODUCT VIDEO SHAPE" in client.messages[-1]["content"]
    assert "Required visual pattern: funnel." in client.messages[-1]["content"]


# --- threading through composition/video.py -------------------------------------------------

@pytest.mark.unit
def test_generate_video_without_recipe_never_calls_pick_recipe(monkeypatch, tmp_path):
    from composition import video
    from core.schemas.outline import Outline
    from core.schemas.style import StyleSpec

    called = {"pick_recipe": False}
    monkeypatch.setattr(video.product_recipe, "pick_recipe",
                        lambda *a, **k: called.__setitem__("pick_recipe", True))
    monkeypatch.setattr(video.planner_outline, "generate",
                        lambda topic, **k: (
                            (_ for _ in ()).throw(AssertionError("recipe_guidance must not be passed"))
                            if "recipe_guidance" in k else
                            Outline.model_validate({"topic": topic, "items": [{"title": "A", "intent": "x"}]})
                        ))
    monkeypatch.setattr(video.style_gen, "generate", lambda topic, outline, **k: StyleSpec())
    monkeypatch.setattr(video, "build_scene",
                        lambda node, project, *, scenes_dir, quality, client, log: node)
    monkeypatch.setattr(video.stitch, "stitch", lambda mp4s, **k: tmp_path / "final.mp4")

    video.generate_video("TCP", out_dir=tmp_path, client=object(), log=None)  # no recipe kwarg at all
    assert called["pick_recipe"] is False


@pytest.mark.unit
def test_generate_video_with_recipe_auto_sends_guidance_to_deck_planner(monkeypatch, tmp_path):
    from composition import video
    from generation.slide_deck import Slide
    from planner.slide_plan import Deck

    seen = {}
    monkeypatch.setattr(video.slide_plan, "plan_deck", lambda topic, **k: (
        seen.update(topic=topic, guidance=k.get("recipe_guidance")),
        Deck(title="Funnel", slides=[Slide(kind="title", title="Funnel", beats=[{"say": "Start", "focus": -1}])])
    )[1])
    final = tmp_path / "deck.mp4"
    final.write_bytes(b"v")
    monkeypatch.setattr(video.slides, "build_deck", lambda deck, out, **k: (
        seen.update(deck=deck, out=out, build=k), final)[1])
    monkeypatch.setattr(video.planner_outline, "generate",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("Manim planner used")))

    project = video.generate_video("Show our conversion funnel: leads to MQL to SQL", out_dir=tmp_path,
                                   client=object(), log=None, recipe="auto")
    assert seen["topic"].startswith("Show our conversion funnel")
    assert "funnel" in seen["guidance"].lower()
    assert len(seen["deck"]) == 1
    assert seen["build"]["math_quality"] == "preview"
    assert project.final_mp4 == str(final)


@pytest.mark.unit
def test_recipe_preplans_scene_handoffs_before_parallel_render(monkeypatch, tmp_path):
    from composition import video
    from composition.scene_dag import VideoProject
    from core.schemas.outline import Outline
    from core.schemas.scene_spec import SceneSpec

    project = VideoProject.from_outline(Outline.model_validate({"topic": "T", "items": [
        {"title": "Silos", "intent": "show source"},
        {"title": "Connection", "intent": "connect source"},
    ]}))
    first = SceneSpec.model_validate({
        "title": "Silos", "prompt": "p", "narration": "n",
        "objects": [{"id": "source", "kind": "rectangle", "label": "CRM"}],
        "beats": [{"action": "create", "targets": ["source"]}],
    })
    second = SceneSpec.model_validate({
        "title": "Connection", "prompt": "p", "narration": "n",
            "continuity": {"carryover_ids": ["source"], "opening_state": "CRM remains visible",
                           "closing_state": "CRM connects to Revenue Brain",
                           "anchor_layouts": {"source": {"cell": "C2", "width": 2.0, "height": 1.0}}},
        "objects": [
            {"id": "source", "kind": "rectangle", "label": "CRM"},
            {"id": "brain", "kind": "rectangle", "label": "Revenue Brain"},
        ],
        "beats": [
            {"action": "indicate", "targets": ["source"]},
            {"action": "fade_in", "targets": ["brain"]},
        ],
    })
    seen = []

    def fake_expand(item, outline, index, **kwargs):
        seen.append(kwargs.get("previous_spec"))
        return [first, second][index]

    monkeypatch.setattr(video.planner_expand, "expand", fake_expand)
    monkeypatch.setattr(video, "build_scene", lambda node, project, **k: node)
    video.build_project(project, out_dir=tmp_path, client=object(), cap=1, log=None,
                        recipe_scene_guidance="guide", recipe_visual_pattern="architecture_map",
                        recipe_continuity=True)
    assert seen == [None, first]
    assert project.scene(1).spec.continuity.carryover_ids == ["source"]


@pytest.mark.unit
def test_build_scene_without_recipe_guidance_does_not_pass_kwarg_to_expand(monkeypatch, tmp_path):
    """Existing fixed-signature callers of expand (no **kwargs) must keep working when no
    recipe is in play — the exact backward-compatibility guarantee Phase 1 promises."""
    from composition import video
    from composition.scene_dag import VideoProject
    from core.schemas.outline import Outline
    from core.schemas.scene_spec import SceneSpec
    from narration.narrate import NarratedResult

    outline = Outline.model_validate({"topic": "T", "items": [{"title": "A", "intent": "x"}]})
    project = VideoProject.from_outline(outline)
    spec = SceneSpec.model_validate({
        "title": "A", "prompt": "p", "narration": "n",
        "objects": [{"id": "o", "kind": "square"}],
        "beats": [{"action": "create", "targets": ["o"]}]})

    def fixed_signature_expand(item, outline, index, *, client=None):   # no recipe_guidance, no **k
        return spec

    monkeypatch.setattr(video.planner_expand, "expand", fixed_signature_expand)
    mp4 = tmp_path / "s0.mp4"
    mp4.write_bytes(b"v")
    monkeypatch.setattr(video.narrate, "build",
                        lambda spec, **k: NarratedResult(True, "code", mp4, tmp_path / "s.srt", [], []))

    node = video.build_scene(project.scene(0), project, scenes_dir=tmp_path,
                             quality="preview", client=object(), log=None)  # no recipe_scene_guidance
    assert node.mp4 == str(mp4)


@pytest.mark.unit
def test_build_scene_recipe_forces_pattern_and_structural_codegen(monkeypatch, tmp_path):
    from composition import video
    from composition.scene_dag import VideoProject
    from core.schemas.outline import Outline
    from core.schemas.scene_spec import SceneSpec
    from narration.narrate import NarratedResult

    project = VideoProject.from_outline(Outline.model_validate({
        "topic": "T", "items": [{"title": "A", "intent": "x"}]
    }))
    spec = SceneSpec.model_validate({
        "title": "A", "prompt": "p", "narration": "n",
        "objects": [{"id": "o", "kind": "square"}],
        "beats": [{"action": "create", "targets": ["o"]}],
    })
    seen = {}
    monkeypatch.setattr(video.planner_expand, "expand",
                        lambda item, outline, index, **k: (seen.update(k), spec)[1])
    monkeypatch.setattr(video.narrate, "build",
                        lambda spec, **k: (seen.update(narrate=k),
                                            NarratedResult(True, "code", None, None, [], []))[1])

    video.build_scene(project.scene(0), project, scenes_dir=tmp_path, quality="preview",
                      client=object(), log=None, recipe_scene_guidance="guide",
                      recipe_visual_pattern="architecture_map", recipe_structural=True)
    assert seen["recipe_guidance"] == "guide"
    assert seen["visual_pattern"] == "architecture_map"
    assert seen["narrate"]["structural"] is True
