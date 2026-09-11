"""Unit tests for the product-video recipe picker (planner/product_recipe.py) and its threading
through composition/video.py. No LLM, no Docker: the picker is pure keyword matching over
prompts/product_video_recipes.json, and the threading tests stub out planner_outline.generate /
planner_expand.expand to capture whether recipe_guidance was passed."""
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
def test_generate_video_with_recipe_auto_injects_guidance(monkeypatch, tmp_path):
    from composition import video
    from core.schemas.outline import Outline
    from core.schemas.style import StyleSpec

    seen = {}
    monkeypatch.setattr(video.planner_outline, "generate",
                        lambda topic, **k: (
                            seen.__setitem__("outline_guidance", k.get("recipe_guidance")),
                            Outline.model_validate({"topic": topic, "items": [{"title": "A", "intent": "x"}]})
                        )[1])
    monkeypatch.setattr(video.style_gen, "generate", lambda topic, outline, **k: StyleSpec())

    def fake_build_scene(node, project, *, scenes_dir, quality, client, log, **k):
        seen["scene_guidance"] = k.get("recipe_scene_guidance")
        return node

    monkeypatch.setattr(video, "build_scene", fake_build_scene)
    monkeypatch.setattr(video.stitch, "stitch", lambda mp4s, **k: tmp_path / "final.mp4")

    video.generate_video("Show our conversion funnel: leads to MQL to SQL", out_dir=tmp_path,
                         client=object(), log=None, recipe="auto")
    assert seen["outline_guidance"]        # non-empty guidance string was passed through
    assert seen["scene_guidance"]
    assert "funnel" in seen["outline_guidance"].lower()


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
