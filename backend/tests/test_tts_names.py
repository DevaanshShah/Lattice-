"""A name on screen that is also a word is read as the name (the room "A", not the article)."""
import pytest

from narration.tts import _for_speech, opens_on_name, spoken_names


@pytest.mark.unit
def test_the_names_on_screen_are_found_in_any_payload():
    payloads = [{"nodes": ["S", "A", "C", "G"], "edges": [["S", "A"]], "label": "The maze"},
                {"items": [{"name": "NYC"}, "queue"]}]
    assert spoken_names(payloads) == {"S", "A", "C", "G", "NYC"}


@pytest.mark.unit
def test_a_shown_as_a_name_is_read_as_the_letter():
    names = {"S", "A", "C"}
    assert _for_speech("Room A comes out next, and S adds A and C.", names) == \
        "Room eigh comes out next, and S adds eigh and C."
    # at the start of a sentence it is the article (the saved BFS lesson, 2026-11-22)
    assert _for_speech("A small maze has rooms. Then A waits.", names) == \
        "A small maze has rooms. Then eigh waits."
    assert _for_speech("Room A's doorway leads on.", names) == "Room A's doorway leads on."
    assert _for_speech("Take a step.", names) == "Take a step."       # the article stays


@pytest.mark.unit
def test_without_an_a_on_screen_the_article_is_left_alone():
    assert _for_speech("A cache keeps a copy.", {"S", "C"}) == "A cache keeps a copy."
    assert _for_speech("A cache keeps a copy.") == "A cache keeps a copy."


@pytest.mark.integration
def test_the_voice_says_the_letter():
    from kokoro_onnx import Kokoro
    from core.config import settings
    voice = Kokoro(settings.kokoro_model, settings.kokoro_voices)
    said = voice.tokenizer.phonemize(_for_speech("Then A and C wait.", {"A", "C"}), "en-us")
    assert "ˈeɪ ænd" in said
    assert "ɐ ænd" in voice.tokenizer.phonemize("Then A and C wait.", "en-us")   # the bug it fixes


@pytest.mark.unit
def test_a_sentence_opening_on_the_name_is_found():
    assert opens_on_name("A comes out next.", {"A", "S"}) == "A"
    assert opens_on_name("S is done. A comes out next.", {"A"}) == "A"
    assert opens_on_name("Room A comes out next.", {"A"}) is None
    assert opens_on_name("A cache keeps a copy.", {"S"}) is None
