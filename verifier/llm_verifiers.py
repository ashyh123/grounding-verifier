"""Approach 2 (MinimalVerifier) and approach 3 (OptimizedVerifier)."""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from . import prompts
from .llm import LLMClient, Usage
from .schemas import Claim, Meta, VerifyRequest, VerifyResponse
from .segment import render_numbered, split_passages
from .validate import DraftClaim, EnforceStats, RawCitation, finalize_claim, resolve_all

MAX_CONCURRENCY = 5
MAX_REPAIR_RETRIES = 2


def _meta(name: str, model: str, t0: float, usage: Usage, stats: EnforceStats,
          downgraded: int, prompt_version: str | None = None) -> Meta:
    return Meta(method=name, model=model, latency_ms=(time.perf_counter() - t0) * 1000,
                llm_calls=usage.calls, input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens, retries=usage.retries,
                raw_citations_total=stats.raw_total, raw_citations_invalid=stats.raw_invalid,
                downgraded_claims=downgraded, warnings=stats.warnings,
                prompt_version=prompt_version)


def _passages_block(passages: list[str]) -> str:
    return "\n".join(f"<passage index={i}>\n{p}\n</passage>" for i, p in enumerate(passages))


def _as_str(x: Any) -> str:
    return x if isinstance(x, str) else ""


class MinimalVerifier:
    """One call, minimal prompt. Output still goes through the deterministic validator."""
    name = "minimal"

    def __init__(self, llm: LLMClient):
        self.llm = llm

    async def verify(self, req: VerifyRequest) -> VerifyResponse:
        user = (f"Passages:\n{_passages_block(req.context_passages)}\n\n"
                f"Answer:\n{req.generated_answer}")
        return await self._run(req.context_passages, user)

    async def verify_claims(self, passages: list[str], claims: list[str]) -> VerifyResponse:
        user = (f"Passages:\n{_passages_block(passages)}\n\n"
                "The answer is already split into claims. Keep exactly these claims, in this order:\n"
                + json.dumps(claims, ensure_ascii=False))
        return await self._run(passages, user)

    async def _run(self, passages: list[str], user: str) -> VerifyResponse:
        t0, usage, stats = time.perf_counter(), Usage(), EnforceStats()
        data = await self.llm.call_tool(prompts.MINIMAL_SYSTEM_V1,
                                        [{"role": "user", "content": user}],
                                        "report", prompts.MINIMAL_SCHEMA, usage)
        claims: list[Claim] = []
        downgraded = 0
        for item in data.get("claims") or []:
            if not isinstance(item, dict) or not _as_str(item.get("claim_text")).strip():
                stats.warnings.append("dropped malformed claim object")
                continue
            raws = [RawCitation(index=c.get("index") if isinstance(c.get("index"), int) else None,
                                quote=_as_str(c.get("quote")))
                    for c in (item.get("citations") or []) if isinstance(c, dict)]
            d = DraftClaim(item["claim_text"], _as_str(item.get("verdict")),
                           _as_str(item.get("reasoning")), raws)
            c = finalize_claim(d, resolve_all(passages, d, stats), stats)
            downgraded += int(c.verdict.value != d.verdict.strip().upper())
            claims.append(c)
        return VerifyResponse(claims=claims,
                              meta=_meta(self.name, self.llm.model, t0, usage, stats, downgraded))


