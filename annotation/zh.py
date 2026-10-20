"""Chinese display layer for the review page. Display only — never written into the gold data.

The dataset is English by design (upstream passages, upstream answers), and translating it would
break every verbatim-quote invariant the benchmark depends on. So this module translates *copies*
for reading and leaves `context_passages`, `generated_answer` and every evidence quote untouched.

    uv run python -m annotation.zh --build            # translate every draft case (needs REVIEW_MODEL)
    uv run python -m annotation.zh --build --limit 2  # a small sample first
    uv run python -m annotation.zh --status           # what is cached, what is missing

Cache: `data/annotation/zh_cache.json`, keyed by the sha256 of the English text, so a translation
is paid for once and stays valid when cases are re-drafted but their text is unchanged. Each entry
records the model that produced it and when.

Config: user-selected `REVIEW_MODEL`, `REVIEW_BASE_URL` and `REVIEW_API_KEY` are required.
There is no fallback to the verifier's endpoint or key. Deliberately separate from `ANNOTATION_MODEL`: the
translation is a reading aid, so using a different model from the one drafting labels keeps the two
roles from being confused.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from verifier import config
from verifier.llm import Usage
from verifier.openai_client import OpenAIChatClient

from . import sources as S

CACHE = S.ANNOTATION_DIR / "zh_cache.json"
DRAFTS = S.ANNOTATION_DIR / "drafts.jsonl"

SYSTEM = """You translate annotation material for a bilingual reviewer. Translate English into
Simplified Chinese.

Rules:
- Translate faithfully and completely. Do not summarise, explain, add or drop anything.
- Keep proper nouns, numbers, dates and units exact. Keep names in the original Latin script on
  first mention and add the usual Chinese name in parentheses when one exists (e.g. "Mount Everest
  (珠穆朗玛峰)").
- Keep the original sentence boundaries where you can: the reviewer reads the Chinese beside the
  English and compares them.
- Do not translate text that is already Chinese.
- This is reference material for a factual-accuracy review; a mistranslation would mislead the
  reviewer. When a phrase is ambiguous, prefer the literal reading."""

TOOL = "submit_translation"
SCHEMA = {
    "type": "object",
    "properties": {
        "translations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"key": {"type": "string"}, "zh": {"type": "string"}},
                "required": ["key", "zh"],
            },
        }
    },
    "required": ["translations"],
}

BATCH_CHARS = 6000  # per call: keeps one request inside the context budget and easy to retry


def text_key(text: str) -> str:
    """Content hash: the cache key, so identical text is never translated twice."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def review_model() -> str:
    return S.require_annotation_model(config.optional_env("REVIEW_MODEL"), "REVIEW_MODEL")


def _client(model: str) -> OpenAIChatClient:
    model = S.require_annotation_model(model, "REVIEW_MODEL")
    key = config.optional_env("REVIEW_API_KEY")
    base = config.optional_env("REVIEW_BASE_URL")
    if not key or not base:
        raise SystemExit("STOP: user must select REVIEW_API_KEY and REVIEW_BASE_URL; "
                         "annotation never falls back to verifier credentials.")
    if "deepseek" in base.lower():
        raise SystemExit("STOP: annotation cannot use a DeepSeek endpoint (design v2.2).")
    return OpenAIChatClient(
        model=model,
        api_key=key, base_url=base)


def load_cache() -> dict[str, dict[str, Any]]:
    if not CACHE.is_file():
        return {}
    return json.loads(CACHE.read_text(encoding="utf-8"))


def save_cache(cache: dict[str, dict[str, Any]]) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=0, sort_keys=True) + "\n",
                     encoding="utf-8")


