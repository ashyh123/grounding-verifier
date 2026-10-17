"""Non-LLM baseline: sentence split + BM25 retrieval + lexical heuristics."""
from __future__ import annotations

import re
import time

from rank_bm25 import BM25Okapi

from .schemas import Claim, Meta, VerifyRequest, VerifyResponse
from .segment import split_answer, split_passages
from .validate import DraftClaim, EnforceStats, RawCitation, finalize_claim, resolve_all

SUPPORT_THRESHOLD = 0.6  # fraction of claim content words found in the best sentence
STOPWORDS = set("""a an the of to in on for and or is are was were be been by with as at it its
this that these those from which when while than then into over via can may will
not no does do""".split())
NEGATIONS = {"not", "no", "never", "cannot", "can't", "doesn't", "don't", "isn't", "without"}
_TOKEN = re.compile(r"[a-z0-9][a-z0-9\-\.']*[a-z0-9]|[a-z0-9]")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def _content(tokens: list[str]) -> set[str]:
    return {t for t in tokens if t not in STOPWORDS and t not in NEGATIONS}


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in _NUMBER.findall(text)}


class BaselineVerifier:
    name = "baseline"

    async def verify(self, req: VerifyRequest) -> VerifyResponse:
        t0 = time.perf_counter()
        claims_text = split_answer(req.generated_answer)
        return self._run(req.context_passages, claims_text, t0)

    async def verify_claims(self, passages: list[str], claims: list[str]) -> VerifyResponse:
        return self._run(passages, claims, time.perf_counter())

    def _run(self, passages: list[str], claims_text: list[str], t0: float) -> VerifyResponse:
        sentences = split_passages(passages)
        stats = EnforceStats()
        bm25 = BM25Okapi([_tokens(s.text) for s in sentences]) if sentences else None
        out: list[Claim] = []
        for text in claims_text:
            out.append(self._judge(passages, sentences, bm25, text, stats))
        meta = Meta(method=self.name, latency_ms=(time.perf_counter() - t0) * 1000,
                    raw_citations_total=stats.raw_total,
                    raw_citations_invalid=stats.raw_invalid, warnings=stats.warnings)
        return VerifyResponse(claims=out, meta=meta)

    def _judge(self, passages, sentences, bm25, text, stats) -> Claim:
        if bm25 is None:
            d = DraftClaim(text, "UNSUPPORTED", "No context passages were provided.")
            return finalize_claim(d, [], stats)
        q = _tokens(text)
        scores = bm25.get_scores(q)
        best = max(range(len(sentences)), key=lambda i: scores[i])
        sent = sentences[best]
        s_tokens = _tokens(sent.text)
        claim_content = _content(q)
        overlap = len(claim_content & set(s_tokens)) / max(1, len(claim_content))

        if overlap < SUPPORT_THRESHOLD:
            d = DraftClaim(text, "UNSUPPORTED",
                           f"Best matching sentence {sent.sid} covers only {overlap:.0%} of the claim's content words.")
            return finalize_claim(d, [], stats)

        cnum, snum = _numbers(text), _numbers(sent.text)
        neg_mismatch = bool(NEGATIONS & set(q)) != bool(NEGATIONS & set(s_tokens))
        num_mismatch = bool(cnum and snum and not cnum <= snum)
        verdict = "CONTRADICTED" if (neg_mismatch or num_mismatch) else "SUPPORTED"
        why = (f"Lexical overlap {overlap:.0%} with {sent.sid}"
               + ("; negation mismatch" if neg_mismatch else "")
               + (f"; numbers {sorted(cnum)} vs {sorted(snum)}" if num_mismatch else ""))
        d = DraftClaim(text, verdict, why, [RawCitation(sentence_id=sent.sid)])
        return finalize_claim(d, resolve_all(passages, d, stats), stats)