class OptimizedVerifier:
    """decompose -> verify each claim in parallel -> validate -> retry with feedback -> finalize."""
    name = "optimized"

    def __init__(self, llm: LLMClient, prompt_version: str | None = None):
        self.llm = llm
        self.prompts = prompts.get_prompt_set(prompt_version)

    async def verify(self, req: VerifyRequest) -> VerifyResponse:
        t0, usage = time.perf_counter(), Usage()
        if not req.generated_answer.strip():
            return VerifyResponse(claims=[], meta=self._meta(t0, usage, EnforceStats(), 0))
        claims = await self.decompose(req.generated_answer, usage)
        return await self._verify_list(req.context_passages, claims, usage, t0)

    async def verify_claims(self, passages: list[str], claims: list[str]) -> VerifyResponse:
        return await self._verify_list(passages, claims, Usage(), time.perf_counter())

    async def decompose(self, answer: str, usage: Usage) -> list[str]:
        data = await self.llm.call_tool(self.prompts.decompose,
                                        [{"role": "user", "content": f"Answer:\n{answer}"}],
                                        "claims", self.prompts.decompose_schema, usage)
        out = [c.strip() for c in (data.get("claims") or []) if isinstance(c, str) and c.strip()]
        return list(dict.fromkeys(out))  # dedupe, keep order

    def _meta(self, t0: float, usage: Usage, stats: EnforceStats, downgraded: int) -> Meta:
        return _meta(self.name, self.llm.model, t0, usage, stats, downgraded, self.prompts.version)

    async def _verify_list(self, passages, claims, usage, t0) -> VerifyResponse:
        stats = EnforceStats()
        if not passages:  # nothing can be grounded; skip LLM calls
            result = [finalize_claim(DraftClaim(c, "UNSUPPORTED",
                                                "No context passages were provided."), [], stats)
                      for c in claims]
            return VerifyResponse(claims=result, meta=self._meta(t0, usage, stats, 0))
        numbered = render_numbered(passages)
        valid_ids = [s.sid for s in split_passages(passages)]
        sem = asyncio.Semaphore(MAX_CONCURRENCY)

        async def one(text: str) -> tuple[Claim, bool]:
            async with sem:
                return await self._verify_one(passages, numbered, valid_ids, text, usage, stats)

        pairs = await asyncio.gather(*(one(c) for c in claims))
        return VerifyResponse(claims=[c for c, _ in pairs],
                              meta=self._meta(t0, usage, stats, sum(d for _, d in pairs)))

    async def _verify_one(self, passages, numbered, valid_ids, text, usage, stats):
        messages: list[dict[str, Any]] = [{"role": "user", "content":
                                           prompts.VERIFY_USER_TEMPLATE.format(
                                               numbered_sources=numbered, claim=text)}]
        draft: DraftClaim | None = None
        cits = []
        for attempt in range(MAX_REPAIR_RETRIES + 1):
            data = await self.llm.call_tool(self.prompts.verify, messages, "verdict",
                                            prompts.VERIFY_SCHEMA, usage)
            raws = [RawCitation(sentence_id=_as_str(e.get("sentence_id")) or None,
                                quote=_as_str(e.get("quote")) or None)
                    for e in (data.get("evidence") or []) if isinstance(e, dict)]
            verdict = _as_str(data.get("verdict")).strip().upper()
            draft = DraftClaim(text, verdict, _as_str(data.get("reasoning")), raws)
            attempt_stats = EnforceStats()
            cits = resolve_all(passages, draft, attempt_stats)
            stats.raw_total += attempt_stats.raw_total
            stats.raw_invalid += attempt_stats.raw_invalid

            problem = None
            if verdict not in ("SUPPORTED", "CONTRADICTED", "UNSUPPORTED"):
                problem = f"verdict {verdict!r} is not one of the allowed values"
            elif verdict != "UNSUPPORTED" and not cits:
                problem = (f"verdict is {verdict} but none of the cited sentence IDs "
                           f"{[r.sentence_id for r in raws]} exist")
            if problem is None:
                break
            usage.retries += 1
            messages = messages[:1] + [
                {"role": "assistant", "content": json.dumps(data)},
                {"role": "user", "content": prompts.RETRY_FEEDBACK.format(
                    problem=problem, valid_ids=", ".join(valid_ids))},
            ]
        assert draft is not None
        claim = finalize_claim(draft, cits, stats)
        return claim, claim.verdict.value != draft.verdict
