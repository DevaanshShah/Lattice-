"""Unit tests for code-level cost levers: prompt caching + token cap. No network."""
import pytest


@pytest.mark.unit
def test_cache_control_added_for_anthropic():
    from core.llm import LLMClient
    c = LLMClient(model="anthropic/claude-sonnet-4.5")
    msgs = [{"role": "system", "content": "BIG STATIC SYSTEM PROMPT"},
            {"role": "user", "content": "hi"}]
    out = c._with_cache(msgs, None)
    assert isinstance(out[0]["content"], list)
    block = out[0]["content"][0]
    assert block["text"] == "BIG STATIC SYSTEM PROMPT"
    assert block["cache_control"] == {"type": "ephemeral"}
    assert out[1] == msgs[1]                         # user message untouched
    assert msgs[0]["content"] == "BIG STATIC SYSTEM PROMPT"   # original not mutated


@pytest.mark.unit
@pytest.mark.parametrize("model", ["openai/gpt-4o-mini", "gemini-2.5-flash", "qwen/qwen3-coder"])
def test_cache_control_noop_for_non_anthropic(model):
    from core.llm import LLMClient
    c = LLMClient(model=model)
    msgs = [{"role": "system", "content": "x"}, {"role": "user", "content": "y"}]
    assert c._with_cache(msgs, None) == msgs         # unchanged (relies on auto-caching)


@pytest.mark.unit
def test_cache_control_respects_flag(monkeypatch):
    from core.config import settings
    from core.llm import LLMClient
    monkeypatch.setattr(settings, "prompt_cache_enabled", False)
    c = LLMClient(model="anthropic/claude-sonnet-4.5")
    msgs = [{"role": "system", "content": "x"}, {"role": "user", "content": "y"}]
    assert c._with_cache(msgs, None) == msgs         # disabled -> no-op even for Anthropic


@pytest.mark.unit
def test_cache_control_handles_no_system_message():
    from core.llm import LLMClient
    c = LLMClient(model="anthropic/claude-sonnet-4.5")
    msgs = [{"role": "user", "content": "no system here"}]
    assert c._with_cache(msgs, None) == msgs         # nothing to cache


@pytest.mark.unit
def test_max_output_tokens_configured():
    from core.config import settings
    assert settings.max_output_tokens > 0            # the reservation/cost cap exists