async def _translate_batch(client: OpenAIChatClient, texts: list[str],
                           usage: Usage) -> dict[str, str]:
    payload = [{"key": text_key(t), "text": t} for t in texts]
    data = await client.call_tool(
        system=SYSTEM,
        messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
        tool_name=TOOL, tool_schema=SCHEMA, usage=usage)
    out: dict[str, str] = {}
    for item in data.get("translations") or []:
        key, zh = item.get("key"), (item.get("zh") or "").strip()
        if key and zh:
            out[key] = zh
    return out


def translate_texts(texts: list[str], model: str) -> dict[str, str]:
    """Translate `texts` in batches. Returns {text_key: chinese}.

    One event loop owns the client for the whole run: an httpx.AsyncClient created outside the loop
    that uses it tears down its pool against a closed loop between batches.
    """
    async def run_all() -> dict[str, str]:
        client = _client(model)
        usage = Usage()
        out: dict[str, str] = {}
        batch: list[str] = []
        size = 0

        async def flush() -> None:
            nonlocal batch, size
            if not batch:
                return
            out.update(await _translate_batch(client, batch, usage))
            batch, size = [], 0

        for text in texts:
            if size + len(text) > BATCH_CHARS:
                await flush()
            batch.append(text)
            size += len(text)
        await flush()
        print(f"  translated {len(out)}/{len(texts)} text(s), "
              f"{usage.input_tokens} in / {usage.output_tokens} out")
        return out

    return asyncio.run(run_all())


def build(limit: int | None = None, model: str | None = None) -> dict[str, Any]:
    """Translate everything the drafts need that is not cached yet."""
    if not DRAFTS.is_file():
        raise SystemExit(f"STOP: {S.rel(DRAFTS)} not found; run annotation.draft_claims first.")
    model = S.require_annotation_model(model or review_model(), "REVIEW_MODEL")
    cases = [json.loads(line) for line in DRAFTS.read_text(encoding="utf-8").splitlines()
             if line.strip()]
    if limit:
        cases = cases[:limit]
    cache = load_cache()

    needed: dict[str, str] = {}  # key -> english
    for case in cases:
        texts = [case["generated_answer"], *(case["context_passages"] or [])]
        texts += [claim.get("claim_text", "") for claim in case.get("claims") or []]
        for text in texts:
            if text.strip():
                needed.setdefault(text_key(text), text)
    missing = {k: v for k, v in needed.items() if k not in cache}
    print(f"zh: {len(needed)} text(s) needed, {len(needed) - len(missing)} cached, "
          f"{len(missing)} to translate with {model}")
    if missing:
        translated = translate_texts(list(missing.values()), model)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for key, zh in translated.items():
            cache[key] = {"zh": zh, "model": model, "translated_at": now,
                          "source_chars": len(missing.get(key, ""))}
        save_cache(cache)
    return cache


def status() -> None:
    if not DRAFTS.is_file():
        print(f"no drafts at {S.rel(DRAFTS)}")
        return
    cache = load_cache()
    cases = [json.loads(line) for line in DRAFTS.read_text(encoding="utf-8").splitlines()
             if line.strip()]
    needed = {text_key(t) for c in cases
              for t in [c["generated_answer"], *(c["context_passages"] or []),
                        *[cl.get("claim_text", "") for cl in c.get("claims") or []]]
              if t.strip()}
    have = len(needed & set(cache))
    print(f"zh cache: {S.rel(CACHE)}")
    print(f"  texts needed: {len(needed)}   translated: {have}   missing: {len(needed) - have}")
    if cache:
        models = sorted({v.get("model", "?") for v in cache.values()})
        print(f"  models: {', '.join(models)}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Chinese display layer for the review page")
    ap.add_argument("--build", action="store_true", help="translate what is missing")
    ap.add_argument("--status", action="store_true", help="show cache coverage")
    ap.add_argument("--limit", type=int, help="only the first N draft cases")
    ap.add_argument("--model", help="override REVIEW_MODEL for this run")
    args = ap.parse_args()
    if args.status or not args.build:
        status()
        return
    build(args.limit, args.model)
    status()


if __name__ == "__main__":
    main()
