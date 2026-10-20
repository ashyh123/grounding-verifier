"""T7 — merge the two review rounds into `data/eval_hard.jsonl`, validate, and freeze.

    uv run python -m annotation.merge                 # refuses while anything is unreviewed
    uv run python -m annotation.merge --allow-partial # dev only, for the 5-case pilot

Round 2 wins where it exists, round 1 otherwise. Refuses to write while any claim of a case it is
about to emit has no decision, and lists the missing `claim_id`s instead of guessing. Also writes
`data/annotation/disagreements.jsonl` (final label vs upstream annotation) and
`data/annotation/audit.json` (how often round 2 overturned round 1 in the random sample).

Freezing records the sha256 of the output in `data/annotation/freeze.json`. Nothing here runs a
verifier: the hard test set is not shown to any method before the user freezes it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import sources as S

DRAFTS = S.ANNOTATION_DIR / "drafts.jsonl"
ROUND1 = S.ANNOTATION_DIR / "decisions_round1.jsonl"
ROUND2 = S.ANNOTATION_DIR / "decisions_round2.jsonl"
ROUND2_QUEUE = S.ANNOTATION_DIR / "round2_queue.jsonl"
OUT = S.ROOT / "data" / "eval_hard.jsonl"
DISAGREEMENTS = S.ANNOTATION_DIR / "disagreements.jsonl"
AUDIT = S.ANNOTATION_DIR / "audit.json"
FREEZE = S.ANNOTATION_DIR / "freeze.json"

VERDICTS = set(S.VERDICTS)
# A case is only emitted when its split is fully reviewed; --allow-partial exists for the pilot.
MIN_CASES_PER_SPLIT = 1


def load_decisions(path: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                out[record["claim_id"]] = record
    return out


def effective_decision(claim_id: str, r1: dict[str, dict], r2: dict[str, dict]) -> dict | None:
    return r2.get(claim_id) or r1.get(claim_id)


def case_claims(case: dict[str, Any], decisions: dict[str, dict[str, Any]]) -> tuple[list[dict], list[str]]:
    """(gold claims, unreviewed claim ids) for one case, with splits/merges/deletes applied."""
    gold: list[dict[str, Any]] = []
    unreviewed: list[str] = []
    for claim in case.get("claims") or []:
        decision = decisions.get(claim["claim_id"])
        if decision is None:
            unreviewed.append(claim["claim_id"])
            continue
        if decision["action"] == "delete":
            continue
        text = (decision.get("claim_text") or claim["claim_text"]).strip()
        verdict = S.normalize_verdict(decision.get("verdict"))
        if verdict not in VERDICTS:
            unreviewed.append(claim["claim_id"])
            continue
        evidence = [{"index": e["index"], "quote": e["quote"]}
                    for e in decision.get("evidence") or []]
        if verdict == "UNSUPPORTED":
            evidence = []
        if verdict != "UNSUPPORTED" and not evidence:
            unreviewed.append(claim["claim_id"])
            continue
        entry: dict[str, Any] = {"claim_text": text, "verdict": verdict, "evidence": evidence}
        if verdict != "UNSUPPORTED" and len({e["index"] for e in evidence}) >= 2:
            entry["tags"] = ["multi_passage"]
        gold.append(entry)
        for extra in decision.get("extra_claims") or []:
            if extra.strip():
                # a split creates a claim the reviewer typed; it inherits the verdict and the
                # evidence until the reviewer gives it its own decision
                gold.append({"claim_text": extra.strip(), "verdict": verdict,
                             "evidence": evidence,
                             **({"tags": ["multi_passage"]}
                                if verdict != "UNSUPPORTED"
                                and len({e["index"] for e in evidence}) >= 2 else {})})
    return gold, unreviewed


def build_case(case: dict[str, Any], gold: list[dict[str, Any]],
               rounds: dict[str, int]) -> dict[str, Any]:
    tags = sorted(set(case.get("difficulty_tags") or []) |
                  {t for g in gold for t in g.get("tags", [])})
    if "multi_passage" in tags and not any(g.get("tags") == ["multi_passage"] for g in gold):
        tags.remove("multi_passage")
    return {
        "id": case["id"],
        "split": case["split"],
        "tags": tags,
        "context_passages": case["context_passages"],
        "generated_answer": case["generated_answer"],
        "gold_claims": gold,
        "notes": (f"{case['source']}: {case['generator_model']}; "
                  f"review rounds: {rounds.get(case['id'], 0)}; "
                  f"upstream annotation kept in source_labels"),
        "source": case["source"],
        "source_labels": case["source_labels"],
        "generator_model": case["generator_model"],
        "context_words": case["context_words"],
        "difficulty_tags": sorted(set(case.get("difficulty_tags") or [])),
        "provenance": {
            **case["provenance"],
            "source_group": case["source_group_id"],
            "annotation_origin": "human_reviewed",
            "review_rounds": rounds.get(case["id"], 0),
            "review_decisions": "data/annotation/decisions_round1.jsonl"
                                + (", data/annotation/decisions_round2.jsonl" if rounds.get(case["id"], 0) > 1 else ""),
        },
    }


def upstream_verdict(claim: dict[str, Any]) -> str | None:
    if claim.get("upstream_label") in ("S", "NS"):
        return {"S": "SUPPORTED", "NS": "UNSUPPORTED"}[claim["upstream_label"]]
    overlaps = claim.get("overlapping_source_labels") or []
    if any("Conflict" in lab["label_type"] for lab in overlaps):
        return "CONTRADICTED"
    if any("Baseless" in lab["label_type"] for lab in overlaps):
        return "UNSUPPORTED"
    if claim.get("needs_full_review"):
        return None
    return "SUPPORTED"


def disagreements(cases: list[dict[str, Any]], drafts: dict[str, dict]) -> list[dict[str, Any]]:
    """Final labels that differ from the original dataset's annotation."""
    out: list[dict[str, Any]] = []
    for case in cases:
        draft = drafts.get(case["id"])
        if not draft:
            continue
        by_text = {c["claim_text"].strip(): c for c in draft.get("claims") or []}
        for gold in case["gold_claims"]:
            source_claim = by_text.get(gold["claim_text"].strip())
            if not source_claim:
                continue
            upstream = upstream_verdict(source_claim)
            if upstream and upstream != gold["verdict"]:
                out.append({"case_id": case["id"], "claim_text": gold["claim_text"],
                            "upstream": upstream, "final": gold["verdict"],
                            "upstream_detail": source_claim.get("overlapping_source_labels")
                                               or source_claim.get("upstream_label")})
    return out


