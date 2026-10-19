"""Build a read-only review packet from immutable drafts, proposals and human decisions.

This exports a preview, never decisions, eval_hard.jsonl or freeze.json. Model suggestions
stay proposals even when a user has delegated the preparation of the remaining cases.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from . import triage

ROOT = Path(__file__).resolve().parent.parent


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def exact_evidence(case: dict, items: list[dict]) -> None:
    for e in items:
        index, start, end = e.get("index"), e.get("start_char"), e.get("end_char")
        if (type(index) is not int or not 0 <= index < len(case["context_passages"])
                or type(start) is not int or type(end) is not int
                or not 0 <= start < end <= len(case["context_passages"][index])
                or not e.get("quote", "").strip()
                or case["context_passages"][index][start:end] != e["quote"]):
            raise ValueError(f"{case['id']}: evidence must be an exact English source substring")


def build(draft_paths: list[Path], review_paths: list[Path], decisions_path: Path) -> tuple[dict, dict]:
    cases, source_hashes, input_hashes = {}, {}, {}
    for path in draft_paths:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        input_hashes[str(path)] = digest
        for case in read_jsonl(path):
            if case["id"] in cases:
                raise ValueError(f"duplicate draft case: {case['id']}")
            cases[case["id"]] = case
            source_hashes[case["id"]] = digest
    decisions = {}
    if decisions_path.is_file():
        input_hashes[str(decisions_path)] = hashlib.sha256(decisions_path.read_bytes()).hexdigest()
        for decision in read_jsonl(decisions_path):
            decisions[decision["claim_id"]] = decision
    proposals = {}
    for path in review_paths:
        input_hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        for item in read_jsonl(path):
            if item["claim_id"] in proposals:
                raise ValueError(f"duplicate proposal: {item['claim_id']}")
            if item["source_sha256"] != source_hashes[item["case_id"]]:
                raise ValueError(f"stale proposal: {item['claim_id']}")
            case = cases[item["case_id"]]
            for unit in [item, *item.get("proposed_children", [])]:
                exact_evidence(case, unit.get("evidence_candidates", []) + unit.get("related_context", []))
                if unit.get("suggested_verdict") in ("SUPPORTED", "CONTRADICTED") and not unit.get("evidence_candidates"):
                    raise ValueError(f"{item['claim_id']}: S/C proposal needs exact evidence")
            proposals[item["claim_id"]] = item
    confirmed, pending, structural, seen = [], [], [], set()

    def resolve(case: dict, claim: dict, ancestors: tuple[str, ...] = ()):
        claim_id = claim["claim_id"]
        if claim_id in ancestors:
            raise ValueError(f"cyclic split lineage: {claim_id}")
        decision = decisions.get(claim_id)
        if decision is None:
            proposal = proposals.get(claim_id)
            if proposal is None or proposal["claim_text"] != claim["claim_text"]:
                raise ValueError(f"missing review proposal: {claim_id}")
            pending.append(proposal)
            return
        if (decision.get("author") != "user" or decision.get("label_source") != "human_adjudicated"
                or not decision.get("human_confirmation") or decision.get("source_sha256") != source_hashes[case["id"]]):
            raise ValueError(f"{claim_id}: missing explicit human confirmation or stale source")
        if decision["action"] == "delete":
            structural.append(decision)
        elif decision["action"] == "split":
            children = decision.get("replacement_claim_ids", [])
            if len(children) < 2 or len(set(children)) != len(children):
                raise ValueError(f"{claim_id}: split needs distinct child ids")
            for child_id in children:
                child = decisions.get(child_id)
                if not child or claim_id not in child.get("derived_from", []):
                    raise ValueError(f"{claim_id}: child decision or derived_from missing")
                resolve(case, child, (*ancestors, claim_id))
        else:
            if decision.get("action") != "set_verdict" or decision.get("verdict") not in ("SUPPORTED", "CONTRADICTED", "UNSUPPORTED"):
                raise ValueError(f"{claim_id}: unresolved human decision")
            evidence = decision.get("evidence", [])
            exact_evidence(case, evidence)
            if bool(evidence) != (decision["verdict"] != "UNSUPPORTED"):
                raise ValueError(f"{claim_id}: verdict/evidence mismatch")
            if claim_id in seen:
                raise ValueError(f"duplicate active child: {claim_id}")
            seen.add(claim_id)
            confirmed.append(decision)

    for case in cases.values():
        for claim in case["claims"]:
            resolve(case, claim)
    ordered = sorted(cases.values(), key=lambda c: (c["split"] != "dev", c["id"]))
    plan = triage.plan(ordered, {})
    audit = {
        "generated_at": datetime.now(timezone.utc).isoformat(), "status": "awaiting_final_human_review",
        "cases": len(cases), "case_splits": dict(Counter(c["split"] for c in ordered)),
        "confirmed_active_claims": len(confirmed), "pending_original_claims": len(pending),
        "confirmed_verdicts": dict(Counter(d["verdict"] for d in confirmed)),
        "pending_suggested_verdicts": dict(Counter(d.get("suggested_verdict") or "NOT_SCORED" for d in pending)),
        "pending_split_parents": sum(bool(p.get("proposed_children")) for p in pending),
        "confirmed_non_scored_items": len(structural),
        "bucket_counts_before_human_resolution": plan["counts"],
        "blind_review": {"status": "not_run", "reason": "model_and_key_not_selected"},
        "c_audit": {"denominator": 0, "overturned": 0, "rate": None,
                    "escalation": "not_applicable_no_A_or_C_without_independent_blind_review"},
        "first_final_agreement": {"rate": None, "reason": "No blind first judgments collected for this assistant-review route."},
        "whole_case_checks": [{**c, "status": "awaiting_human_decomposition_check"} for c in plan["whole_case_checks"]],
        "input_sha256": input_hashes, "gold_written": False, "frozen": False,
        "tests_run_this_round": False, "evaluation_run_this_round": False, "commit_created_this_round": False,
    }
    payload = {"title": "30 例 RAGTruth · 最终核对预览", "description":
               "已确认的人工结果与本轮助手建议分别列出。新建议的标签、拆分和中文解释待你看过确认；未运行独立盲审，尚未合并或冻结金标。",
               "cases": ordered, "reviews": pending, "confirmed": confirmed, "structural": structural,
               "feedback": {}, "source_sha256": hashlib.sha256(json.dumps(input_hashes, sort_keys=True).encode()).hexdigest(),
               "report_read_only": True, "audit": audit}
    return payload, plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--drafts", type=Path, nargs="+", required=True)
    parser.add_argument("--reviews", type=Path, nargs="+", required=True)
    parser.add_argument("--decisions", type=Path, default=ROOT / "data/annotation/decisions_round1.jsonl")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    payload, plan = build(args.drafts, args.reviews, args.decisions)
    args.out.mkdir(parents=True, exist_ok=False)
    template = Path(__file__).with_name("pilot_review.html").read_text()
    html = template.replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c"))
    (args.out / "index.html").write_text(html.replace("__NONCE__", "local-readonly-review"))
    (args.out / "preview.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    (args.out / "audit.preview.json").write_text(json.dumps(payload["audit"], ensure_ascii=False, indent=2) + "\n")
    (args.out / "triage.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: payload["audit"][k] for k in ("cases", "case_splits", "confirmed_active_claims", "pending_original_claims")}, ensure_ascii=False))
    print(f"Review preview: {args.out / 'index.html'}; no decisions or gold dataset written.")


if __name__ == "__main__":
    main()
