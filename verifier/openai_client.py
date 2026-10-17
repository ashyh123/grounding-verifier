"""OpenAI-compatible chat-completions client (DeepSeek, OpenAI, vLLM, Ollama, ...).

Same contract as `AnthropicClient.call_tool`: force exactly one function call whose
arguments are our JSON schema, retry transient failures, and count usage. Kept separate
from llm.py so the Anthropic path stays the one that ships by default.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from . import config
from .llm import UpstreamError, Usage, backoff_s


class OpenAIChatClient:
    name = "openai"

    def __init__(self, model: str | None = None, timeout_s: float | None = None,
                 max_retries: int | None = None, transport: httpx.AsyncBaseTransport | None = None):
        self.model = model or config.model()
        self._key = config.openai_api_key()
        self._base = config.openai_base_url()
        self._max_retries = config.max_retries() if max_retries is None else max_retries
        timeout = timeout_s if timeout_s is not None else config.timeout_s()
        self._client = httpx.AsyncClient(base_url=self._base, timeout=timeout, transport=transport)

    async def call_tool(self, system: str, messages: list[dict[str, Any]],
                        tool_name: str, tool_schema: dict[str, Any], usage: Usage) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": 4096,
            "messages": [{"role": "system", "content": system}] + messages,
            "tools": [{"type": "function", "function": {
                "name": tool_name, "description": "Return the result.", "parameters": tool_schema}}],
            "tool_choice": {"type": "function", "function": {"name": tool_name}},
        } | config.extra_body()
        last: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                resp = await self._client.post("/chat/completions", json=payload,
                                               headers={"Authorization": f"Bearer {self._key}"})
                if resp.status_code == 429 or resp.status_code >= 500:
                    last = UpstreamError(f"LLM request rejected: {resp.status_code}")
                    usage.retries += 1
                    await asyncio.sleep(backoff_s(attempt))
                    continue
                if resp.status_code >= 400:
                    raise UpstreamError(f"LLM request rejected: {resp.status_code} {resp.text[:200]}")
                body = resp.json()
                usage.calls += 1
                u = body.get("usage") or {}
                usage.input_tokens += u.get("prompt_tokens", 0)
                usage.output_tokens += u.get("completion_tokens", 0)
                data = self._extract_tool_call(body, tool_name)
                if data is not None:
                    return data
                last = ValueError(f"no {tool_name!r} tool call in the response")
            except (httpx.TransportError, httpx.TimeoutException) as e:
                last = e
            except (json.JSONDecodeError, KeyError, IndexError) as e:
                last = ValueError(f"unparseable response: {e}")
            usage.retries += 1
            if attempt < self._max_retries:
                await asyncio.sleep(backoff_s(attempt))
        raise UpstreamError(f"LLM unavailable after retries: {last}",
                            timeout=isinstance(last, httpx.TimeoutException))

    @staticmethod
    def _parse_arguments(raw: Any) -> dict[str, Any] | None:
        """Function arguments arrive as a JSON string. Weaker models occasionally emit a raw
        control character inside a string, which strict JSON rejects, so fall back to
        strict=False rather than burning the whole request."""
        if isinstance(raw, dict):
            return raw
        if not isinstance(raw, str):
            return None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = json.loads(raw, strict=False)  # lets control chars through
        return parsed if isinstance(parsed, dict) else None

    @classmethod
    def _extract_tool_call(cls, body: dict[str, Any], tool_name: str) -> dict[str, Any] | None:
        for choice in body.get("choices") or []:
            for call in (choice.get("message") or {}).get("tool_calls") or []:
                fn = call.get("function") or {}
                if fn.get("name") != tool_name:
                    continue
                args = cls._parse_arguments(fn.get("arguments"))
                if args is not None:
                    return args
        return None
