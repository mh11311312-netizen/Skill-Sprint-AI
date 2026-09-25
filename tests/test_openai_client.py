"""The OpenAI client wrapper: argument building and error handling (no network)."""
from types import SimpleNamespace
import pytest
from genai_pipeline.client import OpenAIClient, GenAIError


def _fake_response(text, finish="stop"):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason=finish)])


def test_missing_key_is_reported():
    with pytest.raises(GenAIError, match="OPENAI_API_KEY"):
        OpenAIClient("", "gpt-5.6-luna")


def test_json_mode_and_no_temperature_for_gpt5(monkeypatch):
    c = OpenAIClient("sk-test", "gpt-5.6-luna")
    seen = {}
    monkeypatch.setattr(c.client.chat.completions, "create", lambda **kw: seen.update(kw) or _fake_response('{"a": 1}'))
    assert c.generate("sys", "prompt", 0.2) == '{"a": 1}'
    assert seen["response_format"] == {"type": "json_object"} and "temperature" not in seen


def test_temperature_sent_for_older_models(monkeypatch):
    c = OpenAIClient("sk-test", "gpt-4.1-mini")
    seen = {}
    monkeypatch.setattr(c.client.chat.completions, "create", lambda **kw: seen.update(kw) or _fake_response("{}"))
    c.generate("s", "p", 0.2)
    assert seen["temperature"] == 0.2


def test_truncated_output_raises(monkeypatch):
    c = OpenAIClient("sk-test", "gpt-5.6-luna")
    monkeypatch.setattr(c.client.chat.completions, "create", lambda **kw: _fake_response('{"a":', "length"))
    with pytest.raises(GenAIError, match="cut off"):
        c.generate("s", "p", 0.2)


def test_api_errors_are_wrapped(monkeypatch):
    c = OpenAIClient("sk-test", "gpt-5.6-luna")
    def boom(**kw):
        raise RuntimeError("401 invalid api key")
    monkeypatch.setattr(c.client.chat.completions, "create", boom)
    with pytest.raises(GenAIError, match="invalid api key"):
        c.generate("s", "p", 0.2)
