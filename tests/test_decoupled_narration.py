"""Narration pacing (Tier 1 follow-up): a measured mismatch showed a scene's narration running 25.5s
over an 11.9s silent animation -- the back half played over a static frozen frame. `_scene_narration`
now accepts the MEASURED animation duration and turns it into a soft word-count budget in the prompt,
so the narrator doesn't write far more than the visuals can carry. Pure prompt-construction tests
(fake client captures the messages) -- no LLM/Docker needed."""
import pytest

from composition.decoupled import (_MIN_NARRATION_WORDS, _WORDS_PER_SECOND, _clean_narration,
                                    _scene_narration)
from core.schemas.outline import Outline, OutlineItem

ITEM = OutlineItem(title="Squares on the Right Triangle", intent="Build a square on each side.")
OUTLINE = Outline(topic="Pythagorean theorem", items=[ITEM])
CODE = "class GeneratedScene(LatticeScene):\n    def construct(self):\n        pass\n"


class _FakeClient:
    def __init__(self, reply="Some narration."):
        self.reply = reply
        self.system = None
        self.user = None

    def chat(self, messages, **kw):
        self.system = messages[0]["content"]
        self.user = messages[1]["content"]
        return self.reply


@pytest.mark.unit
def test_no_target_seconds_omits_pacing_rule():
    fake = _FakeClient()
    _scene_narration(ITEM, OUTLINE, 0, CODE, client=fake, target_seconds=None)
    assert "PACING" not in fake.system


@pytest.mark.unit
def test_target_seconds_adds_pacing_rule_with_computed_word_budget():
    fake = _FakeClient()
    target = 12.0
    _scene_narration(ITEM, OUTLINE, 0, CODE, client=fake, target_seconds=target)
    assert "PACING" in fake.system
    assert "12" in fake.system  # the target seconds appear
    expected_words = round(target * _WORDS_PER_SECOND)
    assert str(expected_words) in fake.system


@pytest.mark.unit
def test_tiny_target_seconds_floors_to_minimum_words():
    fake = _FakeClient()
    _scene_narration(ITEM, OUTLINE, 0, CODE, client=fake, target_seconds=1.0)  # 1s * 2.3 << floor
    assert f"{_MIN_NARRATION_WORDS} words" in fake.system


@pytest.mark.unit
def test_zero_target_seconds_omits_pacing_rule():
    # 0.0 is falsy -- an unmeasured/failed probe (_probe_duration returns 0.0 on failure) must not
    # produce a bogus "aim for 0 words" instruction
    fake = _FakeClient()
    _scene_narration(ITEM, OUTLINE, 0, CODE, client=fake, target_seconds=0.0)
    assert "PACING" not in fake.system


@pytest.mark.unit
def test_narration_grounds_in_code_and_arc():
    fake = _FakeClient()
    _scene_narration(ITEM, OUTLINE, 0, CODE, client=fake, target_seconds=10.0)
    assert "Pythagorean theorem" in fake.user
    assert "GeneratedScene" in fake.user  # the actual code, not a paraphrase


@pytest.mark.unit
def test_clean_narration_strips_chat_framing():
    # the exact web defect: model wrapped the spoken words in preamble + markdown + closing remarks,
    # which gTTS would read aloud. _clean_narration must keep ONLY the spoken sentences.
    garbage = (
        "Here's the spoken narration for this scene:\n\n"
        '**"TCP\'s slow start begins with an exponential increase."**\n\n'
        '**"Next, we\'ll see an example transfer."**\n\n'
        "Only visuals from the code are referenced. The narration stays concise.\n\n"
        "Let me know if you'd like any adjustments!"
    )
    out = _clean_narration(garbage)
    assert out.startswith("TCP's slow start")
    assert "example transfer" in out
    for bad in ("Here's the", "**", "Let me know", "Only visuals", "narration stays"):
        assert bad not in out


@pytest.mark.unit
def test_clean_narration_strips_stage_directions_rules_and_meta_paragraph():
    # the real RL scene-4 defect: gTTS read '[As the agent appears]', '---', and a whole
    # 'The narration flows naturally with the visuals...' paragraph ALOUD (190 words -> 100s scene).
    garbage = (
        "Here's a natural, engaging narration for this scene:\n\n"
        "---\n\n"
        "**Narration:**\n\n"
        '"Our robot faces a dilemma: exploration versus exploitation."\n'
        "[As the agent dot appears] Here's our agent, ready to decide.\n"
        "[Paths start drawing] It must balance trying new routes with proven ones.\n\n"
        "---\n\n"
        "The narration flows naturally with the visuals, explaining the concept while using the "
        "on-screen elements to reinforce the explanation."
    )
    out = _clean_narration(garbage)
    assert out.startswith("Our robot faces a dilemma")
    assert "exploration versus exploitation" in out
    for bad in ("[", "]", "---", "Here's a natural", "flows naturally", "on-screen elements", "**"):
        assert bad not in out


@pytest.mark.unit
def test_cap_words_trims_runaway_to_sentence_boundary():
    from composition.decoupled import _cap_words
    long = " ".join(f"Word{i}." if i % 5 == 4 else f"word{i}" for i in range(60))
    capped = _cap_words(long, 20)
    assert len(capped.split()) <= 20
    assert capped.rstrip().endswith(".")           # cut at a sentence boundary, not mid-thought
    # under the cap -> untouched
    short = "Just three words."
    assert _cap_words(short, 20) == short


@pytest.mark.unit
def test_clean_narration_passthrough_clean_text():
    clean = "This scene shows a right triangle. Watch how the squares relate. Next, we prove it."
    assert _clean_narration(clean) == clean


@pytest.mark.unit
def test_clean_narration_never_empty():
    # if EVERYTHING looked like meta, fall back to the original rather than return empty audio
    assert _clean_narration("Here's the narration:").strip() != ""


@pytest.mark.unit
def test_narration_preview_strips_scaffold_boilerplate():
    # structural mode prepends the LatticeScene grid class; the narrator must see the SCENE, not the
    # grid boilerplate (else it narrates "coordinates A to E, columns 1 through 8" -- a real regression)
    scaffolded = (
        "class LatticeScene(Scene):\n"
        "    GRID_COLS = 8\n"
        "    def setup_scene(self, title): pass\n"
        "    def place_in_area(self, m, a, b): pass\n"
        "class GeneratedScene(LatticeScene):\n"
        "    def construct(self):\n"
        "        self.square_on_segment(A, B, away_from=C)  # the real scene\n"
    )
    fake = _FakeClient()
    _scene_narration(ITEM, OUTLINE, 0, scaffolded, client=fake, target_seconds=10.0)
    assert "square_on_segment" in fake.user       # the real scene IS shown
    assert "GRID_COLS" not in fake.user            # the grid boilerplate is NOT
