"""Thin LLM wrapper: one function, forced tool call => structured JSON, retries, usage.

Two interchangeable clients implement the same contract (`LLMClient`):
  * AnthropicClient  - api.anthropic.com or any Anthropic-compatible endpoint
  * OpenAIChatClient - any OpenAI-compatible /chat/completions endpoint (see openai_client.py)
`build_client()` picks one from VERIFIER_PROVIDER.
"""
from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass, field
from typing import Any, Protocol

import anthropic

from . import config


class UpstreamError(Exception):
    """LLM provider failed after all retries (maps to HTTP 502/504)."""

    def __init__(self, message: str, timeout: bool = False):
        super().__init__(message)
        self.timeout = timeout


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    retries: int = 0


@dataclass
class LLMResult:
    data: dict[str, Any]
    usage: Usage = field(default_factory=Usage)


class LLMClient(Protocol):
    model: str

    async def call_tool(self, system: str, messages: list[dict[str, Any]],
                        tool_name: str, tool_schema: dict[str, Any], usage: Usage) -> dict[str, Any]: ...


# Retryable provider failures: rate limits, connection trouble, 5xx.
RETRYABLE = (anthropic.RateLimitError, anthropic.APIConnectionError,
             anthropic.InternalServerError, anthropic.APITimeoutError)


def backoff_s(attempt: int) -> float:
    return min(2 ** attempt, 20)


def _input_volume(usage: Any) -> int:
    """Input tokens actually sent: reported input plus any prompt-cache read/creation traffic.

    Anthropic-style responses keep the cached prefix out of `input_tokens`, which undercounts the
    volume by an order of magnitude on repeated prompt prefixes (measured: 331 vs 4033 tokens per
    case for the same work on the two transports).
    """
    return (getattr(usage, "input_tokens", 0) or 0) \
        + (getattr(usage, "cache_read_input_tokens", 0) or 0) \
        + (getattr(usage, "cache_creation_input_tokens", 0) or 0)


class AnthropicClient:
    """Forces the model to answer by calling exactly one tool whose input is our JSON schema."""

    def __init__(self, model: str | None = None, timeout_s: float | None = None,
                 max_retries: int | None = None):
        self.model = model or config.model()
        self._client = anthropic.AsyncAnthropic(
            api_key=config.anthropic_api_key(),
            auth_token=config.anthropic_auth_token(),
            base_url=config.anthropic_base_url(),
            timeout=timeout_s if timeout_s is not None else config.timeout_s(),
            max_retries=0,  # retrying is this class's job, so usage.retries stays honest
        )
        self._max_retries = config.max_retries() if max_retries is None else max_retries
        # Recent SDKs dropped `temperature` from the typed signature (anthropic 1.15 does not
        # accept it at all). Detect instead of pinning a version: sampling still has to be pinned
        # to 0 for a reproducible benchmark.
        self._temperature_is_typed = "temperature" in inspect.signature(
            self._client.messages.create).parameters

    def _request_kwargs(self) -> dict[str, Any]:
        extra = config.extra_body()
        kwargs: dict[str, Any] = {}
        if self._temperature_is_typed:
            kwargs["temperature"] = 0
        else:
            extra = {"temperature": 0} | extra  # pass it through untyped instead
        if extra:
            kwargs["extra_body"] = extra
        return kwargs

    async def call_tool(self, system, messages, tool_name, tool_schema, usage):
        last: Exception | None = None
        for attempt in range(self._max_retries + 1):
            malformed: str | None = None
            try:
                resp = await self._client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    system=system,
                    messages=messages,
                    tools=[{"name": tool_name, "description": "Return the result.",
                            "input_schema": tool_schema}],
                    tool_choice={"type": "tool", "name": tool_name},
                    **self._request_kwargs(),
                )
                usage.calls += 1
                # Anthropic-style usage reports prompt-cache traffic separately, so the billed input
                # volume is the sum of the three fields. Counting all of it at the cache-miss price
                # keeps the cost column an upper bound instead of a 12x undercount.
                usage.input_tokens += _input_volume(resp.usage)
                usage.output_tokens += resp.usage.output_tokens
                for block in resp.content:
                    if block.type == "tool_use" and block.name == tool_name:
                        return dict(block.input)
                # Truncated (max_tokens) or otherwise off-schema output: retryable.
                malformed = f"no {tool_name!r} tool call in the response (stop_reason={resp.stop_reason})"
            except RETRYABLE as e:
                last = e
                usage.retries += 1
                await asyncio.sleep(backoff_s(attempt))
                continue
            except anthropic.APIStatusError as e:  # 4xx other than 429: do not retry
                raise UpstreamError(f"LLM request rejected: {e.status_code}") from e
            last = ValueError(malformed)
            usage.retries += 1
            if attempt < self._max_retries:
                await asyncio.sleep(backoff_s(attempt))
        raise UpstreamError(f"LLM unavailable after retries: {last}",
                            timeout=isinstance(last, anthropic.APITimeoutError))


def build_client(model: str | None = None) -> LLMClient:
    """Client for VERIFIER_PROVIDER (anthropic | openai)."""
    provider = config.provider()
    if provider == "anthropic":
        return AnthropicClient(model=model)
    if provider in ("openai", "openai-compatible", "deepseek"):
        from .openai_client import OpenAIChatClient  # imported lazily: optional path
        return OpenAIChatClient(model=model)
    raise KeyError(f"VERIFIER_PROVIDER={provider!r} (expected 'anthropic' or 'openai')")
