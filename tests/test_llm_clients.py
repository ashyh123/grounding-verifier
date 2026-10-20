"""Client-level behaviour: forced tool calls, retries, usage accounting, error mapping.

No network: the Anthropic path gets a scripted fake, the OpenAI path an httpx MockTransport.
"""
import asyncio
import json
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from verifier import llm, openai_client
from verifier.llm import AnthropicClient, UpstreamError, Usage, build_client
from verifier.openai_client import OpenAIChatClient

SCHEMA = {"type": "object", "properties": {"claims": {"type": "array"}}, "required": ["claims"]}


@pytest.fixture(autouse=True)
def fast_and_configured(monkeypatch):
    monkeypatch.setenv("VERIFIER_MODEL", "test-model")
    monkeypatch.setenv("VERIFIER_API_KEY", "sk-test")
    monkeypatch.setattr(llm, "backoff_s", lambda attempt: 0)
    monkeypatch.setattr(openai_client, "backoff_s", lambda attempt: 0)


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://api.example.com/v1/messages")


def _status_error(cls, code: int):
    return cls("boom", response=httpx.Response(code, request=_request()), body=None)


def _tool_use_response(args: dict, stop_reason: str = "tool_use"):
    return SimpleNamespace(content=[SimpleNamespace(type="tool_use", name="report", input=args)],
                           usage=SimpleNamespace(input_tokens=11, output_tokens=4),
                           stop_reason=stop_reason)


class _FakeMessages:
    def __init__(self, script):
        self.script = list(script)
        self.seen: list[dict] = []

    async def create(self, **kwargs):
        self.seen.append(kwargs)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _anthropic(script, max_retries: int = 0) -> tuple[AnthropicClient, _FakeMessages]:
    client = AnthropicClient(max_retries=max_retries)
    fake = _FakeMessages(script)
    client._client = SimpleNamespace(messages=fake)
    return client, fake


def call(client, usage: Usage | None = None) -> dict:
    usage = usage if usage is not None else Usage()
    return asyncio.run(client.call_tool("sys", [{"role": "user", "content": "hi"}], "report",
                                        SCHEMA, usage))


def _temperature(kwargs: dict):
    """Older SDKs take temperature= typed; the installed one only accepts it via extra_body."""
    return kwargs.get("temperature", (kwargs.get("extra_body") or {}).get("temperature"))


def test_anthropic_forces_the_tool_and_counts_usage():
    client, fake = _anthropic([_tool_use_response({"claims": ["a"]})])
    usage = Usage()
    assert call(client, usage) == {"claims": ["a"]}
    assert (usage.calls, usage.input_tokens, usage.output_tokens, usage.retries) == (1, 11, 4, 0)
    kwargs = fake.seen[0]
    assert kwargs["tool_choice"] == {"type": "tool", "name": "report"}
    assert kwargs["model"] == "test-model"
    assert _temperature(kwargs) == 0  # pinned either way: a benchmark needs determinism


def test_anthropic_sends_typed_temperature_when_the_sdk_supports_it():
    client, fake = _anthropic([_tool_use_response({"claims": []})])
    client._temperature_is_typed = True  # simulate an SDK with the typed parameter
    call(client)
    kwargs = fake.seen[0]
    assert kwargs["temperature"] == 0 and "temperature" not in (kwargs.get("extra_body") or {})


def test_anthropic_merges_extra_body(monkeypatch):
    monkeypatch.setenv("VERIFIER_EXTRA_BODY", '{"thinking":{"type":"disabled"}}')
    client, fake = _anthropic([_tool_use_response({"claims": []})])
    client._temperature_is_typed = False
    call(client)
    assert fake.seen[0]["extra_body"] == {"temperature": 0, "thinking": {"type": "disabled"}}


def test_anthropic_retries_rate_limit_then_succeeds():
    client, _ = _anthropic([_status_error(anthropic.RateLimitError, 429),
                            _tool_use_response({"claims": []})], max_retries=2)
    usage = Usage()
    assert call(client, usage) == {"claims": []}
    assert usage.retries == 1 and usage.calls == 1  # the failed attempt is not a billed success


def test_anthropic_malformed_output_is_retried_then_upstream_error():
    truncated = SimpleNamespace(content=[SimpleNamespace(type="text", text="...")],
                                usage=SimpleNamespace(input_tokens=3, output_tokens=4096),
                                stop_reason="max_tokens")
    client, _ = _anthropic([truncated], max_retries=0)
    with pytest.raises(UpstreamError, match="max_tokens"):
        call(client)


def test_anthropic_4xx_is_not_retried():
    client, fake = _anthropic([_status_error(anthropic.BadRequestError, 400),
                               _tool_use_response({"claims": []})], max_retries=3)
    with pytest.raises(UpstreamError, match="rejected: 400"):
        call(client)
    assert len(fake.seen) == 1


def test_anthropic_missing_model_setting_is_a_keyerror(monkeypatch):
    monkeypatch.delenv("VERIFIER_MODEL", raising=False)
    with pytest.raises(KeyError):
        AnthropicClient()


# ------------------------------------------------------------------ OpenAI-compatible path
def _chat_response(args: dict | None, status: int = 200):
    if args is None:
        message = {"role": "assistant", "content": "no tool call here"}
    else:
        message = {"role": "assistant", "content": None,
                   "tool_calls": [{"id": "c1", "type": "function",
                                   "function": {"name": "report", "arguments": json.dumps(args)}}]}
    return httpx.Response(status, json={"choices": [{"message": message}],
                                        "usage": {"prompt_tokens": 20, "completion_tokens": 5}})


