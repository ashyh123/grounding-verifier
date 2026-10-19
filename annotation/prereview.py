"""Model pre-review: a second opinion you can accept with one click, never a decision.

    uv run python -m annotation.prereview --build             # suggest for every draft claim
    uv run python -m annotation.prereview --build --only c1 c2
    uv run python -m annotation.prereview --status

This is deliberately *not* an auto-labeller:

* suggestions live in `data/annotation/prereview.json`, keyed by claim id, and never touch
  `drafts.jsonl` or `decisions_round*.jsonl`;
* the review page shows them beside the draft and offers "采纳建议" (accept), which still writes an
  ordinary decision line — a human action with a timestamp, not a model action;
* the model is told to answer UNSUPPORTED when unsure, and evidence it proposes is re-validated
  against the passage text exactly like a human selection (a non-verbatim quote is dropped, and the
  suggestion loses its accept button for that claim);
* the model is a *different* model from the one under test (`VERIFIER_MODEL`) and from the drafter
  (`ANNOTATION_MODEL`); `prereview` refuses otherwise.

Why it exists: the human is still the annotator, but reviewing ~380 claims one by one is the
bottleneck. A pre-review that agrees with the draft most of the time turns that into confirming a
proposal, and the ones it disagrees with are exactly the cases worth reading closely. The
disagreement rate is written to the report so the help is measured, not assumed.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from verifier import config
from verifier.llm import Usage

from . import prompts, sources as S
from .zh import _client, review_model

DRAFTS = S.ANNOTATION_DIR / "drafts.jsonl"
OUT = S.ANNOTATION_DIR / "prereview.json"

SYSTEM = """You are a second reviewer for a citation-grounding benchmark. You do not decide
anything: a human reads your proposal and accepts or overrides it.

You are given numbered source passages, an answer written from them, and a draft claim with a draft
verdict. Decide whether the passages SUPPORT the claim, CONTRADICT it, or say nothing about it
(UNSUPPORTED).

Rules:
- Read the passages literally. Do not use outside knowledge, and do not reason about whether the
  claim is true in the real world.
- SUPPORTED: the passages state it or directly entail it, and nothing conflicts.
- CONTRADICTED: the passages state something incompatible with it — a different number, unit, date,
  entity, direction of comparison, or negation. One incompatible part decides the whole claim.
- UNSUPPORTED: the passages are silent about it, or about part of it, and nothing conflicts. If you
  are unsure between UNSUPPORTED and CONTRADICTED, answer UNSUPPORTED.
- Quote evidence only from the passages, copied character for character. No paraphrase, no ellipsis.
  Give no evidence for UNSUPPORTED.
- If the draft verdict looks right, say so; do not change it just to differ.

