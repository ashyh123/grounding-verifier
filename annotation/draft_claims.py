"""T3 — draft claims for every candidate case with a model that is not the model under test.

    uv run python -m annotation.draft_claims                 # every case without a draft yet
    uv run python -m annotation.draft_claims --only ragtruth-3638 halueval-8027
    uv run python -m annotation.draft_claims --resume        # same as default; skips existing

One call per case, forced tool call, `ANNOTATION_MODEL` from the environment (never guessed: if it
is unset the run stops and says so). Drafts are written to data/annotation/drafts.jsonl and are
never sent to the model under test.

What the script decides itself, so the drafter cannot:

* RAGTruth: the verdict comes from overlap between the claim's answer span and the upstream
  hallucination spans — Conflict -> CONTRADICTED, Baseless -> UNSUPPORTED, otherwise
  SUPPORTED_CANDIDATE. The model's own verdict is kept next to it as `model_verdict`.
* FActScore: the claims are the human atomic facts (IR dropped) and their drafts are
  SUPPORTED_CANDIDATE (S) or NOT_SUPPORTED (NS); the model only suggests which NS facts are
  CONTRADICTED rather than merely unsupported, and supplies evidence.
* HaluEval: every label is a model suggestion and the case is marked `needs_full_review`.
* Evidence offsets are re-derived from the passage text with verifier.validate.find_span, and the
  match quality is recorded, so a quote that is not verbatim is visible instead of trusted.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

from verifier import config
from verifier.llm import AnthropicClient, LLMClient, Usage
from verifier.validate import find_span

from . import prompts, sources as S

CANDIDATES = S.ANNOTATION_DIR / "candidates.jsonl"
DRAFTS = S.ANNOTATION_DIR / "drafts.jsonl"

SUPPORTED_CANDIDATE = "SUPPORTED_CANDIDATE"
NOT_SUPPORTED = "NOT_SUPPORTED"


def annotation_model() -> str:
    """`ANNOTATION_MODEL` or a hard stop — the spec forbids guessing this name."""
    model = S.require_annotation_model(config.optional_env("ANNOTATION_MODEL"), "ANNOTATION_MODEL")
    under_test = config.optional_env("VERIFIER_MODEL")
    if under_test and model == under_test:
        raise SystemExit(
            f"STOP: ANNOTATION_MODEL={model!r} is the model under test (VERIFIER_MODEL).\n"
            "The spec requires a different model to draft the labels.")
    return model


def preflight() -> None:
    """Check the credentials the drafting path actually needs, before spending anything."""
    if not config.anthropic_api_key():
        raise SystemExit(
            "STOP: ANTHROPIC_API_KEY is empty in .env, and the drafting call goes to the "
            "Anthropic client (spec T0/T3).\nWithout it there is nothing to draft with.")
    base = config.optional_env("ANTHROPIC_BASE_URL")
    if base and "deepseek" in base.lower():
        raise SystemExit("STOP: annotation cannot use a DeepSeek endpoint (design v2.2).")
    fallback = config.optional_env("VERIFIER_BASE_URL") or ""
    if not base and fallback:
        raise SystemExit(
            f"STOP: ANTHROPIC_BASE_URL is unset, so AnthropicClient would fall back to "
            f"VERIFIER_BASE_URL={fallback!r},\nwhich is the model-under-test endpoint. Set "
            f"ANTHROPIC_BASE_URL (or leave both unset) before drafting.")
    if "deepseek" in fallback.lower() and not base:
        raise SystemExit("STOP: refusing to send drafting calls to the model-under-test endpoint.")


# --------------------------------------------------------------------------- evidence

def resolve_evidence(passages: list[str], raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Re-derive every evidence offset from the passage text; never trust the model's spans."""
    out: list[dict[str, Any]] = []
    for item in raw or []:
        index, quote = item.get("index"), (item.get("quote") or "")
        entry: dict[str, Any] = {"index": index, "requested_quote": quote, "quote": quote,
                                 "start_char": None, "end_char": None, "match": "unresolved",
                                 "located": False}
        if isinstance(index, int) and 0 <= index < len(passages) and quote.strip():
            hit = find_span(passages[index], quote)
            if hit is not None:
                start, end, how = hit
                entry.update({"quote": passages[index][start:end], "start_char": start,
                              "end_char": end, "match": how, "located": True})
        out.append(entry)
    return out


