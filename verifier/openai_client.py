"""OpenAI-compatible chat-completions client (DeepSeek, OpenAI, vLLM, Ollama, ...).

Same contract as `AnthropicClient.call_tool`: force exactly one function call whose
arguments are our JSON schema, retry transient failures, and count usage. Kept separate
from llm.py so the Anthropic path stays the one that ships by default.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import httpx

from . import config
from .llm import UpstreamError, Usage, backoff_s


class OpenAIChatClient:
    name = "openai"

    def __init__(self, model: str | None = None, timeout_s: float | None = None,
                 max_retries: int | None = None, transport: httpx.AsyncBaseTransport | None = None,
                 api_key: str | None = None, base_url: str | None = None):
        self.model = model or config.model()
        self._key = api_key or config.openai_api_key()
        self._base = (base_url or config.openai_base_url()).rstrip("/")
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
    def _escape_unescaped_quotes(raw: str, close_at_end: bool = False) -> str:
        """Escape quotes that weaker models emit inside a JSON string without a backslash.

        The scanner tracks whether a string is an object key or a value. A key closes before
        `:`; a value closes only before `,`, `}`, `]` or end of input. This keeps JSON fragments
        such as `"quote": "categories": "Bars"` intact instead of ending the value at the first
        inner quote. `close_at_end` additionally closes a value that is missing its final quote
        when the object/array ends.
        """
        out: list[str] = []
        stack: list[str] = []
        expect_key = False
        mode: str | None = None
        i = 0
        while i < len(raw):
            ch = raw[i]
            if mode is None:
                out.append(ch)
                if ch == '"':
                    mode = "key" if stack and stack[-1] == "{" and expect_key else "value"
                elif ch == "{":
                    stack.append("{")
                    expect_key = True
                elif ch == "[":
                    stack.append("[")
                    expect_key = False
                elif ch in "}]":
                    if stack:
                        stack.pop()
                    expect_key = False
                elif ch == ",":
                    expect_key = bool(stack and stack[-1] == "{")
                elif ch == ":" or not ch.isspace():
                    expect_key = False
                i += 1
                continue
            if ch == "\\":
                out.append(ch)
                if i + 1 < len(raw):
                    out.append(raw[i + 1])
                i += 2
                continue
            if ch == '"':
                j = i + 1
                while j < len(raw) and raw[j] in " \t\r\n":
                    j += 1
                nxt = raw[j] if j < len(raw) else ""
                closing = (nxt == ":") if mode == "key" else (nxt in ",}]" or nxt == "")
                if closing:
                    out.append(ch)
                    mode = None
                else:
                    out.append('\\"')
                i += 1
                continue
            if close_at_end and mode == "value" and ch in "}]":
                out.append('"')
                if stack:
                    stack.pop()
                expect_key = False
                mode = None
                out.append(ch)
                i += 1
                continue
            out.append(ch)
            i += 1
        return "".join(out)

    @classmethod
    def _parse_arguments(cls, raw: Any) -> dict[str, Any] | None:
        """Function arguments arrive as a JSON string. Weaker models occasionally emit raw
        control characters or unescaped quotes inside a string, which strict JSON rejects.
        Try strict/relaxed parsing, then a deterministic quote escape and missing-comma repair
        before spending another provider request."""
        if isinstance(raw, dict):
            return raw
        if not isinstance(raw, str):
            return None
        cleaned = re.sub(r',\s*([}\]])', r'\1', raw)
        literal_comma = re.sub(r'(?<=[0-9])\s+(?=")', ', ', raw)
        literal_comma = re.sub(r'\b(true|false|null)\s+(?=")', r'\1, ', literal_comma)
        pre_comma = re.sub(r'(?<=[}\]])\s+(?=["{\[])', ', ', raw)
        pre_comma = re.sub(r'(?<=")\s+(?=["{\[])', ', ', pre_comma)
        texts = [raw, cleaned, literal_comma, pre_comma]
        for base in (raw, pre_comma):
            for close_at_end in (False, True):
                repaired = cls._escape_unescaped_quotes(base, close_at_end=close_at_end)
                repaired = re.sub(r',\s*([}\]])', r'\1', repaired)
                repaired = re.sub(r'(?<=[}\]])\s+(?=["{\[])', ', ', repaired)
                repaired = re.sub(r'(?<=")\s+(?=["{\[])', ', ', repaired)
                repaired = re.sub(r'(?<=[0-9])\s+(?=")', ', ', repaired)
                repaired = re.sub(r'\b(true|false|null)\s+(?=")', r'\1, ', repaired)
                texts.append(repaired)
        for text in dict.fromkeys(texts):
            for strict in (True, False):
                try:
                    parsed = json.loads(text, strict=strict)
                    if isinstance(parsed, dict):
                        return parsed
                except json.JSONDecodeError:
                    pass
        json.loads(raw, strict=False)  # surface the original parse error to the retry loop
        return None

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
