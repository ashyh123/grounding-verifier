"""Design v2.2: upstream human labels + blind review, or human adjudication.

A: upstream and blind verdict agree, no flags, exact evidence when required.
B: disagreement, flags, missing verdict or missing exact evidence.
C: seeded 15% audit of A (rounded up). Each split also gets two whole-case checks.
No drafting verdict or model confidence can qualify a claim for A.
"""
from __future__ import annotations

import argparse
import json
import math
import random
from collections import Counter, defaultdict
from typing import Any

from . import sources as S

DRAFTS = S.ANNOTATION_DIR / "drafts.jsonl"
BLIND_REVIEW = S.ANNOTATION_DIR / "blind_review.json"
OUT = S.ANNOTATION_DIR / "triage.json"
SEED = 20261019
AUDIT_RATE = 0.15
LABEL_SOURCES = {"A": "ragtruth_human+model_blind_agree",
                 "B": "human_adjudicated", "C": "human_audit"}


def load(path, default):
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def reasons_for(claim: dict[str, Any], case: dict[str, Any],
                review: dict[str, Any] | None) -> list[str]:
    reasons: list[str] = []
    if case.get("provenance", {}).get("dataset") != "RAGTruth":
        reasons.append("not_ragtruth")
    upstream = claim.get("upstream_verdict")
    blind = (review or {}).get("blind_verdict")
    if upstream not in S.VERDICTS:
        reasons.append("missing_upstream_verdict")
    if blind not in S.VERDICTS:
        reasons.append("missing_blind_review")
    elif upstream != blind:
        reasons.append("upstream_blind_disagree")
    for flag in [*(case.get("flags") or []), *(claim.get("flags") or [])]:
        reasons.append(flag.get("flag", "flagged") if isinstance(flag, dict) else str(flag))
    evidence = (review or {}).get("evidence_candidates") or []
    exact = False
    passages = case["context_passages"]
    for item in evidence:
        index, quote = item.get("index"), item.get("quote")
        start, end = item.get("start_char"), item.get("end_char")
        valid = (item.get("match") == "exact" and type(index) is int
                 and 0 <= index < len(passages) and isinstance(quote, str) and bool(quote.strip())
                 and type(start) is int and type(end) is int
                 and 0 <= start < end <= len(passages[index])
                 and passages[index][start:end] == quote)
        if valid:
            exact = True
        else:
            reasons.append("evidence_not_exact")
    if blind in ("SUPPORTED", "CONTRADICTED") and not exact:
        reasons.append("no_exact_evidence")
    return sorted(set(reasons))


def plan(drafts: list[dict], blind_review: dict[str, dict]) -> dict:
    claims: list[dict[str, Any]] = []
    for case in sorted(drafts, key=lambda c: c["id"]):
        task = case.get("provenance", {}).get("task_type") or case["source"]
        for claim in sorted(case.get("claims") or [], key=lambda c: c["claim_id"]):
            review = blind_review.get(claim["claim_id"])
            reasons = reasons_for(claim, case, review)
            bucket = "B" if reasons else "A"
            claims.append({
                "claim_id": claim["claim_id"], "case_id": case["id"], "task": task,
                "source": case["source"], "split": case["split"],
                "upstream_verdict": claim.get("upstream_verdict"),
                "blind_verdict": (review or {}).get("blind_verdict"),
                "bucket": bucket, "label_source": LABEL_SOURCES[bucket], "reasons": reasons,
            })
    candidates = [c for c in claims if c["bucket"] == "A"]
    for claim in random.Random(SEED).sample(candidates, math.ceil(len(candidates) * AUDIT_RATE)):
        claim.update(bucket="C", label_source=LABEL_SOURCES["C"], reasons=["random_audit_sample"])

    whole_case_checks = []
    for split in ("dev", "test"):
        cases = sorted((c for c in drafts if c["split"] == split), key=lambda c: c["id"])
        whole_case_checks.extend({"case_id": c["id"], "split": split,
                                  "reason": "whole_case_decomposition_check"}
                                 for c in random.Random(SEED).sample(cases, min(2, len(cases))))
    counts = Counter(c["bucket"] for c in claims)
    tasks: dict[str, Counter] = defaultdict(Counter)
    reasons = Counter()
    task_reasons: dict[str, Counter] = defaultdict(Counter)
    for claim in claims:
        tasks[claim["task"]][claim["bucket"]] += 1
        reasons.update(claim["reasons"])
        task_reasons[claim["task"]].update(claim["reasons"])
    return {
        "design_version": "2.2", "seed": SEED, "audit_rate": AUDIT_RATE,
        "audit_rounding": "ceil", "audit_population": len(candidates),
        "total": len(claims), "counts": {b: counts[b] for b in LABEL_SOURCES},
        "by_task": {task: dict(n) for task, n in sorted(tasks.items())},
        "reasons": dict(reasons),
        "by_task_reason": {task: dict(n) for task, n in sorted(task_reasons.items())},
        "whole_case_checks": whole_case_checks,
        "whole_case_shortfalls": {s: max(0, 2 - sum(c["split"] == s for c in whole_case_checks))
                                   for s in ("dev", "test")},
        "claims": claims,
    }


def by_case(triage: dict) -> dict[str, list[str]]:
    """B/C claim queue; whole-case checks are separate review tasks."""
    out: dict[str, list[str]] = defaultdict(list)
    for claim in triage.get("claims", []):
        if claim["bucket"] in ("B", "C"):
            out[claim["case_id"]].append(claim["claim_id"])
    return dict(out)


def main() -> None:
    ap = argparse.ArgumentParser(description="v2.2 A/B/C triage and whole-case checks")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()
    if args.status:
        triage = load(OUT, None)
        if triage is None:
            raise SystemExit(f"STOP: no plan at {S.rel(OUT)}.")
    else:
        if not DRAFTS.is_file():
            raise SystemExit(f"STOP: {S.rel(DRAFTS)} not found; no valid drafts yet.")
        triage = plan(S.read_jsonl(DRAFTS), load(BLIND_REVIEW, {}))
        OUT.write_text(json.dumps(triage, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"claims: {triage['total']}; buckets: {triage['counts']}")
    print(f"by task: {triage['by_task']}")
    print(f"by reason: {triage['reasons']}")
    print(f"by task/reason: {triage['by_task_reason']}")
    print(f"whole-case checks: {triage['whole_case_checks']}")
    print(f"plan -> {S.rel(OUT)}")


if __name__ == "__main__":
    main()