def audit_report(r2_queue: list[dict[str, Any]], r2: dict[str, dict]) -> dict[str, Any]:
    sampled = [q for q in r2_queue if "random_10pct" in q.get("reasons", [])]
    overturned = 0
    checked = 0
    for item in sampled:
        decision = r2.get(item["claim_id"])
        if decision is None:
            continue
        checked += 1
        if decision.get("action") != "agree" or (
                decision.get("verdict") and decision["verdict"] != item.get("round1_verdict")):
            overturned += 1
    rate = overturned / checked if checked else None
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "random_sample_size": len(sampled),
        "random_sample_reviewed": checked,
        "overturned_in_sample": overturned,
        "overturn_rate": rate,
        "note": ("Share of the randomly re-checked round-1 agreements that round 2 changed. "
                 "This is an estimate of round-1 label error, for docs/DATASET.md."),
    }


def target_report(cases: list[dict[str, Any]]) -> list[str]:
    """Compare the result with the design doc §1 targets. Report, never adjust the data."""
    import statistics
    test = [c for c in cases if c["split"] == "test"]
    claims = [g for c in test for g in c["gold_claims"]]
    verdicts = Counter(g["verdict"] for g in claims)
    multi = sum(1 for g in claims if len({e["index"] for e in g["evidence"]}) >= 2)
    words = [c["context_words"] for c in test]
    per_case = [len(c["gold_claims"]) for c in test]
    lines = []
    checks = [
        ("test cases", len(test), "24"),
        ("median context words", f"{statistics.median(words):.0f}" if words else "0", ">= 400"),
        ("cases with >= 800 context words",
         sum(1 for w in words if w >= 800), ">= 8 (one third of 24)"),
        ("median gold claims per answer",
         f"{statistics.median(per_case):.0f}" if per_case else "0", ">= 7"),
        ("test CONTRADICTED", verdicts.get("CONTRADICTED", 0), ">= 30"),
        ("test UNSUPPORTED", verdicts.get("UNSUPPORTED", 0), ">= 30"),
        ("test claims needing >= 2 passages", multi, ">= 20"),
    ]
    for name, got, want in checks:
        lines.append(f"  {name:<38}got {str(got):<8}target {want}")
    return lines


