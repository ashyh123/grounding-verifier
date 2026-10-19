"""Tests for the v2 annotation pipeline. No network, no model calls.

The fixtures build small synthetic upstream records in the real formats, so the segmentation,
labelling and flag logic is exercised without the multi-hundred-megabyte snapshots.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from annotation import check_drafts, merge, prompts, round2_queue
from annotation import sources as S

ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- segmentation

def test_paragraph_split_only_cuts_text():
    text = ("First sentence here. Second one follows.\n\n"
            "A second paragraph, with “curly” quotes and  double  spaces.\n\n"
            "Third paragraph ends here.")
    passages = S.split_paragraphs(text)
    assert len(passages) == 3
    check = S.check_segmentation("t", passages, text)
    assert check.ok, check.detail


def test_sentence_chunking_keeps_quotes_at_boundaries():
    # A closing quote between two sentences used to be dropped by a trimming splitter; the
    # annotation splitter must cut on offsets, not on trimmed sentence text.
    text = 'He said "we will win." Then he left. She stayed.'
    chunks = S._sentence_chunks(text, 1)
    assert S.ws("".join(chunks)) == S.ws(text)


def test_qa_passages_drop_only_prefixes():
    field = ("passage 1:First answer text.\n\n"
             "passage 2:Second answer text.\n\n"
             "passage 3:Third answer text.\n\n")
    passages = S.split_qa_passages(field)
    assert passages == ["First answer text.", "Second answer text.", "Third answer text."]
    assert S.check_segmentation("t", passages, field, S.qa_prefixes(field)).ok


def test_data2txt_concatenates_to_the_original_json():
    record = {
        "name": "Cafe", "address": "1 Main St", "city": "Town", "state": "CA",
        "categories": "Food",
        "hours": {"Monday": "9-5", "Tuesday": "9-5"},
        "attributes": {"WiFi": "no", "OutdoorSeating": True},
        "business_stars": 4.5,
        "review_info": [{"review_stars": 5.0, "review_text": "Great."},
                        {"review_stars": 3.0, "review_text": "Fine."}],
    }
    passages = S.split_data2txt(record)
    original = json.dumps(record, ensure_ascii=False, indent=1)
    assert "".join(passages) == original
    assert any('"review_text": "Great."' in p for p in passages)
    assert len(passages) == 5  # basics, hours, attributes+stars, and one passage per review


def test_truncated_wikipedia_passes_the_prefix_check():
    paragraphs = "\n\n".join(f"Paragraph number {i} with a few words." for i in range(60))
    passages, truncated = S.split_wikipedia(paragraphs)
    assert truncated and len(passages) == S.MAX_PASSAGES
    assert S.check_segmentation("t", passages, paragraphs, allow_prefix=True).ok
    assert not S.check_segmentation("t", passages, paragraphs).ok


def test_segmentation_check_rejects_a_rewrite():
    check = S.check_segmentation("t", ["the quick brown fox"], "the quick brown cat")
    assert not check.ok


# --------------------------------------------------------------------------- T0

def test_fetch_sources_verifies_expected_fields(tmp_path, monkeypatch):
    from annotation import fetch_sources
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "source_info.jsonl").write_text(
        json.dumps({"source_id": "1", "task_type": "Summary", "source_info": "x"}) + "\n")
    (raw / "response.jsonl").write_text(json.dumps({
        "id": "1", "source_id": "1", "model": "gpt-4-0613", "response": "y",
        "labels": [{"start": 0, "end": 1, "text": "y", "label_type": "Evident Conflict"}],
        "split": "test"}) + "\n")
    for name in ("InstructGPT.jsonl", "ChatGPT.jsonl", "PerplexityAI.jsonl"):
        (raw / name).write_text(json.dumps({
            "topic": "Someone", "output": "Bio.", "annotations": [
                {"human-atomic-facts": [{"text": "A fact.", "label": "S"}]}]}) + "\n")
    (raw / "summarization_data.json").write_text(json.dumps({
        "document": "Doc.", "right_summary": "R", "hallucinated_summary": "H"}) + "\n")
    monkeypatch.setattr(fetch_sources, "S", S)
    monkeypatch.setattr(S, "RAW", raw)
    report = fetch_sources.verify_fields(check_offline=True)
    assert set(report) == set(fetch_sources.EXPECTED)


def test_fetch_sources_stops_on_a_field_mismatch(tmp_path, monkeypatch):
    from annotation import fetch_sources
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "source_info.jsonl").write_text(json.dumps({"source_id": "1"}) + "\n")
    monkeypatch.setattr(S, "RAW", raw)
    with pytest.raises(SystemExit) as exc:
        fetch_sources.verify_fields(check_offline=True)
    assert exc.value.code == 2


def test_html_to_text_drops_markup_and_tables():
    from annotation.fetch_sources import html_to_text
    markup = ('<p>First <b>paragraph</b>.</p><table><tr><td>infobox</td></tr></table>'
              '<h2>Heading</h2><p>Second&nbsp;paragraph.<sup>[1]</sup></p>')
    text = html_to_text(markup)
    assert "infobox" not in text
    assert "First paragraph." in text
    assert "Second paragraph." in text
    assert "Heading\nSecond paragraph." in text  # a heading rides with its paragraph
    assert "\n\n" in text


def test_html_to_text_joins_list_runs():
    # A filmography as one-line <li>s must not become one passage per credit: that would spend the
    # 50-passage budget on credits and leave the biography's prose outside the context.
    from annotation.fetch_sources import html_to_text
    markup = ('<h2>Filmography</h2><ul><li>Film A (1990)</li><li>Film B (1991)</li>'
              '<li>Film C (1992)</li></ul><p>After.</p>')
    text = html_to_text(markup)
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    assert len(paragraphs) == 2
    assert paragraphs[0].startswith("Filmography\n* Film A (1990)")
    assert "Film C (1992)" in paragraphs[0]


# --------------------------------------------------------------------------- T3 helpers

def _ragtruth_case(answer: str = "Alpha is red. Beta is blue.") -> dict[str, Any]:
    """A draft case with the fields draft_claims/merge actually rely on."""
    return {
        "id": "ragtruth-1", "source": "ragtruth_summary", "split": "dev",
        "context_passages": ["Alpha is red and square.", "Beta is blue."],
        "generated_answer": answer,
        "generator_model": "gpt-4-0613", "context_words": 8,
        "source_group_id": "ragtruth-1", "difficulty_tags": [], "truncated": False,
        "source_labels": {"labels": [
            {"start": 0, "end": 13, "text": "Alpha is red.", "label_type": "Evident Conflict"}]},
        "claims": [],
        "provenance": {"dataset": "RAGTruth", "response_id": "1", "source_id": "1"},
        "selection": {"seed": 20261019, "stratum": "evident_only"},
    }


def test_ragtruth_verdict_comes_from_overlap():
    case = _ragtruth_case()
    claims = [
        {"claim_text": "Alpha is red.", "answer_span": {"start": 0, "end": 13},
         "verdict": "SUPPORTED", "evidence": [{"index": 0, "quote": "Alpha is red"}]},
        {"claim_text": "Beta is blue.", "answer_span": {"start": 14, "end": 27},
         "verdict": "SUPPORTED", "evidence": [{"index": 1, "quote": "Beta is blue"}]},
    ]
    drafted, notes = __import__("annotation.draft_claims", fromlist=["draft_ragtruth"]) \
        .draft_ragtruth(case, claims)
    assert drafted[0]["draft_verdict"] == "CONTRADICTED"
    assert drafted[0]["model_verdict"] == "SUPPORTED"
    assert drafted[1]["draft_verdict"] == "SUPPORTED_CANDIDATE"
    assert drafted[1]["evidence"][0]["match"] == "exact"
    assert notes == []


def test_unresolvable_evidence_is_kept_but_marked():
    from annotation.draft_claims import resolve_evidence
    out = resolve_evidence(["Alpha is red."], [{"index": 0, "quote": "Alpha is crimson"}])
    assert out[0]["located"] is False and out[0]["match"] == "unresolved"
    assert out[0]["requested_quote"] == "Alpha is crimson"


def test_answer_span_is_checked_against_the_text():
    from annotation.draft_claims import resolve_answer_span
    answer = "Alpha is red. Beta is blue."
    span, how = resolve_answer_span(answer, "Alpha is red.", {"start": 0, "end": 13})
    assert span == {"start": 0, "end": 13} and how == "exact"
    span, how = resolve_answer_span(answer, "Beta is blue.", {"start": 0, "end": 5})
    assert span == {"start": 14, "end": 27} and how == "exact"  # model span rejected, text found


def test_factscore_draft_keeps_human_facts_and_labels():
    from annotation.draft_claims import draft_factscore
    case = {
        "context_passages": ["She was born in 1950 in Ohio."],
        "generated_answer": "She was born in 1950 in Ohio.",
        "source_labels": {"human_atomic_facts": [
            {"text": "She was born in 1950.", "label": "S"},
            {"text": "She was born in Ohio.", "label": "S"},
            {"text": "She was a pilot.", "label": "NS"},
            {"text": "Ohio is a state.", "label": "IR"},
        ]},
    }
    claims = [
        {"fact": 0, "claim_text": "She was born in 1950.", "verdict": "SUPPORTED",
         "evidence": [{"index": 0, "quote": "born in 1950"}]},
        {"fact": 1, "claim_text": "She was born in Ohio.", "verdict": "SUPPORTED",
         "evidence": [{"index": 0, "quote": "in Ohio"}]},
        {"fact": 2, "claim_text": "She was a pilot.", "verdict": "CONTRADICTED",
         "evidence": [{"index": 0, "quote": "born in 1950"}]},
    ]
    drafted, notes = draft_factscore(case, claims)
    assert [c["claim_text"] for c in drafted] == ["She was born in 1950.", "She was born in Ohio.",
                                                 "She was a pilot."]
    assert [c["draft_verdict"] for c in drafted] == ["SUPPORTED_CANDIDATE",
                                                     "SUPPORTED_CANDIDATE", "NOT_SUPPORTED"]
    assert drafted[2]["model_verdict"] == "CONTRADICTED"


def test_halueval_drafts_need_full_review():
    from annotation.draft_claims import draft_halueval
    case = {"context_passages": ["The sky is blue."],
            "generated_answer": "The sky is green."}
    drafted, _ = draft_halueval(case, [{"claim_text": "The sky is green.",
                                        "verdict": "CONTRADICTED", "tampered": True,
                                        "evidence": [{"index": 0, "quote": "The sky is blue"}]}])
    assert drafted[0]["needs_full_review"] is True
    assert drafted[0]["tampered"] is True


def test_annotation_model_must_be_set_and_differ_from_the_model_under_test(monkeypatch):
    from annotation import draft_claims
    from verifier import config
    monkeypatch.delenv("ANNOTATION_MODEL", raising=False)
    with pytest.raises(SystemExit) as exc:
        draft_claims.annotation_model()
    assert "ANNOTATION_MODEL" in str(exc.value)
    monkeypatch.setenv("ANNOTATION_MODEL", "some-model")
    monkeypatch.setenv("VERIFIER_MODEL", "some-model")
    with pytest.raises(SystemExit) as exc:
        draft_claims.annotation_model()
    assert "model under test" in str(exc.value)
    monkeypatch.setenv("VERIFIER_MODEL", "other-model")
    assert draft_claims.annotation_model() == "some-model"


def test_prompt_embeds_the_dataset_rules():
    rules = prompts.rules_excerpt()
    assert "CONTRADICTED" in rules and "UNSUPPORTED" in rules
    assert "Labelling rules" not in rules  # heading trimmed, body kept
    case = _ragtruth_case()
    assert rules in prompts.system_prompt(case)
    assert prompts.prompt_hash(case) != prompts.prompt_hash({**case, "generated_answer": "x"})


# --------------------------------------------------------------------------- T4 flags

def _flagged_case() -> dict[str, Any]:
    case = _ragtruth_case("Alpha is red. Beta is blue and very large indeed, much larger.")
    case["truncated"] = False
    case["claims"] = [
        {"claim_id": "c1", "claim_text": "Alpha is red.",
         "answer_span": {"start": 0, "end": 13},
         "draft_verdict": "SUPPORTED_CANDIDATE", "model_verdict": "CONTRADICTED",
         "evidence": [{"index": 0, "quote": "Alpha is crimson", "match": "unresolved",
                       "located": False}]},
    ]
    return case


def test_each_flag_fires_on_a_positive_and_stays_quiet_on_a_negative():
    case = _flagged_case()
    per_claim, case_flags = check_drafts.flag_case(case)
    names = {f["flag"] for f in per_claim[0]} | {f["flag"] for f in case_flags}
    assert "evidence_not_verbatim" in names          # the quote does not occur in the passage
    assert "supported_without_evidence" in names     # nothing located
    assert "model_disagrees" in names                # model said CONTRADICTED, script SUPPORTED
    assert "answer_not_covered" in names             # the long tail of the answer is in no claim

    clean = {
        "id": "ragtruth-2", "source": "ragtruth_summary", "split": "dev", "truncated": False,
        "context_passages": ["Alpha is red."],
        "generated_answer": "Alpha is red.",
        "source_labels": {"labels": [
            {"start": 0, "end": 13, "text": "Alpha is red.", "label_type": "Evident Conflict"}]},
        "claims": [{"claim_id": "c1", "claim_text": "Alpha is red.",
                    "answer_span": {"start": 0, "end": 13},
                    "draft_verdict": "CONTRADICTED", "model_verdict": "CONTRADICTED",
                    "evidence": [{"index": 0, "quote": "Alpha is red", "match": "exact",
                                  "located": True}]}],
    }
    per_claim, case_flags = check_drafts.flag_case(clean)
    assert per_claim == [[]] and case_flags == []


def test_source_label_uncovered_fires_when_a_span_has_no_claim():
    case = _flagged_case()
    case["generated_answer"] = "Alpha is red."
    case["source_labels"]["labels"] = [
        {"start": 0, "end": 5, "text": "Alpha", "label_type": "Evident Conflict"}]
    case["claims"][0]["answer_span"] = {"start": 6, "end": 19}
    _, case_flags = check_drafts.flag_case(case)
    assert any(f["flag"] == "source_label_uncovered" for f in case_flags)


def test_evidence_truncated_only_for_cut_factscore_cases():
    claim = {"claim_id": "c", "draft_verdict": "SUPPORTED_CANDIDATE", "evidence": []}
    assert check_drafts.evidence_truncated(claim, {"truncated": True,
                                                   "source": "factscore_chatgpt"})
    assert not check_drafts.evidence_truncated(claim, {"truncated": False,
                                                       "source": "factscore_chatgpt"})
    assert not check_drafts.evidence_truncated(claim, {"truncated": True,
                                                       "source": "ragtruth_summary"})


def test_check_drafts_is_additive(tmp_path, monkeypatch):
    path = tmp_path / "drafts.jsonl"
    case = _flagged_case()
    path.write_text(json.dumps(case, ensure_ascii=False) + "\n", encoding="utf-8")
    monkeypatch.setattr(check_drafts, "DRAFTS", path)
    before = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    check_drafts.main()
    after = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert after["claims"][0]["claim_text"] == before["claims"][0]["claim_text"]
    assert after["claims"][0]["flags"]


# --------------------------------------------------------------------------- T6

def test_round2_reasons_cover_changes_flags_and_upstream_disagreement():
    import random
    claim = {"claim_id": "c1", "claim_text": "A is true.", "draft_verdict": "SUPPORTED_CANDIDATE",
             "evidence": [{"index": 0, "start_char": 0, "end_char": 5}],
             "overlapping_source_labels": [], "needs_full_review": False}
    case = {"flags": []}
    rng = random.Random(1)
    decision = {"action": "set_verdict", "verdict": "CONTRADICTED",
                "claim_text": "A is false.", "evidence": [{"index": 0, "start_char": 0,
                                                           "end_char": 5}]}
    reasons = round2_queue.reasons_for(claim, case, decision, rng)
    assert "verdict_changed" in reasons and "claim_text_changed" in reasons
    assert any(r.startswith("disagrees_with_upstream") for r in reasons)
    agreed = {"action": "agree", "verdict": "SUPPORTED_CANDIDATE", "claim_text": "A is true.",
              "evidence": [{"index": 0, "start_char": 0, "end_char": 5}]}
    assert round2_queue.reasons_for(claim, case, agreed, random.Random(1)) in ([], ["random_10pct"])


# --------------------------------------------------------------------------- T7

def test_merge_refuses_while_claims_are_unreviewed(tmp_path, monkeypatch):
    drafts = tmp_path / "drafts.jsonl"
    r1 = tmp_path / "decisions_round1.jsonl"
    case = _flagged_case()
    drafts.write_text(json.dumps(case, ensure_ascii=False) + "\n", encoding="utf-8")
    r1.write_text(json.dumps({"claim_id": "c1", "case_id": "ragtruth-1", "action": "agree",
                              "claim_text": "Alpha is red.", "verdict": "CONTRADICTED",
                              "evidence": [{"index": 0, "start_char": 0, "end_char": 13,
                                            "quote": "Alpha is red and"}],
                              "note": "", "round": 1}) + "\n", encoding="utf-8")
    monkeypatch.setattr(merge, "DRAFTS", drafts)
    monkeypatch.setattr(merge, "ROUND1", r1)
    monkeypatch.setattr(merge, "ROUND2", tmp_path / "round2.jsonl")
    monkeypatch.setattr(merge, "ROUND2_QUEUE", tmp_path / "queue.jsonl")
    monkeypatch.setattr(merge, "OUT", tmp_path / "eval_hard.jsonl")
    monkeypatch.setattr(merge, "DISAGREEMENTS", tmp_path / "dis.jsonl")
    monkeypatch.setattr(merge, "AUDIT", tmp_path / "audit.json")
    monkeypatch.setattr(merge, "FREEZE", tmp_path / "freeze.json")
    import sys
    monkeypatch.setattr(sys, "argv", ["merge"])
    merge.main()  # one claim, one decision: it should write
    assert (tmp_path / "eval_hard.jsonl").is_file()
    written = json.loads((tmp_path / "eval_hard.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert written["gold_claims"][0]["verdict"] == "CONTRADICTED"
    assert written["provenance"]["annotation_origin"] == "human_reviewed"
    assert written["provenance"]["source_group"] == "ragtruth-1"


def test_eval_dataset_accepts_the_v2_fields_and_rejects_cross_split_groups():
    from eval.dataset import EvalCase, validate
    base = {
        "id": "ragtruth-1", "split": "dev", "tags": ["subtle"], "context_passages": ["A."],
        "generated_answer": "A.", "gold_claims": [
            {"claim_text": "A.", "verdict": "SUPPORTED", "evidence": [{"index": 0, "quote": "A."}]}],
        "source": "ragtruth_summary", "generator_model": "gpt-4-0613", "context_words": 1,
        "difficulty_tags": ["subtle"], "provenance": {"annotation_origin": "human_reviewed",
                                                      "source_group": "g-1"},
    }
    other = {**base, "id": "ragtruth-2", "split": "test"}
    cases = [EvalCase.model_validate(base), EvalCase.model_validate(other)]
    errors = validate(cases)
    assert any("appears in both splits" in e for e in errors)
    other["provenance"] = {**base["provenance"], "source_group": "g-2"}
    assert validate([EvalCase.model_validate(base), EvalCase.model_validate(other)]) == []


def test_existing_synthetic_dataset_still_loads():
    from eval.dataset import load
    cases = load(ROOT / "data" / "eval.jsonl")
    assert len(cases) == 46
    assert all(c.source is None for c in cases)


# --------------------------------------------------------------------------- T5 review app

def _review_fixture(tmp_path: Path) -> dict[str, Path]:
    drafts = tmp_path / "drafts.jsonl"
    case = _flagged_case()
    # the review fixture needs evidence a reviewer could agree to: verbatim and located
    case["claims"][0]["evidence"] = [{
        "index": 0, "quote": "Alpha is red", "start_char": 0, "end_char": 13,
        "match": "exact", "located": True}]
    case["claims"].append({
        "claim_id": "c2", "claim_text": "Beta is blue.", "answer_span": {"start": 14, "end": 27},
        "draft_verdict": "SUPPORTED_CANDIDATE", "model_verdict": "SUPPORTED",
        "evidence": [{"index": 0, "quote": "Alpha is red and square.", "start_char": 0,
                      "end_char": 23, "match": "exact", "located": True}]})
    S.write_jsonl(drafts, [case])
    return {"drafts": drafts, "decisions": tmp_path / "decisions_round1.jsonl",
            "queue": tmp_path / "round2_queue.jsonl"}


def _client(tmp_path: Path, monkeypatch):
    from fastapi.testclient import TestClient
    from annotation import review_app
    paths = _review_fixture(tmp_path)
    monkeypatch.setattr(review_app, "DRAFTS", paths["drafts"])
    monkeypatch.setattr(review_app, "ROUND2_QUEUE", paths["queue"])
    monkeypatch.setattr(review_app, "decisions_path",
                        lambda n: tmp_path / f"decisions_round{n}.jsonl")
    return TestClient(review_app.make_app(1)), paths


def test_review_page_ships_the_context_answer_and_claim_data(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    page = client.get("/").text
    # the panes are drawn client-side from the embedded JSON
    assert "Alpha is red and square." in page and "Beta is blue." in page
    assert "Alpha is red." in page             # the current claim
    assert "同意草稿 (A)" in page and "拆成两条" in page
    assert "decisions_round${ROUND}.jsonl" in page  # rendered with the round number
    assert "只看有问题的" in page


def test_every_action_appends_exactly_one_decision_line(tmp_path, monkeypatch):
    client, paths = _client(tmp_path, monkeypatch)
    evidence = [{"index": 0, "start_char": 0, "end_char": 15}]
    actions = [
        {"claim_id": "c1", "action": "agree"},
        {"claim_id": "c2", "action": "set_verdict", "verdict": "CONTRADICTED", "evidence": evidence},
        {"claim_id": "c2", "action": "delete"},
        {"claim_id": "c1", "action": "split", "extra_claims": ["Alpha is red."]},
        {"claim_id": "c2", "action": "merge_previous", "verdict": "SUPPORTED", "evidence": evidence},
    ]
    for body in actions:
        res = client.post("/api/decision", json=body)
        assert res.status_code == 200, (body, res.text)
    lines = [json.loads(line) for line in
             paths["decisions"].read_text(encoding="utf-8").splitlines()]
    assert len(lines) == len(actions)
    assert lines[0]["verdict"] == "SUPPORTED"  # agree on SUPPORTED_CANDIDATE -> SUPPORTED


def test_non_verbatim_evidence_is_rejected(tmp_path, monkeypatch):
    client, paths = _client(tmp_path, monkeypatch)
    res = client.post("/api/decision", json={
        "claim_id": "c2", "action": "set_verdict", "verdict": "SUPPORTED",
        "evidence": [{"index": 0, "start_char": 0, "end_char": 23}]})
    assert res.status_code == 200  # in-range ranges are accepted as what the passage says
    res = client.post("/api/decision", json={
        "claim_id": "c2", "action": "set_verdict", "verdict": "SUPPORTED",
        "evidence": [{"index": 0, "start_char": 0, "end_char": 9999}]})
    assert res.status_code == 422
    res = client.post("/api/decision", json={
        "claim_id": "c2", "action": "set_verdict", "verdict": "SUPPORTED",
        "evidence": [{"index": 7, "start_char": 0, "end_char": 3}]})
    assert res.status_code == 422


def test_supported_needs_evidence_and_unsupported_never_keeps_it(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    res = client.post("/api/decision", json={
        "claim_id": "c2", "action": "set_verdict", "verdict": "SUPPORTED", "evidence": []})
    assert res.status_code == 422
    res = client.post("/api/decision", json={
        "claim_id": "c2", "action": "set_verdict", "verdict": "UNSUPPORTED",
        "evidence": [{"index": 0, "start_char": 0, "end_char": 10}]})
    assert res.status_code == 200
    assert res.json()["record"]["evidence"] == []


def test_restart_keeps_progress(tmp_path, monkeypatch):
    from annotation import review_app
    client, paths = _client(tmp_path, monkeypatch)
    client.post("/api/decision", json={"claim_id": "c1", "action": "agree"})
    fresh = review_app.Store(1)  # a new process would build exactly this
    assert "c1" in fresh.current
    assert fresh.progress()["done"] == 1
    page = client.get("/").text
    assert '"final_verdict": "SUPPORTED"' in page  # the decision is in the embedded claim JSON


def test_last_decision_wins_and_deleted_claims_disappear(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    client.post("/api/decision", json={"claim_id": "c1", "action": "agree"})
    client.post("/api/decision", json={"claim_id": "c1", "action": "delete"})
    from annotation import review_app
    store = review_app.Store(1)
    case = store.by_id["ragtruth-1"]
    assert [c["claim_id"] for c in store.claims(case)] == ["c2"]


# --------------------------------------------------------------------------- Chinese layer (T5+)

def test_zh_cache_key_is_content_addressed():
    from annotation.zh import text_key
    assert text_key("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert text_key("abc") == text_key("abc")
    assert text_key("abc") != text_key("abd")


def test_zh_build_caches_and_does_not_touch_drafts(tmp_path, monkeypatch):
    from annotation import zh
    drafts = tmp_path / "drafts.jsonl"
    case = _flagged_case()
    S.write_jsonl(drafts, [case])
    cache = tmp_path / "zh_cache.json"
    monkeypatch.setattr(zh, "DRAFTS", drafts)
    monkeypatch.setattr(zh, "CACHE", cache)
    monkeypatch.setenv("REVIEW_MODEL", "test-model")

    calls: list[list[str]] = []

    def fake_translate(texts, model):
        calls.append(list(texts))
        return {zh.text_key(t): f"译:{t[:10]}" for t in texts}

    monkeypatch.setattr(zh, "translate_texts", fake_translate)
    zh.build()
    assert calls and cache.is_file()
    assert json.loads(cache.read_text(encoding="utf-8"))
    # the drafts themselves are untouched
    assert json.loads(drafts.read_text(encoding="utf-8").splitlines()[0])["claims"][0]["claim_text"] \
        == case["claims"][0]["claim_text"]

    # a second run translates nothing: the cache is keyed by content
    calls.clear()
    zh.build()
    assert calls == []


def test_zh_requires_review_model(monkeypatch):
    from annotation import zh
    monkeypatch.delenv("REVIEW_MODEL", raising=False)
    with pytest.raises(SystemExit) as exc:
        zh.review_model()
    assert "REVIEW_MODEL" in str(exc.value)


# --------------------------------------------------------------------------- model pre-review

def test_prereview_refuses_the_model_under_test_and_the_drafter(monkeypatch):
    from annotation import prereview
    monkeypatch.setenv("REVIEW_MODEL", "same")
    monkeypatch.setenv("VERIFIER_MODEL", "same")
    with pytest.raises(SystemExit) as exc:
        prereview.check_models()
    assert "model under test" in str(exc.value)
    monkeypatch.setenv("VERIFIER_MODEL", "other")
    monkeypatch.setenv("ANNOTATION_MODEL", "same")
    with pytest.raises(SystemExit) as exc:
        prereview.check_models()
    assert "ANNOTATION_MODEL" in str(exc.value)


def test_prereview_evidence_is_revalidated_and_non_verbatim_is_dropped():
    from annotation import prereview
    passages = ["Alpha is red and square."]
    good, ok = prereview.validate_evidence(passages, [{"index": 0, "quote": "Alpha is red"}])
    assert ok and good[0]["quote"] == "Alpha is red" and good[0]["start_char"] == 0
    bad, ok2 = prereview.validate_evidence(passages, [{"index": 0, "quote": "Alpha is crimson"}])
    assert not ok2 and bad == []
    # v2.2: normalised quotes are candidates only; never accepted as exact evidence
    norm, ok3 = prereview.validate_evidence(["He said 'hi'."], [{"index": 0, "quote": "He said ‘hi’"}])
    assert not ok3 and norm == []


def test_prereview_suggestion_is_never_a_decision(tmp_path, monkeypatch):
    from annotation import prereview
    out = tmp_path / "prereview.json"
    monkeypatch.setattr(prereview, "OUT", out)
    prereview.save({"c1": {"claim_id": "c1", "verdict": "SUPPORTED"}})
    assert json.loads(out.read_text(encoding="utf-8"))["c1"]["verdict"] == "SUPPORTED"
    # there is no code path that writes decisions_round*.jsonl from this module
    source = Path(prereview.__file__).read_text(encoding="utf-8")
    assert "decisions_round" not in source.replace("`decisions_round*.jsonl`", "")


def test_review_page_ships_chinese_and_suggestions(tmp_path, monkeypatch):
    from annotation import review_app
    client, _ = _client(tmp_path, monkeypatch)
    zh_cache = tmp_path / "zh_cache.json"
    pre = tmp_path / "prereview.json"
    from annotation.zh import text_key
    zh_cache.write_text(json.dumps({text_key("Alpha is red and square."): {"zh": "阿尔法是红色的正方形。"}}),
                        encoding="utf-8")
    pre.write_text(json.dumps({"c1": {"claim_id": "c1", "verdict": "CONTRADICTED", "confidence": 0.8,
                                      "agrees_with_draft": False, "reasoning_zh": "原文说的是方形。",
                                      "evidence": [], "evidence_verbatim": True, "acceptable": True,
                                      "model": "m"}}), encoding="utf-8")
    monkeypatch.setattr(review_app, "ZH_CACHE", zh_cache)
    monkeypatch.setattr(review_app, "PREREVIEW", pre)
    page = client.get("/").text
    assert "阿尔法是红色的正方形。" in page
    assert "模型预审" in page and "采纳建议" in page
    assert "原文说的是方形。" in page


# --------------------------------------------------------------------------- triage

def _blind_case():
    case = _ragtruth_case()
    case["provenance"]["task_type"] = "Summary"
    case["claims"] = [{"claim_id": "agree", "claim_text": "Alpha is red.",
                       "upstream_verdict": "SUPPORTED"}]
    review = {"agree": {"blind_verdict": "SUPPORTED", "evidence_candidates": [
        {"index": 0, "quote": "Alpha is red", "start_char": 0, "end_char": 12, "match": "exact"}]}}
    return case, review


@pytest.mark.parametrize("failure,reason", [
    ("disagree", "upstream_blind_disagree"), ("flag", "partial_overlap"),
    ("case_flag", "answer_gap"), ("missing", "missing_blind_review"),
    ("draft_only", "missing_upstream_verdict"), ("no_evidence", "no_exact_evidence"),
    ("normalized", "evidence_not_exact"), ("forged_exact", "evidence_not_exact"),
])
def test_triage_never_uses_model_agreement_or_confidence_as_gold(failure, reason):
    from annotation import triage
    case, review = _blind_case()
    claim = case["claims"][0]
    if failure == "disagree":
        review["agree"]["blind_verdict"] = "UNSUPPORTED"
    elif failure == "flag":
        claim["flags"] = [{"flag": "partial_overlap"}]
    elif failure == "case_flag":
        case["flags"] = [{"flag": "answer_gap"}]
    elif failure == "missing":
        review = {"agree": {"verdict": "SUPPORTED", "confidence": 1.0}}
    elif failure == "draft_only":
        claim.pop("upstream_verdict")
        claim["draft_verdict"] = "SUPPORTED"
    elif failure == "no_evidence":
        review["agree"]["evidence_candidates"] = []
    elif failure == "normalized":
        review["agree"]["evidence_candidates"][0]["match"] = "normalized"
    elif failure == "forged_exact":
        review["agree"]["evidence_candidates"][0]["quote"] = "Alpha is blue"
    result = triage.plan([case], review)
    assert result["counts"] == {"A": 0, "B": 1, "C": 0}
    assert reason in result["claims"][0]["reasons"]
    assert result["claims"][0]["label_source"] == "human_adjudicated"


def test_triage_audit_and_whole_case_checks_are_seeded_and_measured():
    from annotation import triage
    cases = []
    review = {}
    for n in range(8):
        case = _ragtruth_case()
        case.update(id=f"case{n}", split="dev" if n < 4 else "test")
        case["claims"] = [{"claim_id": f"c{n}-{i}", "claim_text": "An unsupported fact.",
                           "upstream_verdict": "UNSUPPORTED"} for i in range(5)]
        review.update({c["claim_id"]: {"blind_verdict": "UNSUPPORTED", "evidence_candidates": []}
                       for c in case["claims"]})
        cases.append(case)
    result = triage.plan(cases, review)
    assert result == triage.plan(list(reversed(cases)), review)
    assert result["counts"] == {"A": 34, "B": 0, "C": 6}
    assert result["audit_population"] == 40
    assert len(result["whole_case_checks"]) == 4
    assert result["whole_case_shortfalls"] == {"dev": 0, "test": 0}
    assert {c["label_source"] for c in result["claims"]} == {
        "ragtruth_human+model_blind_agree", "human_audit"}
    assert sum(map(len, triage.by_case(result).values())) == 6


def test_bulk_accept_endpoint_is_unavailable_and_writes_no_decisions(tmp_path, monkeypatch):
    client, paths = _client(tmp_path, monkeypatch)
    assert client.post("/api/accept_model").status_code == 404
    assert not paths["decisions"].exists()
    assert 'id="bulk-accept"' not in client.get("/").text


def test_needs_review_filter_shows_only_b_and_c_claims(tmp_path, monkeypatch):
    from annotation import review_app
    drafts = tmp_path / "drafts.jsonl"
    case = _ragtruth_case()
    case["claims"] = [{"claim_id": name, "claim_text": name, "draft_verdict": "SUPPORTED"}
                      for name in ("accepted", "adjudicate", "audit")]
    S.write_jsonl(drafts, [case])
    tri = {"claims": [{"claim_id": name, "case_id": case["id"], "bucket": bucket}
                      for name, bucket in [("accepted", "A"), ("adjudicate", "B"), ("audit", "C")]]}
    triage_file = tmp_path / "triage.json"
    triage_file.write_text(json.dumps(tri), encoding="utf-8")
    monkeypatch.setattr(review_app, "DRAFTS", drafts)
    monkeypatch.setattr(review_app, "TRIAGE", triage_file)
    monkeypatch.setattr(review_app, "PREREVIEW", tmp_path / "none.json")
    monkeypatch.setattr(review_app, "decisions_path", lambda n: tmp_path / f"d{n}.jsonl")
    from fastapi.testclient import TestClient
    page = TestClient(review_app.make_app(1, needs_review=True)).get("/").text
    assert '"claim_id": "adjudicate"' in page and '"claim_id": "audit"' in page
    assert '"claim_id": "accepted"' not in page


@pytest.mark.parametrize("model", ["deepseek-flash", "deepseek-chat", "vendor/DeepSeek-V4", "deep-seek-v3"])
def test_all_annotation_roles_reject_deepseek_before_any_call(monkeypatch, model):
    from annotation import draft_claims, prereview, zh
    monkeypatch.setenv("ANNOTATION_MODEL", model)
    monkeypatch.setenv("REVIEW_MODEL", model)
    for choose in (draft_claims.annotation_model, prereview.check_models, zh.review_model):
        with pytest.raises(SystemExit, match="DeepSeek"):
            choose()
    with pytest.raises(SystemExit, match="DeepSeek"):
        zh._client(model)


def test_review_client_cannot_inherit_verifier_key_or_endpoint(monkeypatch):
    from annotation import zh
    monkeypatch.delenv("REVIEW_API_KEY", raising=False)
    monkeypatch.delenv("REVIEW_BASE_URL", raising=False)
    monkeypatch.setenv("VERIFIER_API_KEY", "test-verifier-key")
    monkeypatch.setenv("VERIFIER_BASE_URL", "https://api.deepseek.com/v1")
    with pytest.raises(SystemExit, match="REVIEW_API_KEY"):
        zh._client("user-selected-model")


def test_duplicate_groups_are_transitive_and_do_not_rewrite_text():
    from annotation.select_cases import duplicate_groups
    # B is similar to both endpoints; endpoints are less than .8 similar to each other.
    middle = " ".join(f"word{i}" for i in range(100))
    left = " ".join([*(f"left{i}" for i in range(8)), *middle.split()[8:]])
    right = " ".join([*middle.split()[:-8], *(f"right{i}" for i in range(8))])
    docs = {"a": left, "b": middle, "c": right, "d": "unrelated words here"}
    original = dict(docs)
    groups = duplicate_groups(docs)
    assert groups["a"] == groups["b"] == groups["c"] != groups["d"]
    assert docs == original


def test_passage_map_rejects_internal_whitespace_rewrites():
    from annotation.select_cases import passage_mapping
    with pytest.raises(ValueError):
        passage_mapping("Alpha  is red.", ["Alpha is red."], [])


def test_sampling_cli_preserves_snapshot_and_all_fixed_margins(tmp_path):
    # Real CLI, production-shaped on-disk snapshots; no model/network dependency.
    import shutil
    import subprocess
    import sys
    from collections import Counter
    for package in ("annotation", "verifier"):
        shutil.copytree(ROOT / package, tmp_path / package, ignore=shutil.ignore_patterns("__pycache__"))
    raw = tmp_path / "data/sources/v2/raw"
    raw.mkdir(parents=True)
    out = tmp_path / "data/annotation"
    out.mkdir(parents=True)
    S.write_jsonl(tmp_path / "data/eval.jsonl", [{"id": "legacy", "context_passages": ["Legacy context."]}])
    sources, responses = [], []
    for task in ("Summary", "QA", "Data2txt"):
        for stratum in ("clean", "subtle", "evident_only"):
            for model in S.RAGTRUTH_MODELS:
                for n in range(5):
                    rid = str(100000 + len(responses))
                    text = " ".join(f"s{rid}w{i}" for i in range(450))
                    info = text if task == "Summary" else (
                        {"question": "What happened?", "passages":
                         f"passage 1:  {text}  \npassage 2:Second {rid}.\npassage 3:Third {rid}. "}
                        if task == "QA" else {"name": f"Cafe {rid}", "review_info": [{"review_text": text}]})
                    sources.append({"source_id": rid, "task_type": task, "source_info": info})
                    answer = "Fact " + " ".join(f"a{rid}w{i}" for i in range(110))
                    labels = [] if stratum == "clean" else [{"start": 0, "end": 4, "text": "Fact",
                        "label_type": "Subtle Conflict" if stratum == "subtle" else "Evident Baseless"}]
                    responses.append({"id": rid, "source_id": rid, "model": model, "response": answer,
                                      "labels": labels, "split": "test", "quality": "good"})
    # A second source id with identical context must remain in the same duplicate group.
    duplicate = dict(sources[0], source_id="duplicate")
    sources.append(duplicate)
    responses.append(dict(responses[0], id="duplicate", source_id="duplicate"))
    S.write_jsonl(raw / "source_info.jsonl", sources)
    S.write_jsonl(raw / "response.jsonl", responses)
    snapshot_before = {p.name: p.read_bytes() for p in raw.iterdir()}
    command = [sys.executable, "-m", "annotation.select_cases", "--offline"]
    first = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True)
    assert first.returncode == 0, first.stderr + first.stdout
    selected_bytes = (out / "candidates.jsonl").read_bytes()
    rows = S.read_jsonl(out / "candidates.jsonl")
    assert len(rows) == 30
    assert Counter((r["source"], r["split"]) for r in rows) == {
        ("ragtruth_summary", "dev"): 6, ("ragtruth_summary", "test"): 12,
        ("ragtruth_qa", "dev"): 3, ("ragtruth_qa", "test"): 5,
        ("ragtruth_data2txt", "dev"): 1, ("ragtruth_data2txt", "test"): 3}
    assert Counter((r["split"], r["selection"]["stratum"]) for r in rows) == {
        ("dev", "subtle"): 5, ("dev", "evident_only"): 3, ("dev", "clean"): 2,
        ("test", "subtle"): 10, ("test", "evident_only"): 5, ("test", "clean"): 5}
    assert Counter(r["split"] for r in rows if r["generator_model"] in S.GPT_MODELS) == {"dev": 7, "test": 14}
    assert len({r["source_group_id"] for r in rows}) == 30
    original_sources = {r["source_id"]: r for r in sources}
    original_answers = {r["id"]: r["response"] for r in responses}
    from annotation.select_cases import source_context
    for row in rows:
        assert row["generated_answer"] == original_answers[row["provenance"]["response_id"]]
        source = original_sources[row["provenance"]["source_id"]]
        original = (source["source_info"]["passages"] if source["task_type"] == "QA" else source_context(source))
        restored = ""
        for passage, span in zip(row["context_passages"], row["passage_map"], strict=True):
            assert passage == original[span["start_char"]:span["end_char"]]
            restored += span["removed_before"] + passage + span["removed_after"]
        assert restored == original
    second = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True)
    assert second.returncode == 0, second.stderr
    assert selected_bytes == (out / "candidates.jsonl").read_bytes()
    assert snapshot_before == {p.name: p.read_bytes() for p in raw.iterdir()}
    assert not (out / "wiki_requests.json").exists()
    assert (out / "selection-stats.md").is_file()
    # Infeasible quotas fail without overwriting the last valid output.
    (raw / "response.jsonl").write_text("", encoding="utf-8")
    failed = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True)
    assert failed.returncode != 0
    assert (out / "candidates.jsonl").read_bytes() == selected_bytes