Answer in the tool call. `confidence` is your own 0-1 estimate that a careful human would agree
with you; use below 0.5 when the claim sits on a boundary."""

TOOL = "submit_review"
SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["SUPPORTED", "CONTRADICTED", "UNSUPPORTED"]},
        "confidence": {"type": "number"},
        "reasoning_zh": {"type": "string", "description": "one or two sentences, in Chinese"},
        "evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"index": {"type": "integer"}, "quote": {"type": "string"}},
                "required": ["index", "quote"],
            },
        },
    },
    "required": ["verdict", "confidence", "reasoning_zh"],
}


def check_models() -> str:
    """Refuse to pre-review with the model under test or with the drafting model."""
    model = review_model()
    under_test = config.optional_env("VERIFIER_MODEL")
    drafter = config.optional_env("ANNOTATION_MODEL")
    if under_test and model == under_test:
        raise SystemExit(f"STOP: REVIEW_MODEL={model!r} is the model under test (VERIFIER_MODEL). "
                         f"A pre-review by the system being measured is not a second opinion.")
    if drafter and model == drafter:
        raise SystemExit(f"STOP: REVIEW_MODEL={model!r} equals ANNOTATION_MODEL. The pre-review is "
                         f"only useful from a model that did not write the draft.")
    return model


def load() -> dict[str, dict[str, Any]]:
    if not OUT.is_file():
        return {}
    return json.loads(OUT.read_text(encoding="utf-8"))


def save(records: dict[str, dict[str, Any]]) -> None:
    OUT.write_text(json.dumps(records, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")


def case_prompt(case: dict[str, Any], claim: dict[str, Any]) -> str:
    """Passages + answer + the one claim under review."""
    parts = [prompts.render_passages(case["context_passages"]), "---", "Answer:",
             case["generated_answer"], "---", "Claim under review:",
             json.dumps({"claim_text": claim["claim_text"],
                         "draft_verdict": claim.get("draft_verdict"),
                         "draft_reasoning": claim.get("reasoning", "")},
                        ensure_ascii=False, indent=1)]
    labels = case.get("source_labels", {}).get("labels") or []
    if labels:
        parts += ["---", "Upstream annotation of the answer (for context):",
                  json.dumps(labels, ensure_ascii=False)]
    return "\n".join(parts)


def validate_evidence(passages: list[str], raw: list[dict[str, Any]]) -> tuple[list[dict], bool]:
    """Re-derive every proposed quote from the passage text. Returns (evidence, all_located)."""
    out: list[dict] = []
    all_ok = True
    for item in raw or []:
        index, quote = item.get("index"), (item.get("quote") or "")
        if not isinstance(index, int) or not 0 <= index < len(passages) or not quote.strip():
            all_ok = False
            continue
        start = passages[index].find(quote)
        if start < 0:
            all_ok = False
            continue
        end = start + len(quote)
        out.append({"index": index, "start_char": start, "end_char": end,
                    "quote": quote})
    return out, all_ok


async def review_claim(case: dict[str, Any], claim: dict[str, Any], client,
                       usage: Usage) -> dict[str, Any]:
    data = await client.call_tool(
        system=SYSTEM, messages=[{"role": "user", "content": case_prompt(case, claim)}],
        tool_name=TOOL, tool_schema=SCHEMA, usage=usage)
    verdict = (data.get("verdict") or "").upper()
    if verdict not in S.VERDICTS:
        verdict = "UNSUPPORTED"
    evidence, located = validate_evidence(case["context_passages"], data.get("evidence"))
    if verdict == "UNSUPPORTED":
        evidence, located = [], True
    try:
        confidence = max(0.0, min(1.0, float(data.get("confidence", 0.5))))
    except (TypeError, ValueError):
        confidence = 0.5
    draft = S.normalize_verdict(claim.get("draft_verdict"))
    return {
        "claim_id": claim["claim_id"],
        "case_id": case["id"],
        "verdict": verdict,
        "confidence": round(confidence, 2),
        "agrees_with_draft": verdict == draft,
        "reasoning_zh": (data.get("reasoning_zh") or "").strip(),
        "evidence": evidence,
        "evidence_verbatim": located,
        # accept is offered only when the suggestion is usable as-is
        "acceptable": verdict == "UNSUPPORTED" or bool(evidence),
        "model": client.model,
        "reviewed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


async def run(claims: list[tuple[dict, dict]], model: str, concurrency: int) -> list[dict]:
    model = S.require_annotation_model(model, "REVIEW_MODEL")
    client = _client(model)
    usage = Usage()
    sem = asyncio.Semaphore(concurrency)
    out: list[dict] = []

    async def one(case: dict, claim: dict) -> None:
        async with sem:
            try:
                out.append(await review_claim(case, claim, client, usage))
                print(f"  [ok  ] {claim['claim_id']}")
            except Exception as e:  # a failed suggestion is reported, never invented
                print(f"  [FAIL] {claim['claim_id']}: {type(e).__name__}: {e}")

    await asyncio.gather(*(one(c, cl) for c, cl in claims))
    print(f"pre-review: {len(out)} claim(s), {usage.input_tokens} in / {usage.output_tokens} out")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Model pre-review suggestions for the review page")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--only", nargs="*", help="claim ids to review")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--redo", action="store_true", help="re-review claims that already have one")
    ap.add_argument("--concurrency", type=int, default=4)
    args = ap.parse_args()

    if not DRAFTS.is_file():
        raise SystemExit(f"STOP: {S.rel(DRAFTS)} not found; run annotation.draft_claims first.")
    cases = [json.loads(line) for line in DRAFTS.read_text(encoding="utf-8").splitlines()
             if line.strip()]
    existing = load()

    if args.status or not args.build:
        total = sum(len(c.get("claims") or []) for c in cases)
        print(f"pre-review: {S.rel(OUT)}")
        print(f"  claims: {total}   reviewed: {len(existing)}   missing: {total - len(existing)}")
        if existing:
            agree = sum(1 for r in existing.values() if r.get("agrees_with_draft"))
            print(f"  agrees with draft: {agree}/{len(existing)} "
                  f"({agree / len(existing):.0%})")
            print(f"  models: {', '.join(sorted({r.get('model', '?') for r in existing.values()}))}")
        return

    wanted = set(args.only or [])
    claims: list[tuple[dict, dict]] = []
    for case in cases:
        for claim in case.get("claims") or []:
            if wanted and claim["claim_id"] not in wanted:
                continue
            if claim["claim_id"] in existing and not args.redo:
                continue
            claims.append((case, claim))
    if args.limit:
        claims = claims[:args.limit]
    if not claims:
        print("nothing to do: every claim already has a suggestion")
        return

    model = check_models()
    print(f"pre-reviewing {len(claims)} claim(s) with REVIEW_MODEL={model}")
    reviewed = asyncio.run(run(claims, model, args.concurrency))
    existing.update({r["claim_id"]: r for r in reviewed})
    save(existing)
    agree = sum(1 for r in reviewed if r["agrees_with_draft"])
    print(f"suggestions -> {S.rel(OUT)}")
    print(f"agrees with the draft: {agree}/{len(reviewed)} ({agree / max(len(reviewed), 1):.0%})")
    print("Open the review page: suggestions appear beside each claim, with 采纳建议.")


if __name__ == "__main__":
    main()