def resolve_answer_span(answer: str, claim_text: str,
                        model_span: dict[str, Any] | None) -> tuple[dict[str, int] | None, str]:
    """Return (span, how). The model's span is accepted only if the text under it matches."""
    if isinstance(model_span, dict) and isinstance(model_span.get("start"), int) \
            and isinstance(model_span.get("end"), int):
        start, end = model_span["start"], model_span["end"]
        if 0 <= start < end <= len(answer) and answer[start:end].strip() == claim_text.strip():
            return {"start": start, "end": end}, "exact"
    hit = find_span(answer, claim_text) if claim_text.strip() else None
    if hit is not None:
        return {"start": hit[0], "end": hit[1]}, hit[2]
    if isinstance(model_span, dict) and isinstance(model_span.get("start"), int) \
            and isinstance(model_span.get("end"), int):
        return {"start": model_span["start"], "end": model_span["end"]}, "model_only"
    return None, "missing"


# --------------------------------------------------------------------------- per-source labelling

def overlapping_labels(labels: list[dict[str, Any]], span: dict[str, int] | None) -> list[dict]:
    if span is None:
        return []
    return [lab for lab in labels if lab["start"] < span["end"] and span["start"] < lab["end"]]


def ragtruth_verdict(overlaps: list[dict[str, Any]]) -> str:
    """Script-side verdict from the upstream spans: conflict wins, then baseless, else candidate."""
    if any("Conflict" in lab["label_type"] for lab in overlaps):
        return "CONTRADICTED"
    if any("Baseless" in lab["label_type"] for lab in overlaps):
        return "UNSUPPORTED"
    return SUPPORTED_CANDIDATE


def draft_ragtruth(case: dict, claims: list[dict[str, Any]]) -> tuple[list[dict], list[str]]:
    labels = case["source_labels"].get("labels", [])
    answer = case["generated_answer"]
    out: list[dict[str, Any]] = []
    notes: list[str] = []
    for n, claim in enumerate(claims, start=1):
        span, how = resolve_answer_span(answer, claim.get("claim_text", ""),
                                        claim.get("answer_span"))
        if how == "model_only":
            notes.append(f"claim {n}: answer span does not match the claim text as given")
        overlaps = overlapping_labels(labels, span)
        evidence = resolve_evidence(case["context_passages"], claim.get("evidence"))
        draft = ragtruth_verdict(overlaps)
        if draft == "UNSUPPORTED":
            evidence = []  # the upstream says the answer is unsupported here: no evidence exists
        out.append({
            "claim_id": None, "claim_text": claim.get("claim_text", ""), "answer_span": span,
            "answer_span_match": how, "draft_verdict": draft,
            "model_verdict": (claim.get("verdict") or "").upper() or None,
            "evidence": evidence, "overlapping_source_labels": overlaps,
            "reasoning": claim.get("reasoning", ""), "needs_full_review": False,
        })
    return out, notes


def draft_factscore(case: dict, claims: list[dict[str, Any]]) -> tuple[list[dict], list[str]]:
    facts = [f for f in case["source_labels"].get("human_atomic_facts", []) if f.get("label") != "IR"]
    by_fact = {c["fact"]: c for c in claims if isinstance(c.get("fact"), int)}
    answer = case["generated_answer"]
    out: list[dict[str, Any]] = []
    notes: list[str] = []
    for n, fact in enumerate(facts):
        claim = by_fact.get(n, {})
        if n not in by_fact:
            notes.append(f"fact {n}: the drafter returned no entry for it")
        evidence = resolve_evidence(case["context_passages"], claim.get("evidence"))
        upstream = fact.get("label")
        if upstream == "S":
            draft, model_verdict = SUPPORTED_CANDIDATE, (claim.get("verdict") or "").upper() or None
        else:
            draft = NOT_SUPPORTED
            model_verdict = (claim.get("verdict") or "").upper() or None
            if model_verdict not in ("CONTRADICTED", "UNSUPPORTED"):
                model_verdict = None
            if model_verdict == "UNSUPPORTED":
                evidence = []
        span, how = resolve_answer_span(answer, fact["text"], None)
        # the human fact came from one of the answer's sentences; the span is a convenience for
        # the reviewer, so a miss is recorded rather than repaired
        out.append({
            "claim_id": None, "claim_text": fact["text"], "answer_span": span,
            "answer_span_match": how if span else "not_in_answer",
            "draft_verdict": draft, "upstream_label": upstream, "model_verdict": model_verdict,
            "evidence": evidence, "overlapping_source_labels": [],
            "reasoning": claim.get("reasoning", ""), "needs_full_review": False,
        })
    return out, notes


