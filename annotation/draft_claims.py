"""v2.2 RAGTruth drafting: context + complete answer, without upstream labels.

    uv run python -m annotation.draft_claims --split dev --only <five authorized ids>

The user selects model, endpoint and credentials. Answer quotes get exact offsets locally;
upstream verdicts are mapped only after the call. Checkpoints append without replacing prior
drafts. Legacy FActScore/HaluEval helpers remain available offline but cannot enter this round.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import anthropic
from pydantic import BaseModel, ConfigDict, Field

from verifier import config
from verifier.llm import LLMClient, Usage
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
    if not config.optional_env("ANTHROPIC_API_KEY"):
        raise SystemExit(
            "STOP: ANTHROPIC_API_KEY is empty in .env, and the drafting call goes to the "
            "Anthropic client (spec T0/T3).\nWithout it there is nothing to draft with.")
    base = config.optional_env("ANTHROPIC_BASE_URL")
    if not base:
        raise SystemExit("STOP: drafting requires an explicit ANTHROPIC_BASE_URL.")
    if base and "deepseek" in base.lower():
        raise SystemExit("STOP: annotation cannot use a DeepSeek endpoint (design v2.2).")


class AnswerQuote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quote: str = Field(min_length=1)


class AtomicDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim_text: str = Field(min_length=1)
    answer_spans: list[AnswerQuote] = Field(min_length=1)
    reasoning: str


class DraftOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claims: list[AtomicDraft]


class StructuredOutputError(ValueError):
    """Completed model response without the requested complete structured result."""

    def __init__(self, response):
        super().__init__('model response has no complete structured tool result')
        self.response = response.model_dump(mode='json')


class DraftClient:
    """Drafting credentials/parameters are independent of the verifier and other annotation roles.

    One request per case, with no automatic retries. A failed call is checkpointed and stops the
    run, so an ambiguous timeout cannot silently cause another paid annotation call.
    """

    parameters = {"max_tokens": 16384, "temperature": 0,
                  "thinking": {"type": "disabled"}, "tool_choice": {"type": "auto"}}

    def __init__(self, model: str):
        self.model = model
        self.response_model: str | None = None
        key = config.optional_env("ANTHROPIC_API_KEY")
        self._client = anthropic.AsyncAnthropic(
            api_key=key, base_url=config.optional_env("ANTHROPIC_BASE_URL"),
            default_headers={"api-key": key} if key else {},
            max_retries=0, timeout=180.0)

    async def call_tool(self, system, messages, tool_name, tool_schema, usage):
        usage.calls += 1
        response = await self._client.messages.create(
            model=self.model, system=system, messages=messages,
            tools=[{"name": tool_name, "description": "Return the requested structured result.",
                    "input_schema": tool_schema}],
            max_tokens=self.parameters["max_tokens"],
            tool_choice=self.parameters["tool_choice"],
            extra_body={"temperature": self.parameters["temperature"],
                        "thinking": self.parameters["thinking"]})
        self.response_model = response.model
        usage.input_tokens += (response.usage.input_tokens
                               + (getattr(response.usage, "cache_read_input_tokens", 0) or 0)
                               + (getattr(response.usage, "cache_creation_input_tokens", 0) or 0))
        usage.output_tokens += response.usage.output_tokens
        calls = [b for b in response.content if b.type == "tool_use"]
        if response.stop_reason != "tool_use" or len(calls) != 1 or calls[0].name != tool_name:
            raise StructuredOutputError(response)
        return calls[0].input

    async def close(self):
        await self._client.close()


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
        spans, flags = [], []
        for requested in claim.get("answer_spans", []):
            quote = requested.get("quote", "")
            start = answer.find(quote) if quote else -1
            unique = start >= 0 and answer.find(quote, start + 1) == -1
            spans.append({"quote": quote, "start": start if unique else None,
                          "end": start + len(quote) if unique else None,
                          "match": "exact" if unique else "candidate_only"})
        exact = [s for s in spans if s["match"] == "exact"]
        if not spans or len(exact) != len(spans):
            flags.append({"level": "red", "flag": "answer_span_not_exact",
                          "detail": "answer quotes must occur exactly once; no fuzzy offset accepted"})
        overlaps = [lab for lab in labels if any(
            lab["start"] < s["end"] and s["start"] < lab["end"] for s in exact)]
        upstream = (S.normalize_verdict(ragtruth_verdict(overlaps))
                    if spans and len(exact) == len(spans) else None)
        covered = {i for s in exact for i in range(s["start"], s["end"])}
        labelled = {i for lab in overlaps for i in range(lab["start"], lab["end"])}
        if overlaps and len(covered - labelled) > 20:
            flags.append({"level": "red", "flag": "partial_overlap",
                          "detail": f"{len(covered - labelled)} answer-span characters outside labelled fragments"})
        out.append({
            "claim_id": None, "claim_text": claim["claim_text"], "answer_spans": spans,
            "upstream_verdict": upstream, "flags": flags,
            "evidence": [], "overlapping_source_labels": overlaps,
            "reasoning": claim.get("reasoning", ""), "needs_full_review": False,
        })
    if answer_span_gaps({**case, "claims": out}):
        notes.append("answer_gap: more than 20 answer characters in an uncovered run")
    if any(not any(lab["start"] < s["end"] and s["start"] < lab["end"]
                   for c in out for s in c["answer_spans"] if s["match"] == "exact")
           for lab in labels):
        notes.append("source_label_uncovered: an upstream fragment overlaps no exact answer span")
    return out, notes


def answer_span_gaps(case: dict) -> list[dict]:
    """Report unlocated answer text; character coverage does not establish factual coverage."""
    answer = case["generated_answer"]
    covered = set()
    for claim in case["claims"]:
        for span in claim["answer_spans"]:
            start, end = span.get("start"), span.get("end")
            if (span.get("match") == "exact" and type(start) is int and type(end) is int
                    and 0 <= start < end <= len(answer) and answer[start:end] == span.get("quote")):
                covered.update(range(start, end))
    gaps, start = [], None
    for i in range(len(answer) + 1):
        if i < len(answer) and i not in covered:
            if start is None:
                start = i
        elif start is not None:
            quote = answer[start:i]
            if len(quote.strip()) > 20:
                gaps.append({"level": "yellow", "flag": "answer_gap", "start": start,
                             "end": i, "quote": quote,
                             "detail": f"回答定位覆盖缺口 [{start}:{i})：{quote!r}；需核查，不能据此判定漏事实。"})
            start = None
    return gaps


def case_diagnostics(case: dict, notes: list[str]) -> list[dict]:
    return ([{"level": "red", "flag": note.split(":", 1)[0], "detail": note}
             for note in notes if not note.startswith("answer_gap:")]
            + answer_span_gaps(case))


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
    started_at: str = ""
    finished_at: str = ""
    response_model: str | None = None


async def draft_case(case: dict[str, Any], client: LLMClient, usage: Usage) -> tuple[list[dict], list[str], dict]:
    """One drafting call for one case. Returns (claims, notes)."""
    family = prompts.family(case["source"])
    data = await client.call_tool(
        system=prompts.system_prompt(case), messages=[{"role": "user",
                                                      "content": prompts.user_prompt(case)}],
        tool_name=prompts.TOOL_NAME, tool_schema=prompts.tool_schema(case), usage=usage)
    if family == "ragtruth":
        data = DraftOutput.model_validate(data).model_dump()
    claims = data.get("claims")
    if not isinstance(claims, list):
        return [], [f"drafter returned no 'claims' array: {sorted(data)}"], data
    drafted, notes = DRAFTERS[family](case, claims)
    if family == "ragtruth" and not drafted:
        notes.append("drafter returned zero claims for this answer")
    for n, claim in enumerate(drafted, start=1):
        claim["claim_id"] = f"{case['id']}-c{n}"
    return drafted, notes, data


def case_record(case: dict[str, Any], claims: list[dict[str, Any]], stats: CallStats,
                model: str, raw_draft: dict | None = None) -> dict[str, Any]:
    """The draft case: the candidate plus claims plus the provenance of the drafting call."""
    return {
        "id": case["id"], "source": case["source"], "split": case["split"],
        "context_passages": case["context_passages"], "generated_answer": case["generated_answer"],
        "generator_model": case["generator_model"], "context_words": case["context_words"],
        "source_group_id": case["source_group_id"], "source_labels": case["source_labels"],
        "difficulty_tags": case["difficulty_tags"], "truncated": case["truncated"],
        "claims": claims,
        "raw_draft": raw_draft,
        "flags": case_diagnostics({**case, "claims": claims}, stats.errors),
        "provenance": {
            **case["provenance"],
            "annotation_origin": "llm_draft",
            "annotation_model": stats.response_model or model,
            "requested_annotation_model": model,
            "annotation_endpoint": config.optional_env("ANTHROPIC_BASE_URL"),
            "annotation_parameters": DraftClient.parameters,
            "prompt_sha256": prompts.prompt_hash(case),
            "draft_call": {
                "calls": stats.calls, "input_tokens": stats.input_tokens,
                "output_tokens": stats.output_tokens, "retries": stats.retries,
                "seconds": round(stats.seconds, 2),
                "started_at": stats.started_at, "finished_at": stats.finished_at,
            },
        },
        "selection": case["selection"],
    }


async def run(cases: list[dict[str, Any]], model: str, output: Path) -> list[dict[str, Any]]:
    client = DraftClient(model=model)
    out: list[dict[str, Any]] = []
    try:
        for case in cases:
            usage = Usage()
            client.response_model = None
            started = time.monotonic()
            stats = CallStats(started_at=datetime.now(timezone.utc).isoformat())
            raw = None
            failed = None
            try:
                claims, notes, raw = await draft_case(case, client, usage)
            except Exception as error:
                # Do not log provider exception bodies: they may contain authentication details.
                failed = type(error).__name__
                claims, notes = [], [f"draft_error: {failed}"]
            stats.calls, stats.input_tokens, stats.output_tokens = usage.calls, usage.input_tokens, usage.output_tokens
            stats.retries, stats.seconds = usage.retries, time.monotonic() - started
            stats.errors, stats.finished_at = notes, datetime.now(timezone.utc).isoformat()
            stats.response_model = client.response_model
            record = case_record(case, claims, stats, model, raw)
            if failed:
                record["draft_error"] = failed
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            out.append(record)
            print(f"  [{'FAIL' if failed else 'ok  '}] {case['id']}: {len(claims)} claims; "
                  f"{stats.input_tokens} in / {stats.output_tokens} out; {stats.seconds:.1f}s", flush=True)
            if failed:
                raise SystemExit(f"STOP: {case['id']} failed ({failed}); checkpoint saved, no retry.")
    finally:
        await client.close()
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="T3: draft claims for the sampled candidates")
    ap.add_argument("--only", nargs="*", help="case ids to draft")
    ap.add_argument("--limit", type=int, help="draft at most this many cases")
    ap.add_argument("--resume", action="store_true", help="skip cases that already have a draft")
    ap.add_argument("--split", choices=["dev", "test"])
    ap.add_argument("--candidates", type=Path, default=CANDIDATES)
    ap.add_argument("--out", type=Path, default=DRAFTS)
    args = ap.parse_args()

    if not args.candidates.is_file():
        raise SystemExit(f"STOP: {S.rel(CANDIDATES)} not found; "
                         f"run annotation.select_cases first.")
    cases = [json.loads(line) for line in args.candidates.read_text(encoding="utf-8").splitlines()
             if line.strip()]
    existing: dict[str, dict] = {}
    if args.out.is_file():
        existing = {r["id"]: r for r in
                    (json.loads(line) for line in args.out.read_text(encoding="utf-8").splitlines()
                     if line.strip())}

    selected = cases
    if args.only:
        wanted = set(args.only)
        selected = [c for c in cases if c["id"] in wanted]
        missing = wanted - {c["id"] for c in selected}
        if missing:
            raise SystemExit(f"STOP: unknown case id(s): {sorted(missing)}")
    if args.split:
        selected = [c for c in selected if c["split"] == args.split]
    selected = [c for c in selected if c["id"] not in existing]
    if args.limit:
        selected = selected[:args.limit]
    if not selected:
        print("nothing to do: every selected case already has a draft")
        return

    model = annotation_model()
    preflight()
    if any(not c["source"].startswith("ragtruth_") for c in selected):
        raise SystemExit("STOP: the v2.2 first round permits only RAGTruth.")
    print(f"drafting {len(selected)} case(s) with ANNOTATION_MODEL={model} "
          f"(model under test: {config.optional_env('VERIFIER_MODEL')})")
    drafted = asyncio.run(run(selected, model, args.out))

    merged: dict[str, dict] = dict(existing)
    for record in drafted:
        merged[record["id"]] = record
    ordered = [merged[c["id"]] for c in cases if c["id"] in merged]

    failed = [r["id"] for r in ordered if r.get("draft_error")]
    claims = sum(len(r["claims"]) for r in ordered)
    print(f"\ndrafts -> {S.rel(args.out)}: {len(ordered)} case(s), {claims} claim(s)")
    if failed:
        print(f"cases that failed and are recorded as such: {failed}")
    print("Drafting complete; blind-review and translation require separate user selection.")


if __name__ == "__main__":
    main()