def _openai(handler, max_retries: int = 0) -> OpenAIChatClient:
    return OpenAIChatClient(model="test-model", max_retries=max_retries,
                            transport=httpx.MockTransport(handler))


def test_openai_parses_the_forced_function_call():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request):
        seen.append(request)
        return _chat_response({"claims": ["x"]})

    usage = Usage()
    assert call(_openai(handler), usage) == {"claims": ["x"]}
    assert (usage.calls, usage.input_tokens, usage.output_tokens) == (1, 20, 5)
    payload = json.loads(seen[0].content)
    assert payload["tool_choice"] == {"type": "function", "function": {"name": "report"}}
    assert payload["messages"][0] == {"role": "system", "content": "sys"}
    assert seen[0].headers["authorization"] == "Bearer sk-test"


def test_openai_retries_5xx_then_raises_upstream_error():
    calls = {"n": 0}

    def handler(request: httpx.Request):
        calls["n"] += 1
        return httpx.Response(503, json={"error": "overloaded"})

    with pytest.raises(UpstreamError, match="503"):
        call(_openai(handler, max_retries=2))
    assert calls["n"] == 3


def test_openai_missing_tool_call_is_retried():
    responses = [lambda: _chat_response(None), lambda: _chat_response({"claims": []})]
    client = _openai(lambda request: responses.pop(0)(), max_retries=2)
    usage = Usage()
    assert call(client, usage) == {"claims": []}
    assert usage.retries == 1


def test_openai_control_characters_in_arguments_are_tolerated():
    """DeepSeek-flash emitted a raw control char inside a string once; strict JSON rejects it."""
    args = json.dumps({"claims": ["line one\nline two"]}).replace("\\n", "\n")  # literal newline

    def handler(request: httpx.Request):
        return httpx.Response(200, json={"choices": [{"message": {
            "role": "assistant", "content": None,
            "tool_calls": [{"id": "c1", "type": "function",
                            "function": {"name": "report", "arguments": args}}]}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1}})

    assert call(_openai(handler)) == {"claims": ["line one\nline two"]}


def test_openai_unescaped_quotes_inside_arguments_are_repaired():
    """DeepSeek-v4-pro copied a quoted source sentence without escaping the inner quotes."""
    args = ('{"quote": "I sincerely apologize," Patrick Cherry told WNBC\'s Jonathan Dienst", '
            '"verdict": "SUPPORTED"}')

    def handler(request: httpx.Request):
        return httpx.Response(200, json={"choices": [{"message": {
            "role": "assistant", "content": None,
            "tool_calls": [{"id": "c1", "type": "function",
                            "function": {"name": "report", "arguments": args}}]}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1}})

    assert call(_openai(handler)) == {
        "quote": 'I sincerely apologize," Patrick Cherry told WNBC\'s Jonathan Dienst',
        "verdict": "SUPPORTED"}


def test_openai_json_fragment_inside_a_quoted_source_is_repaired():
    """The model copied a source JSON fragment into a quote without escaping either quote."""
    for args, expected in [
        ('{"quote": "categories": "Restaurants, Food, Breweries"}',
         {"quote": 'categories": "Restaurants, Food, Breweries'}),
        ('{"quote": "RestaurantsTakeOut": true}',
         {"quote": 'RestaurantsTakeOut": true'}),
    ]:
        def handler(request: httpx.Request, args=args):
            return httpx.Response(200, json={"choices": [{"message": {
                "role": "assistant", "content": None,
                "tool_calls": [{"id": "c1", "type": "function",
                                "function": {"name": "report", "arguments": args}}]}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1}})

        assert call(_openai(handler)) == expected


def test_openai_trailing_and_missing_commas_are_repaired():
    for args, expected in [
        ('{"a": 1,}', {"a": 1}),
        ('{"a": {"b": 1} "c": 2}', {"a": {"b": 1}, "c": 2}),
        ('{"a": "x" "b": "y"}', {"a": "x", "b": "y"}),
    ]:
        def handler(request: httpx.Request, args=args):
            return httpx.Response(200, json={"choices": [{"message": {
                "role": "assistant", "content": None,
                "tool_calls": [{"id": "c1", "type": "function",
                                "function": {"name": "report", "arguments": args}}]}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1}})

        assert call(_openai(handler)) == expected


def test_openai_4xx_is_not_retried():
    calls = {"n": 0}

    def handler(request: httpx.Request):
        calls["n"] += 1
        return httpx.Response(401, json={"error": "bad key"})

    with pytest.raises(UpstreamError, match="401"):
        call(_openai(handler, max_retries=3))
    assert calls["n"] == 1


def test_build_client_selects_the_provider(monkeypatch):
    monkeypatch.setenv("VERIFIER_PROVIDER", "anthropic")
    assert isinstance(build_client(), AnthropicClient)
    monkeypatch.setenv("VERIFIER_PROVIDER", "openai")
    assert isinstance(build_client(), OpenAIChatClient)
    monkeypatch.setenv("VERIFIER_PROVIDER", "carrier-pigeon")
    with pytest.raises(KeyError):
        build_client()


def test_input_volume_counts_cache_traffic():
    """Anthropic-style usage hides the cached prefix outside input_tokens; the bill includes it."""
    usage = SimpleNamespace(input_tokens=100, output_tokens=7,
                            cache_read_input_tokens=900, cache_creation_input_tokens=50)
    assert llm._input_volume(usage) == 1050
    assert llm._input_volume(SimpleNamespace(input_tokens=10, output_tokens=1,
                                             cache_read_input_tokens=None)) == 10