def draft_halueval(case: dict, claims: list[dict[str, Any]]) -> tuple[list[dict], list[str]]:
    answer = case["generated_answer"]
    out: list[dict[str, Any]] = []
    notes: list[str] = []
    for n, claim in enumerate(claims, start=1):
        span, how = resolve_answer_span(answer, claim.get("claim_text", ""),
                                        claim.get("answer_span"))
        verdict = (claim.get("verdict") or "").upper() or None
        evidence = resolve_evidence(case["context_passages"], claim.get("evidence"))
        if verdict == "UNSUPPORTED":
            evidence = []
        out.append({
            "claim_id": None, "claim_text": claim.get("claim_text", ""), "answer_span": span,
            "answer_span_match": how, "draft_verdict": verdict, "model_verdict": verdict,
            "tampered": bool(claim.get("tampered")), "evidence": evidence,
            "overlapping_source_labels": [], "reasoning": claim.get("reasoning", ""),
            "needs_full_review": True,  # this source has no claim-level ground truth
        })
    return out, notes


DRAFTERS = {"ragtruth": draft_ragtruth, "factscore": draft_factscore, "halueval": draft_halueval}


# --------------------------------------------------------------------------- one case

@dataclass
class CallStats:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    retries: int = 0
    errors: list[str] = field(default_factory=list)


async def draft_case(case: dict[str, Any], client: LLMClient, usage: Usage) -> tuple[list[dict], list[str]]:
    """One drafting call for one case. Returns (claims, notes)."""
    family = prompts.family(case["source"])
    data = await client.call_tool(
        system=prompts.system_prompt(case), messages=[{"role": "user",
                                                      "content": prompts.user_prompt(case)}],
        tool_name=prompts.TOOL_NAME, tool_schema=prompts.tool_schema(case), usage=usage)
    claims = data.get("claims")
    if not isinstance(claims, list):
        return [], [f"drafter returned no 'claims' array: {sorted(data)}"]
    drafted, notes = DRAFTERS[family](case, claims)
    if family == "ragtruth" and not drafted:
        notes.append("drafter returned zero claims for this answer")
    for n, claim in enumerate(drafted, start=1):
        claim["claim_id"] = f"{case['id']}-c{n}"
    return drafted, notes


def case_record(case: dict[str, Any], claims: list[dict[str, Any]], stats: CallStats,
                model: str) -> dict[str, Any]:
    """The draft case: the candidate plus claims plus the provenance of the drafting call."""
    return {
        "id": case["id"], "source": case["source"], "split": case["split"],
        "context_passages": case["context_passages"], "generated_answer": case["generated_answer"],
        "generator_model": case["generator_model"], "context_words": case["context_words"],
        "source_group_id": case["source_group_id"], "source_labels": case["source_labels"],
        "difficulty_tags": case["difficulty_tags"], "truncated": case["truncated"],
        "claims": claims,
        "provenance": {
            **case["provenance"],
            "annotation_origin": "llm_draft",
            "annotation_model": model,
            "prompt_sha256": prompts.prompt_hash(case),
            "draft_call": {
                "calls": stats.calls, "input_tokens": stats.input_tokens,
                "output_tokens": stats.output_tokens, "retries": stats.retries,
                "seconds": round(stats.seconds, 2),
            },
        },
        "selection": case["selection"],
    }


