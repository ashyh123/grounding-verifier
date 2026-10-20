"""T4 — flag the drafts automatically. Adds `flags`, changes nothing else.

    uv run python -m annotation.check_drafts

Flags (spec T4):

red    evidence_not_verbatim    evidence that could not be located exactly or after normalisation
red    source_label_uncovered   an upstream hallucination span no claim answers for (RAGTruth)
red    answer_not_covered       a run of >20 non-whitespace characters of the answer in no claim
yellow supported_without_evidence  SUPPORTED_CANDIDATE with no located evidence
yellow model_disagrees          the drafter's verdict differs from the script's
yellow evidence_truncated       FActScore case cut at the passage limit whose supported fact has
                                no evidence in the kept text

The file is rewritten in place with the flags added; the claim content is asserted to be unchanged,
so a flag can never rewrite what the drafter said.
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Any

from . import sources as S

DRAFTS = S.ANNOTATION_DIR / "drafts.jsonl"

RED = "red"
YELLOW = "yellow"
UNCOVERED_RUN = 20


def evidence_not_verbatim(claim: dict[str, Any], case: dict[str, Any]) -> list[dict]:
    bad = [e for e in claim.get("evidence") or [] if e.get("match") not in ("exact", "normalized")]
    return [{"level": RED, "flag": "evidence_not_verbatim",
             "detail": f"evidence {e.get('index')} match={e.get('match')}: "
                       f"{str(e.get('requested_quote'))[:60]!r}"} for e in bad]


def supported_without_evidence(claim: dict[str, Any], case: dict[str, Any]) -> list[dict]:
    if claim.get("draft_verdict") != "SUPPORTED_CANDIDATE":
        return []
    if any(e.get("located") for e in claim.get("evidence") or []):
        return []
    return [{"level": YELLOW, "flag": "supported_without_evidence",
             "detail": "SUPPORTED_CANDIDATE with no evidence that could be located in the passages"}]


def model_disagrees(claim: dict[str, Any], case: dict[str, Any]) -> list[dict]:
    model_verdict = claim.get("model_verdict")
    draft = claim.get("draft_verdict")
    if not model_verdict or not draft:
        return []
    if draft == "SUPPORTED_CANDIDATE":
        differs = model_verdict != "SUPPORTED"
    elif draft == "NOT_SUPPORTED":
        # FActScore: the script says "not supported" by construction and the drafter is asked to
        # refine it into CONTRADICTED or UNSUPPORTED, so that is not a disagreement.
        differs = False
    else:
        differs = model_verdict != draft
    if not differs:
        return []
    return [{"level": YELLOW, "flag": "model_disagrees",
             "detail": f"drafter said {model_verdict}, the script assigned {draft}"}]


def fragment_claim(claim: dict[str, Any], case: dict[str, Any]) -> list[dict]:
    """A claim with no proposition: a list marker, a bare number, a truncated clause.

    These are decomposition failures, not labelling questions. They are cheap to detect and they
    are the main reason a review queue fills up with items a human can only delete.
    """
    text = (claim.get("claim_text") or "").strip()
    words = text.split()
    stripped = text.rstrip(" .!?;:,)")
    if len(words) <= 2 and (len(stripped) <= 3 or stripped.isdigit()):
        return [{"level": RED, "flag": "fragment_claim",
                 "detail": f"no proposition to verify: {text[:40]!r}"}]
    if len(words) <= 4 and stripped.rstrip(".").isdigit():
        return [{"level": RED, "flag": "fragment_claim",
                 "detail": f"no proposition to verify: {text[:40]!r}"}]
    return []


def duplicate_claim(claim: dict[str, Any], case: dict[str, Any]) -> list[dict]:
    """The same text already appears as an earlier claim of this case."""
    mine = (claim.get("claim_text") or "").strip().lower()
    if not mine:
        return []
    earlier = [c for c in case.get("claims") or []
               if c["claim_id"] != claim["claim_id"]
               and (c.get("claim_text") or "").strip().lower() == mine
               and c["claim_id"] < claim["claim_id"]]
    if not earlier:
        return []
    return [{"level": YELLOW, "flag": "duplicate_claim",
             "detail": f"same text as {earlier[0]['claim_id']}"}]


def evidence_truncated(claim: dict[str, Any], case: dict[str, Any]) -> list[dict]:
    if not case.get("truncated") or not case["source"].startswith("factscore"):
        return []
    if claim.get("draft_verdict") != "SUPPORTED_CANDIDATE":
        return []
    if any(e.get("located") for e in claim.get("evidence") or []):
        return []
    return [{"level": YELLOW, "flag": "evidence_truncated",
             "detail": "Wikipedia extract was cut at the passage limit and this supported fact has "
                       "no evidence in the kept text"}]


CLAIM_CHECKS = (evidence_not_verbatim, supported_without_evidence, model_disagrees,
                evidence_truncated, fragment_claim, duplicate_claim)


def uncovered_answer_runs(case: dict[str, Any]) -> list[tuple[int, int]]:
    """Runs of >UNCOVERED_RUN non-whitespace answer characters that no claim span covers."""
    answer = case["generated_answer"]
    covered = [False] * len(answer)
    for claim in case.get("claims") or []:
        span = claim.get("answer_span")
        if not span:
            continue
        start = max(0, int(span.get("start", 0)))
        end = min(len(answer), int(span.get("end", 0)))
        for i in range(start, end):
            covered[i] = True
    runs: list[tuple[int, int]] = []
    i = 0
    while i < len(answer):
        if covered[i] or answer[i].isspace():
            i += 1
            continue
        j = i
        while j < len(answer) and not covered[j]:
            j += 1
        text = answer[i:j]
        if len(text.strip()) > UNCOVERED_RUN:
            runs.append((i, j))
        i = j
    return runs


def uncovered_source_labels(case: dict[str, Any]) -> list[dict[str, Any]]:
    labels = case.get("source_labels", {}).get("labels") or []
    spans = [c.get("answer_span") for c in case.get("claims") or [] if c.get("answer_span")]
    out = []
    for lab in labels:
        if not any(s["start"] < lab["end"] and lab["start"] < s["end"] for s in spans):
            out.append(lab)
    return out


def flag_case(case: dict[str, Any]) -> tuple[list[dict], list[dict]]:
    """(claim-level flags per claim, case-level flags)."""
    per_claim: list[list[dict]] = []
    for claim in case.get("claims") or []:
        flags: list[dict] = []
        for check in CLAIM_CHECKS:
            flags.extend(check(claim, case))
        per_claim.append(flags)

    case_flags: list[dict] = []
    if case["source"].startswith("ragtruth"):
        for lab in uncovered_source_labels(case):
            case_flags.append({
                "level": RED, "flag": "source_label_uncovered",
                "detail": f"answer[{lab['start']}:{lab['end']}] {lab['label_type']!r} "
                          f"{lab['text'][:60]!r} overlaps no claim"})
    if case["source"].startswith("ragtruth") or case["source"].startswith("halueval"):
        for start, end in uncovered_answer_runs(case):
            case_flags.append({
                "level": RED, "flag": "answer_not_covered",
                "detail": f"answer[{start}:{end}] in no claim: "
                          f"{case['generated_answer'][start:end][:60]!r}"})
    return per_claim, case_flags


def main() -> None:
    if not DRAFTS.is_file():
        raise SystemExit(f"STOP: {S.rel(DRAFTS)} not found; "
                         f"run annotation.draft_claims first.")
    cases = [json.loads(line) for line in DRAFTS.read_text(encoding="utf-8").splitlines()
             if line.strip()]

    counts: Counter[tuple[str, str, str]] = Counter()
    flagged_cases = 0
    before = json.dumps(cases, ensure_ascii=False, sort_keys=True)
    for case in cases:
        per_claim, case_flags = flag_case(case)
        for claim, flags in zip(case["claims"], per_claim):
            claim["flags"] = flags
        case["flags"] = case_flags
        case["flags_summary"] = {
            "claims_with_flags": sum(1 for f in per_claim if f),
            "red": sum(1 for f in per_claim for x in f if x["level"] == RED)
                   + sum(1 for x in case_flags if x["level"] == RED),
            "yellow": sum(1 for f in per_claim for x in f if x["level"] == YELLOW)
                      + sum(1 for x in case_flags if x["level"] == YELLOW),
        }
        if case["flags_summary"]["red"] or case["flags_summary"]["yellow"]:
            flagged_cases += 1
        for x in per_claim:
            for f in x:
                counts[(case["source"], f["level"], f["flag"])] += 1
        for f in case_flags:
            counts[(case["source"], f["level"], f["flag"])] += 1

    # the flags are additive: assert nothing else about the cases moved
    stripped = json.loads(json.dumps(cases, ensure_ascii=False))
    for case in stripped:
        case.pop("flags", None)
        case.pop("flags_summary", None)
        for claim in case["claims"]:
            claim.pop("flags", None)
    assert json.dumps(stripped, ensure_ascii=False, sort_keys=True) == before, \
        "check_drafts must not change draft content"

    S.write_jsonl(DRAFTS, cases)

    broken = []
    for case in cases:
        claims_ = case["claims"]
        if not claims_:
            continue
        frags = sum(1 for cl in claims_
                    if any(f["flag"] == "fragment_claim" for f in cl.get("flags") or []))
        if frags / len(claims_) >= 0.5:
            broken.append((case["id"], frags, len(claims_)))

    claims = sum(len(c["claims"]) for c in cases)
    print(f"checked {len(cases)} case(s), {claims} claim(s); "
          f"{flagged_cases} case(s) carry at least one flag")
    print(f"\n{'source':<24}{'level':<8}{'flag':<28}count")
    print("-" * 68)
    for (source, level, flag), n in sorted(counts.items()):
        print(f"{source:<24}{level:<8}{flag:<28}{n}")
    if not counts:
        print("(no flags)")
    if broken:
        print("\ncase(s) whose decomposition is broken (>= half the claims are fragments):")
        for case_id, frags, total in broken:
            print(f"  {case_id}: {frags}/{total} fragment claims")
        print("  Re-draft these cases before reviewing them; reviewing them wastes your time.")
    print(f"\nflagged drafts -> {S.rel(DRAFTS)} (content unchanged, flags added)")
    print("Next: uv run python -m annotation.review_app --round 1")


if __name__ == "__main__":
    main()
