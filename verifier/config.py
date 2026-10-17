"""Process-wide settings.

Everything is read from the environment. `.env` (next to `pyproject.toml`, or at
VERIFIER_ENV_FILE) is loaded here, once, at import time: the Anthropic SDK does not read `.env`
by itself, so a key placed there would otherwise be silently ignored. Real environment variables
always win over `.env` (override=False).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

ENV_FILE = Path(os.environ.get("VERIFIER_ENV_FILE", "").strip()
                or Path(__file__).resolve().parent.parent / ".env")
load_dotenv(ENV_FILE, override=False)


def optional_env(name: str) -> str | None:
    """Value of `name`, or None when unset/blank."""
    return os.environ.get(name, "").strip() or None


def require_env(name: str) -> str:
    """Raise KeyError(name) when unset; the HTTP layer maps that to 500/misconfigured."""
    value = optional_env(name)
    if value is None:
        raise KeyError(name)
    return value


def float_env(name: str, default: float) -> float:
    value = optional_env(name)
    return default if value is None else float(value)


def int_env(name: str, default: int) -> int:
    value = optional_env(name)
    return default if value is None else int(value)


def provider() -> str:
    """`anthropic` (default) or `openai` (any OpenAI-compatible /chat/completions API)."""
    return (optional_env("VERIFIER_PROVIDER") or "anthropic").lower()


# --------------------------------------------------------------------------- anthropic
def anthropic_api_key() -> str | None:
    return optional_env("VERIFIER_API_KEY") or optional_env("ANTHROPIC_API_KEY")


def anthropic_auth_token() -> str | None:
    return optional_env("ANTHROPIC_AUTH_TOKEN")


def anthropic_base_url() -> str | None:
    """Provider-specific setting first: a stale VERIFIER_BASE_URL must not hijack a switched provider."""
    return optional_env("ANTHROPIC_BASE_URL") or optional_env("VERIFIER_BASE_URL")


# ------------------------------------------------------------------------------ openai
def openai_api_key() -> str:
    for name in ("VERIFIER_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY"):
        key = optional_env(name)
        if key:
            return key
    raise KeyError("VERIFIER_API_KEY (or DEEPSEEK_API_KEY / OPENAI_API_KEY)")


def openai_base_url() -> str:
    """Explicit setting wins (provider-specific first); otherwise guess from which key is present."""
    explicit = optional_env("OPENAI_BASE_URL") or optional_env("VERIFIER_BASE_URL")
    if explicit:
        return explicit.rstrip("/")
    if optional_env("DEEPSEEK_API_KEY"):
        return "https://api.deepseek.com/v1"
    return "https://api.openai.com/v1"


# ------------------------------------------------------------------------------- common
def model() -> str:
    return require_env("VERIFIER_MODEL")


def timeout_s() -> float:
    return float_env("VERIFIER_TIMEOUT_S", 60.0)


def max_retries() -> int:
    return int_env("VERIFIER_MAX_RETRIES", 3)


def extra_body() -> dict:
    """Provider-specific request fields, as a JSON object, merged into the request last.

    Needs to exist because some endpoints refuse a forced tool call unless a vendor flag is
    set: DeepSeek's thinking models answer
    `400 Thinking mode does not support this tool_choice` unless the request carries
    {"thinking": {"type": "disabled"}}.
    """
    raw = optional_env("VERIFIER_EXTRA_BODY")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"VERIFIER_EXTRA_BODY is not valid JSON: {e}") from e
    if not isinstance(parsed, dict):
        raise ValueError("VERIFIER_EXTRA_BODY must be a JSON object")
    return parsed


def describe() -> dict[str, object]:
    """Non-secret view of the LLM settings, used by /health to debug a bad .env."""
    return {
        "provider": provider(),
        "model": optional_env("VERIFIER_MODEL"),
        "prompt_version": optional_env("VERIFIER_PROMPT_VERSION") or "v1",
        "api_key_set": bool(anthropic_api_key() if provider() == "anthropic" else
                            (optional_env("VERIFIER_API_KEY") or optional_env("DEEPSEEK_API_KEY")
                             or optional_env("OPENAI_API_KEY"))),
        "base_url_set": bool(anthropic_base_url() if provider() == "anthropic" else
                             optional_env("VERIFIER_BASE_URL") or optional_env("OPENAI_BASE_URL")),
        "env_file": str(ENV_FILE) if ENV_FILE.is_file() else None,
    }
