"""T6 — build the round-2 queue from the round-1 decisions.

    uv run python -m annotation.round2_queue

Selected for round 2 (spec T6), each with the reason recorded:

* round 1 changed the verdict, the claim text or the evidence;
* the final verdict disagrees with the upstream dataset annotation;
* the claim or its case carries a red or yellow flag;
* a 10% random sample (seed 20261019) of claims that were agreed to and carry no flag, as a check
  on round 1 itself.

Output: data/annotation/round2_queue.jsonl, one line per claim, in draft order.
"""
from __future__ import annotations

import json
import random
from collections import Counter
from typing import Any

from . import sources as S

SEED = 20261019
SAMPLE_RATE = 0.10
DRAFTS = S.ANNOTATION_DIR / "drafts.jsonl"
DECISIONS = S.ANNOTATION_DIR / "decisions_round1.jsonl"
QUEUE = S.ANNOTATION_DIR / "round2_queue.jsonl"

def upstream_verdict(claim: dict[str, Any]) -> str | None:
    """What the original dataset implies, mapped to our three labels (docs: design doc §5)."""
    if claim.get("upstream_label") in ("S", "NS"):
        return {"S": "SUPPORTED", "NS": "UNSUPPORTED"}[claim["upstream_label"]]
    overlaps = claim.get("overlapping_source_labels") or []
    if any("Conflict" in lab["label_type"] for lab in overlaps):
        return "CONTRADICTED"
    if any("Baseless" in lab["label_type"] for lab in overlaps):
        return "UNSUPPORTED"
    if claim.get("needs_full_review"):
        return None  # HaluEval: no claim-level ground truth to disagree with
    return "SUPPORTED"


def reasons_for(claim: dict[str, Any], case: dict[str, Any], decision: dict[str, Any],
                rng: random.Random) -> list[str]:
    reasons: list[str] = []
    draft_verdict = S.normalize_verdict(claim.get("draft_verdict"))
    final_verdict = S.normalize_verdict(decision.get("verdict"))
    if final_verdict and draft_verdict and final_verdict != draft_verdict:
        reasons.append("verdict_changed")
    if decision.get("claim_text") and decision["claim_text"].strip() != claim["claim_text"].strip():
        reasons.append("claim_text_changed")
    original_evidence = {(e.get("index"), e.get("start_char"), e.get("end_char"))
                         for e in claim.get("evidence") or []}
    final_evidence = {(e.get("index"), e.get("start_char"), e.get("end_char"))
                      for e in decision.get("evidence") or []}
    if original_evidence != final_evidence:
        reasons.append("evidence_changed")
    if decision.get("action") == "split":
        reasons.append("split")
    if decision.get("action") == "merge_previous":
        reasons.append("merged")
    up = upstream_verdict(claim)
    if up and final_verdict and up != final_verdict:
        reasons.append(f"disagrees_with_upstream({up}->{final_verdict})")
    if claim.get("flags"):
        reasons.append("flagged_claim")
    if case.get("flags"):
        reasons.append("flagged_case")
    if not reasons and decision.get("action") == "agree":
        if rng.random() < SAMPLE_RATE:
            reasons.append("random_10pct")
    return reasons


def main() -> None:
    for path in (DRAFTS, DECISIONS):
        if not path.is_file():
            raise SystemExit(f"STOP: {S.rel(path)} not found; finish round 1 first.")
    cases = [json.loads(line) for line in DRAFTS.read_text(encoding="utf-8").splitlines()
             if line.strip()]
    decisions: dict[str, dict[str, Any]] = {}
    for line in DECISIONS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            decisions[record["claim_id"]] = record  # last line wins

    rng = random.Random(SEED)
    queue: list[dict[str, Any]] = []
    unreviewed: list[str] = []
    counts: Counter[str] = Counter()
    for case in cases:
        for claim in case.get("claims") or []:
            decision = decisions.get(claim["claim_id"])
            if decision is None:
                unreviewed.append(claim["claim_id"])
                continue
            reasons = reasons_for(claim, case, decision, rng)
            if not reasons:
                continue
            for r in reasons:
                counts[r.split("(")[0]] += 1
            queue.append({
                "claim_id": claim["claim_id"], "case_id": case["id"], "source": case["source"],
                "reasons": reasons,
                "draft_verdict": claim.get("draft_verdict"),
                "round1_verdict": decision.get("verdict"),
                "upstream_verdict": upstream_verdict(claim),
            })

    S.write_jsonl(QUEUE, queue)
    print(f"round-1 decisions: {len(decisions)} claim(s); unreviewed: {len(unreviewed)}")
    if unreviewed:
        print(f"  NOTE: {len(unreviewed)} claim(s) have no round-1 decision and are not in the "
              f"queue: {unreviewed[:10]}{' ...' if len(unreviewed) > 10 else ''}")
    print(f"\nround-2 queue: {len(queue)} claim(s) -> {S.rel(QUEUE)}")
    print(f"\n{'reason':<38}count")
    print("-" * 48)
    for reason, n in counts.most_common():
        print(f"{reason:<38}{n}")
    sampled = counts.get("random_10pct", 0)
    agreed = sum(1 for d in decisions.values() if d.get("action") == "agree")
    if agreed:
        print(f"\nrandom audit sample: {sampled} of {agreed} agreed claim(s) "
              f"({sampled / agreed:.0%}; target {SAMPLE_RATE:.0%})")
    print("\nNext: uv run python -m annotation.review_app --round 2")


if __name__ == "__main__":
    main()