def main() -> None:
    ap = argparse.ArgumentParser(description="T7: merge review decisions into the hard dataset")
    ap.add_argument("--allow-partial", action="store_true",
                    help="write with unreviewed claims (pilot only; default refuses)")
    ap.add_argument("--no-freeze", action="store_true", help="do not write freeze.json")
    args = ap.parse_args()

    if not DRAFTS.is_file():
        raise SystemExit(f"STOP: {S.rel(DRAFTS)} not found.")
    drafts = {c["id"]: c for c in
              (json.loads(line) for line in DRAFTS.read_text(encoding="utf-8").splitlines()
               if line.strip())}
    r1 = load_decisions(ROUND1)
    r2 = load_decisions(ROUND2)
    if not r1:
        raise SystemExit(f"STOP: no round-1 decisions at {S.rel(ROUND1)}; "
                         f"run the review page first.")

    cases: list[dict[str, Any]] = []
    rounds: dict[str, int] = {}
    blocked: dict[str, list[str]] = {}
    for case_id, case in drafts.items():
        decisions = {}
        used_rounds = 1
        for claim in case.get("claims") or []:
            decision = effective_decision(claim["claim_id"], r1, r2)
            if decision:
                decisions[claim["claim_id"]] = decision
                if claim["claim_id"] in r2:
                    used_rounds = 2
        gold, unreviewed = case_claims(case, decisions)
        if unreviewed:
            blocked[case_id] = unreviewed
            if not args.allow_partial:
                continue
        rounds[case_id] = used_rounds
        cases.append(build_case(case, gold, rounds))

    if blocked and not args.allow_partial:
        print("STOP: refusing to build the dataset while claims are unreviewed.")
        for case_id, ids in blocked.items():
            print(f"  {case_id}: {len(ids)} unreviewed -> {ids[:6]}"
                  f"{' ...' if len(ids) > 6 else ''}")
        print(f"\nReview them (uv run python -m annotation.review_app --round 1), then re-run.\n"
              f"For the 5-case pilot only, pass --allow-partial.")
        raise SystemExit(4)

    # the dataset must validate before anything is written
    from eval.dataset import hard_summary, validate
    from eval.dataset import EvalCase
    validated = [EvalCase.model_validate(c) for c in cases]
    errors = validate(validated)
    if errors:
        print("STOP: merged dataset is invalid:")
        for e in errors[:20]:
            print(f"  - {e}")
        raise SystemExit(5)

    S.write_jsonl(OUT, cases)
    dis = disagreements(cases, drafts)
    S.write_jsonl(DISAGREEMENTS, dis)
    r2_queue = [json.loads(line) for line in ROUND2_QUEUE.read_text(encoding="utf-8").splitlines()
                if line.strip()] if ROUND2_QUEUE.is_file() else []
    audit = audit_report(r2_queue, r2)
    AUDIT.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"dataset -> {S.rel(OUT)}: {len(cases)} case(s), "
          f"{sum(len(c['gold_claims']) for c in cases)} gold claim(s)")
    print(hard_summary(validated))
    print("\nDesign-doc targets (reported, not tuned for):")
    for line in target_report(cases):
        print(line)
    print(f"\ndisagreements with the upstream annotation: {len(dis)} -> "
          f"{S.rel(DISAGREEMENTS)}")
    print(f"round-2 audit: {audit['overturned_in_sample']}/{audit['random_sample_reviewed']} "
          f"overturned ({audit['overturn_rate']}) -> {S.rel(AUDIT)}")

    if not args.no_freeze:
        sha = hashlib.sha256(OUT.read_bytes()).hexdigest()
        freeze = {
            "frozen_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "file": str(S.rel(OUT)),
            "sha256": sha,
            "cases": len(cases),
            "claims": sum(len(c["gold_claims"]) for c in cases),
            "splits": dict(Counter(c["split"] for c in cases)),
            "decisions_round1_sha256": hashlib.sha256(ROUND1.read_bytes()).hexdigest()
                                        if ROUND1.is_file() else None,
            "decisions_round2_sha256": hashlib.sha256(ROUND2.read_bytes()).hexdigest()
                                        if ROUND2.is_file() else None,
            "note": "No verifier has been run on the test split as of this hash. Any change to "
                    "the dataset after this point needs a new hash and a note in docs/ITERATIONS.md.",
        }
        FREEZE.write_text(json.dumps(freeze, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"frozen: sha256 {sha[:16]} -> {S.rel(FREEZE)}")
    print("\nNext: python -m eval.dataset data/eval_hard.jsonl")


if __name__ == "__main__":
    main()
