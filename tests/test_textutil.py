"""Tests for robust code extraction (the prose/fence-leak failure mode the prompt review flagged)."""
import pytest

CODE = "from manim import *\n\nclass GeneratedScene(Scene):\n    def construct(self):\n        pass"


@pytest.mark.unit
def test_plain_code_unchanged():
    from core.textutil import strip_code_fences
    assert strip_code_fences(CODE) == CODE


@pytest.mark.unit
def test_fenced_block_extracted():
    from core.textutil import strip_code_fences
    assert strip_code_fences(f"```python\n{CODE}\n```") == CODE


@pytest.mark.unit
def test_leading_prose_before_fence_stripped():
    from core.textutil import strip_code_fences
    assert strip_code_fences(f"Here is the file:\n```python\n{CODE}\n```\nHope this helps!") == CODE


@pytest.mark.unit
def test_leading_prose_no_fence_stripped():
    from core.textutil import strip_code_fences
    assert strip_code_fences(f"Sure! Here you go:\n{CODE}") == CODE


@pytest.mark.unit
def test_import_form_detected():
    from core.textutil import strip_code_fences
    src = "import manim\nclass GeneratedScene(manim.Scene): pass"
    assert strip_code_fences(f"blah blah\n{src}") == src
