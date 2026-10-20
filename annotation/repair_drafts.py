"""Replay user-approved annotation metadata revisions against an immutable model draft.

    python -m annotation.repair_drafts --input drafts.original.jsonl \
        --revisions draft_revisions.jsonl --out drafts.jsonl

No model calls, label edits, claim edits, automatic fuzzy acceptance or semantic exemptions.
The revision journal is append-only; this command reads it and creates a new derived file.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

from .draft_claims import case_diagnostics, draft_ragtruth
from .triage import active_flags


def apply_revisions(source: bytes, revisions: list[dict]) -> list[dict]:
    cases = [json.loads(line) for line in source.decode().splitlines() if line.strip()]
    original = copy.deepcopy(cases)
    by_id = {case["id"]: case for case in cases}
    digest = hashlib.sha256(source).hexdigest()
    if len(by_id) != len(cases):
        raise ValueError("duplicate source case IDs")
    seen = set()
    for revision in revisions:
        if (revision.get("approved_by") != "user"
                or revision.get("scope") != "annotation_metadata_only"
                or revision.get("source_sha256") != digest):
            raise ValueError("revision requires user metadata approval and the exact source SHA256")
        rid = revision["revision_id"]
        if not rid or rid in seen:
            raise ValueError("revision IDs must be nonempty and unique")
        seen.add(rid)
        if not revision.get("reason") or not revision.get("approved_at"):
            raise ValueError("revision requires a reason and approval time")
        case = by_id[revision["case_id"]]
        if revision["op"] != "replace_answer_spans":
            continue
        claim = next(c for c in case["claims"] if c["claim_id"] == revision["claim_id"])
        if claim["answer_spans"] != revision["before"]:
            raise ValueError("answer-span precondition does not match")
        spans = revision["after"]
        if not spans:
            raise ValueError("replacement answer spans must be nonempty")
        answer = case["generated_answer"]
        for span in spans:
            start, end, quote = span.get("start"), span.get("end"), span.get("quote")
            if (span.get("match") != "exact" or type(start) is not int or type(end) is not int
                    or not isinstance(quote, str) or not quote
                    or not 0 <= start < end <= len(answer) or answer[start:end] != quote
                    or answer.find(quote) != start or answer.find(quote, start + 1) != -1):
                raise ValueError("replacement must be a unique, exact original-answer substring")
        claim["answer_spans"] = copy.deepcopy(spans)

    # Recompute diagnostics from the exact answer spans, keeping every label and model output.
    for case in cases:
        mapped, notes = draft_ragtruth(case, case["claims"])
        for claim, diagnostic in zip(case["claims"], mapped):
            claim["flags"] = diagnostic["flags"]
        case["flags"] = case_diagnostics(case, notes)

    for revision in revisions:
        case = by_id[revision["case_id"]]
        claim = (next(c for c in case["claims"] if c["claim_id"] == revision["claim_id"])
                 if revision.get("claim_id") else None)
        operation = revision["op"]
        if operation == "waive_flag":
            selector = revision["selector"]
            if selector.get("flag") not in ("answer_gap", "partial_overlap"):
                raise ValueError("only answer-gap and partial-overlap metadata waivers are supported")
            flags = (claim if claim is not None else case)["flags"]
            matches = [f for f in flags if all(f.get(k) == v for k, v in selector.items())]
            if len(matches) != 1 or matches[0].get("status") == "waived":
                raise ValueError("waiver must identify exactly one unwaived diagnostic")
            matches[0].update(status="waived", waiver={
                "revision_id": revision["revision_id"], "approved_by": "user",
                "reason": revision["reason"]})
        elif operation == "require_human_review":
            if claim is None:
                raise ValueError("human review hold requires a claim")
            claim["flags"].append({"level": "red", "flag": "human_adjudication_required",
                                   "detail": revision["reason"], "revision_id": revision["revision_id"]})
        elif operation != "replace_answer_spans":
            raise ValueError("unsupported revision operation: labels and claim edits are forbidden")
        case.setdefault("draft_revisions", []).append(revision["revision_id"])

    # All non-metadata content, including nullable upstream verdicts, remains exactly as supplied.
    for before, after in zip(original, cases):
        def content(case):
            value = copy.deepcopy(case)
            value.pop("flags", None)
            value.pop("draft_revisions", None)
            for claim in value["claims"]:
                claim.pop("flags", None)
                claim.pop("answer_spans", None)
            return value
        if content(before) != content(after):
            raise ValueError("revision changed protected claim, label, answer or provenance data")
    return cases


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--revisions", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    if args.out.resolve() in (args.input.resolve(), args.revisions.resolve()) or args.out.exists():
        raise SystemExit("STOP: output must be a new file; original draft and journal cannot be overwritten")
    revisions = [json.loads(line) for line in args.revisions.read_text().splitlines() if line.strip()]
    cases = apply_revisions(args.input.read_bytes(), revisions)
    payload = "".join(json.dumps(case, ensure_ascii=False) + "\n" for case in cases)
    with args.out.open("x", encoding="utf-8") as stream:
        stream.write(payload)
    print(json.dumps({"cases": len(cases), "revisions": len(revisions),
                      "active_case_flags": sum(len(active_flags(c["flags"])) for c in cases),
                      "active_claim_flags": sum(len(active_flags(cl["flags"])) for c in cases for cl in c["claims"])},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
