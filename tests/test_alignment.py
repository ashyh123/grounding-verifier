"""Failure modes: changed/missing numbers, polarity flips, removed guarded clauses,
partial compound claims, duplicate/additional outputs, and blocked edges stealing valid matches.
These are lexical guards; conditions without a changed number/negation still need semantic review.
"""
import pytest

from eval.dataset import EvalCase, GoldClaim
from eval.metrics import compute
from verifier.align import align_claims


@pytest.mark.parametrize("pred,gold", [
    ("The server waits 600 seconds.", "The server waits 60 seconds."),
    ("The temperature is -10 degrees.", "The temperature is 10 degrees."),
    ("The server waits.", "The server waits 60 seconds."),
    ("The server allows writes.", "The server does not allow writes."),
    ("The server allows writes.", "The server cannot allow writes."),
    ("The server allows writes.", "The server never allows writes."),
    ("Restart is allowed.", "Restart is allowed if the cache is not empty."),
    ("The server uses TLS.", "The server uses TLS and listens on port 8000."),
])
def test_alignment_rejects_changed_numbers_polarity_and_guarded_omissions(pred, gold):
    result = align_claims([pred], [gold])
    assert result.pairs == []
    assert result.guard_rejected_pairs == 1
    case = EvalCase(id="counterexample", split="dev", tags=[], context_passages=[],
                    generated_answer=gold,
                    gold_claims=[GoldClaim(claim_text=gold, verdict="UNSUPPORTED")])
    scored = compute([case], {case.id: {"claims": [
        {"claim_text": pred, "verdict": "UNSUPPORTED", "citations": []}]}})
    assert scored["guard_rejected_pairs"] == 1
    assert scored["decomposition"]["missed_gold"] == 1
    assert scored["decomposition"]["extra_predictions"] == 1
    assert scored["claim_accuracy_all_gold"] == 0


@pytest.mark.parametrize("pred,gold", [
    ("Checkpoint after 1,000 pages.", "Checkpoint after 1000 pages."),
    ("Version 3.7.0 is available.", "Version 3.7.0 is available."),
    ("The server can't allow writes.", "The server cannot allow writes."),
])
def test_guard_keeps_identical_numbers_and_equivalent_explicit_negation(pred, gold):
    result = align_claims([pred], [gold])
    assert [(p, g) for p, g, _ in result.pairs] == [(0, 0)]
    assert result.guard_rejected_pairs == 0


def test_guard_excludes_edges_before_assignment_so_valid_matches_can_be_found():
    result = align_claims(["The replica waits 600 seconds.", "The primary waits 60 seconds."],
                          ["The replica waits 60 seconds.", "The primary waits 600 seconds."])
    assert {(p, g) for p, g, _ in result.pairs} == {(0, 1), (1, 0)}
    assert result.guard_rejected_pairs == 2


def test_duplicate_and_additional_claims_are_separate_unmatched_outputs():
    text = "The cache stores data."
    case = EvalCase(id="duplicates", split="dev", tags=[], context_passages=[],
                    generated_answer=text,
                    gold_claims=[GoldClaim(claim_text=text, verdict="UNSUPPORTED")])
    result = compute([case], {case.id: {"claims": [
        {"claim_text": p, "verdict": "UNSUPPORTED", "citations": []}
        for p in [text, text, "Elephants dance on Jupiter."]]}})
    assert result["decomposition"] == {
        "recall": 1.0, "precision": 1 / 3, "gold_claims": 1, "predicted_claims": 3,
        "matched_pairs": 1, "used_predictions": 1, "missed_gold": 0, "extra_predictions": 2,
        "duplicate_predictions": 1, "added_predictions": 1}


@pytest.mark.parametrize("pred,gold", [
    ([], []), (["A fact."], []), ([], ["A fact."]),
    (["The database uses TLS."], ["Elephants dance on Jupiter for 500 years."]),
])
def test_empty_or_unrelated_alignment_inputs(pred, gold):
    result = align_claims(pred, gold)
    assert result.pairs == [] and result.guard_rejected_pairs == 0
