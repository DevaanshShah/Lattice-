"""Unit tests for the model-comparison harness (scripts/test_video). No network."""
import pytest


@pytest.mark.unit
def test_slug_sanitizes():
    from scripts.test_video import _slug
    assert _slug("openai/gpt-4o-mini") == "openai_gpt_4o_mini"
    assert _slug("moonshotai/kimi-k2.6") == "moonshotai_kimi_k2_6"
    assert _slug("how a Linked List works!") == "how_a_linked_list_works"
    assert _slug("") == "untitled"


@pytest.mark.unit
def test_append_index_creates_table_and_rows(tmp_path):
    from scripts.test_video import append_index
    root = tmp_path / "model_tests"
    v = root / "llama" / "topic" / "final.mp4"
    v.parent.mkdir(parents=True)
    v.write_bytes(b"x")

    append_index(root, model="llama-3.3-70b", topic="linked list", rendered=2, total=2,
                 quality="preview", final_path=str(v))
    append_index(root, model="openai/gpt-4o-mini", topic="linked list", rendered=3, total=3,
                 quality="preview", final_path=str(v))

    text = (root / "index.md").read_text(encoding="utf-8")
    assert text.count("\n|") >= 4                       # header + 2 separator/data rows
    assert "llama-3.3-70b" in text and "openai/gpt-4o-mini" in text
    assert "2/2" in text and "3/3" in text
    assert "llama/topic/final.mp4" in text              # relative path recorded


@pytest.mark.unit
def test_append_index_handles_no_video(tmp_path):
    from scripts.test_video import append_index
    root = tmp_path / "model_tests"
    append_index(root, model="m", topic="t", rendered=0, total=2, quality="preview", final_path=None)
    assert "(none)" in (root / "index.md").read_text(encoding="utf-8")