async def run(cases: list[dict[str, Any]], model: str, concurrency: int = 4) -> list[dict[str, Any]]:
    client = AnthropicClient(model=model)
    semaphore = asyncio.Semaphore(concurrency)
    out: list[dict[str, Any]] = []

    async def one(case: dict[str, Any]) -> None:
        usage = Usage()
        started = time.monotonic()
        async with semaphore:
            try:
                claims, notes = await draft_case(case, client, usage)
            except Exception as e:  # a failed case is reported, never silently dropped
                print(f"  [FAIL] {case['id']}: {type(e).__name__}: {e}")
                record = case_record(case, [], CallStats(errors=[f"{type(e).__name__}: {e}"]), model)
                record["draft_error"] = f"{type(e).__name__}: {e}"
                out.append(record)
                return
        stats = CallStats(calls=usage.calls, input_tokens=usage.input_tokens,
                          output_tokens=usage.output_tokens, retries=usage.retries,
                          seconds=time.monotonic() - started,
                          errors=list(notes))
        record = case_record(case, claims, stats, model)
        out.append(record)
        print(f"  [ok  ] {case['id']:<42} {len(claims):>2} claims  "
              f"{stats.input_tokens:>5} in / {stats.output_tokens:>4} out  "
              f"{stats.seconds:.1f}s" + (f"  notes={len(notes)}" if notes else ""))

    await asyncio.gather(*(one(c) for c in cases))
    return sorted(out, key=lambda r: [c["id"] for c in cases].index(r["id"]))


def main() -> None:
    ap = argparse.ArgumentParser(description="T3: draft claims for the sampled candidates")
    ap.add_argument("--only", nargs="*", help="case ids to draft")
    ap.add_argument("--limit", type=int, help="draft at most this many cases")
    ap.add_argument("--resume", action="store_true", help="skip cases that already have a draft")
    ap.add_argument("--concurrency", type=int, default=4)
    args = ap.parse_args()

    if not CANDIDATES.is_file():
        raise SystemExit(f"STOP: {S.rel(CANDIDATES)} not found; "
                         f"run annotation.select_cases first.")
    cases = [json.loads(line) for line in CANDIDATES.read_text(encoding="utf-8").splitlines()
             if line.strip()]
    existing: dict[str, dict] = {}
    if DRAFTS.is_file():
        existing = {r["id"]: r for r in
                    (json.loads(line) for line in DRAFTS.read_text(encoding="utf-8").splitlines()
                     if line.strip())}

    selected = cases
    if args.only:
        wanted = set(args.only)
        selected = [c for c in cases if c["id"] in wanted]
        missing = wanted - {c["id"] for c in selected}
        if missing:
            raise SystemExit(f"STOP: unknown case id(s): {sorted(missing)}")
    if args.resume or not args.only:
        selected = [c for c in selected if c["id"] not in existing]
    if args.limit:
        selected = selected[:args.limit]
    if not selected:
        print("nothing to do: every selected case already has a draft")
        return

    model = annotation_model()
    preflight()
    print(f"drafting {len(selected)} case(s) with ANNOTATION_MODEL={model} "
          f"(model under test: {config.optional_env('VERIFIER_MODEL')})")
    drafted = asyncio.run(run(selected, model, args.concurrency))

    merged: dict[str, dict] = dict(existing)
    for record in drafted:
        merged[record["id"]] = record
    ordered = [merged[c["id"]] for c in cases if c["id"] in merged]
    S.write_jsonl(DRAFTS, ordered)

    failed = [r["id"] for r in ordered if r.get("draft_error")]
    claims = sum(len(r["claims"]) for r in ordered)
    print(f"\ndrafts -> {S.rel(DRAFTS)}: {len(ordered)} case(s), {claims} claim(s)")
    if failed:
        print(f"cases that failed and are recorded as such: {failed}")
    print("Review 5 cases first (spec T3 acceptance) before drafting the rest:")
    print("  uv run python -m annotation.check_drafts && "
          "uv run python -m annotation.review_app --round 1")


if __name__ == "__main__":
    main()
