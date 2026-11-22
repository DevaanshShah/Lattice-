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


def _client_answering(monkeypatch, base_url, answers):
    """An LLMClient whose provider is a list of canned (content, finish_reason) answers."""
    from types import SimpleNamespace

    from core.llm import LLMClient

    sent = []

    def create(**kwargs):
        sent.append(kwargs)
        content, finish = answers[len(sent) - 1]
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=content), finish_reason=finish)], usage=None)

    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(LLMClient, "client", property(lambda self: fake))
    return LLMClient(model="deepseek/deepseek-v4.1-flash", base_url=base_url, api_key="k"), sent


@pytest.mark.unit
def test_an_answer_cut_off_by_the_token_limit_is_not_asked_for_again(monkeypatch):
    client, sent = _client_answering(monkeypatch, "https://openrouter.ai/api/v1",
                                     [("", "length"), ("late", "stop")])
    response = client._create(model=client.model, messages=[], attempts=3)
    assert len(sent) == 1 and response.choices[0].message.content == ""


@pytest.mark.unit
def test_the_reasoning_switch_goes_to_openrouter_and_is_dropped_for_a_direct_provider(monkeypatch):
    off = {"reasoning": {"enabled": False}}
    client, sent = _client_answering(monkeypatch, "https://openrouter.ai/api/v1", [("{}", "stop")])
    client._create(model=client.model, messages=[], attempts=1, extra_body=dict(off))
    assert sent[0]["extra_body"]["reasoning"] == {"enabled": False}
    client, sent = _client_answering(monkeypatch, "https://api.deepseek.com/v1", [("{}", "stop")])
    client._create(model=client.model, messages=[], attempts=1, extra_body=dict(off))
    assert "extra_body" not in sent[0]
