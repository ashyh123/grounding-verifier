"""Pure metric functions over saved predictions. No LLM calls here."""
from __future__ import annotations

from collections import Counter, defaultdict
from statistics import mean

import re

from rapidfuzz import fuzz

from verifier.align import span_overlap
from verifier.segment import split_answer

from .dataset import EvalCase, GoldClaim
from .scoring import align_case, parent_verdict

LABELS = ["SUPPORTED", "CONTRADICTED", "UNSUPPORTED"]
SPAN_HIT = 0.5  # predicted citation "hits" gold evidence if it covers >= 50% of the gold span
SENT_MATCH = 60.0  # token_set_ratio at which a claim counts as covering an answer sentence
FUSION_MIN_WORDS = 2  # distinctive words a claim must inherit from a sentence to have fused it
STOPWORDS = set("""a an the of to in on for and or is are was were be been by with as at it its this
that these those from which when while than then into over via can may will not no does do
default by""".split())
_WORD = re.compile(r"[a-z0-9][a-z0-9\-_.]*")


def _content_words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in STOPWORDS}


def _fused_claims(claim_texts: list[str], sentences: list[str]) -> int:
    """Count claims that carry distinctive content of two different answer sentences.

    The earlier version of this metric asked "does the claim resemble >= 2 sentences?" (token-set ratio
    >= 60). That has a false-positive floor: the baseline splits the answer into sentences verbatim, so a
    claim is one sentence and cannot fuse anything, yet it scored 0.113 — about 11 % of its claims
    resembled two sentences anyway, because neighbouring sentences share vocabulary. Deciding on
    *distinctive* words instead — words that appear in exactly one of the answer's sentences — makes a
    whole-sentence claim score zero by construction, which is what a fusion detector owes its reader.
    """
    per_sentence = [_content_words(s) for s in sentences]
    counts: Counter = Counter()
    for words in per_sentence:
        counts.update(words)
    shared = {w for w, n in counts.items() if n > 1}  # vocabulary of the answer, not of one sentence
    distinctive = [words - shared for words in per_sentence]
    fused = 0
    for text in claim_texts:
        words = _content_words(text)
        carriers = [i for i, d in enumerate(distinctive) if len(words & d) >= FUSION_MIN_WORDS]
        fused += int(len(carriers) >= 2)
    return fused


def _prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def _gold_span(case: EvalCase, ev) -> tuple[int, int, int]:
    start = case.context_passages[ev.index].find(ev.quote)
    return ev.index, start, start + len(ev.quote)


def _label_scores(confusion: dict[str, Counter]) -> dict:
    scores = {}
    for lab in LABELS:
        tp = confusion[lab][lab]
        fp = sum(confusion[g][lab] for g in LABELS if g != lab)
        fn = sum(v for k, v in confusion[lab].items() if k != lab)
        scores[lab] = dict(zip(("p", "r", "f1"), _prf(tp, fp, fn)))
    return scores


def _group_keys(case: EvalCase, claim: GoldClaim) -> list[tuple[str, str]]:
    task = {"ragtruth_summary": "Summary", "ragtruth_qa": "QA",
            "ragtruth_data2txt": "Data2txt"}.get(case.source, "unknown")
    tags = set(case.tags + case.difficulty_tags)
    difficulty = ("subtle" if "subtle" in tags else "evident" if "evident" in tags
                  else "clean" if "clean" in tags else "unknown")
    words = len(" ".join(case.context_passages).split())
    length = "0-399" if words < 400 else "400-799" if words < 800 else "800+"
    return [("task", task), ("difficulty", difficulty), ("context_length_words", length),
            ("multi_passage", "true" if "multi_passage" in claim.tags else "false")]


def _group_summary(group: dict) -> dict:
    confusion = group["confusion"]
    gold = sum(sum(row.values()) for row in confusion.values())
    missed = sum(row["MISSED"] for row in confusion.values())
    correct = sum(confusion[lab][lab] for lab in LABELS)
    per_label = _label_scores(confusion)
    return {"n_cases": len(group["case_ids"]), "gold_claims": gold,
            "matched_pairs": gold - missed, "missed_gold": missed, "correct": correct,
            "claim_accuracy_all_gold": correct / max(1, gold),
            "claim_accuracy_matched": correct / max(1, gold - missed),
            "decomposition_recall": (gold - missed) / max(1, gold),
            "per_label": per_label, "macro_f1": mean(v["f1"] for v in per_label.values()),
            "confusion": {lab: dict(row) for lab, row in confusion.items()}}


def compute(cases: list[EvalCase], preds: dict[str, dict], oracle: bool = False) -> dict:
    """preds: case_id -> VerifyResponse dict (with meta) or {"error": "..."}.
    oracle=True means preds were produced from gold claims in the same order (no alignment)."""
    ans_tp = ans_fp = ans_fn = ans_tn = 0
    confusion: dict[str, Counter] = {g: Counter() for g in LABELS}
    per_tag: dict[str, list[int]] = defaultdict(list)
    n_gold = n_pred = n_matched = n_used = 0
    guard_rejected_pairs = duplicate_predictions = 0
    groups: dict[str, dict] = defaultdict(dict)
    cit_hit = cit_total = gold_ev_hit = gold_ev_total = 0
    cit_passage_hit = gold_ev_passage_hit = 0
    raw_total = raw_invalid = errors = 0
    scored_citation_invalid = 0
    sent_total = sent_covered = fused_claims = 0
    latencies, in_tok, out_tok, calls = [], [], [], []

    for case in cases:
        pred = preds.get(case.id)
        if pred is None or "error" in pred:
            errors += 1
            pred = {"claims": [], "meta": {}}
        pclaims = pred["claims"]
        meta = pred.get("meta") or {}
        latencies.append(meta.get("latency_ms", 0.0))
        in_tok.append(meta.get("input_tokens", 0))
        out_tok.append(meta.get("output_tokens", 0))
        calls.append(meta.get("llm_calls", 0))
        raw_total += meta.get("raw_citations_total", 0)
        raw_invalid += meta.get("raw_citations_invalid", 0)

        # answer level: positive class = "answer contains a hallucination"
        gold_bad = any(g.verdict.value != "SUPPORTED" for g in case.gold_claims)
        pred_bad = any(c["verdict"] != "SUPPORTED" for c in pclaims)
        ans_tp += gold_bad and pred_bad
        ans_fp += (not gold_bad) and pred_bad
        ans_fn += gold_bad and not pred_bad
        ans_tn += (not gold_bad) and not pred_bad

        # Gold denominators stay at parent level; prediction precision counts every used child.
        alignment = align_case(case, pclaims, oracle)
        guard_rejected_pairs += alignment.guard_rejected_pairs
        duplicate_predictions += alignment.duplicate_predictions
        n_gold += len(case.gold_claims)
        n_pred += len(pclaims)
        n_matched += len(alignment.matches)
        n_used += len(alignment.used_predictions)

        # decomposition shape, measured against the answer itself (no gold labels needed):
        # every answer sentence should be covered by some claim, and no claim should fuse two.
        sentences = split_answer(case.generated_answer)
        sent_total += len(sentences)
        for s in sentences:
            if any(fuzz.token_set_ratio(s.lower(), c["claim_text"].lower()) >= SENT_MATCH
                   for c in pclaims):
                sent_covered += 1
        fused_claims += _fused_claims([c["claim_text"] for c in pclaims], sentences)

        for gi, g in enumerate(case.gold_claims):
            indices = alignment.matches.get(gi)
            predicted_label = parent_verdict(pclaims, indices) if indices else "MISSED"
            ok = int(g.verdict.value == predicted_label)
            confusion[g.verdict.value][predicted_label] += 1
            for t in g.tags or case.tags:
                per_tag[t].append(ok)
            for dimension, name in _group_keys(case, g):
                group = groups[dimension].setdefault(name, {
                    "case_ids": set(), "confusion": {lab: Counter() for lab in LABELS}})
                group["case_ids"].add(case.id)
                group["confusion"][g.verdict.value][predicted_label] += 1
            if ok:
                # Keep attribution: a split output may cite only its own unit's reference spans.
                # Whole-parent/oracle outputs are compared with all approved evidence for that parent.
                units = case._scoring_units.get(gi)
                parent_evidence = [e for unit in units for e in unit.evidence] if units else g.evidence
                gold_matches: dict[tuple[int, int, int], list[tuple[int, int, int]]] = {}
                for pi in indices:
                    evidence = (alignment.matched_units[pi].evidence
                                if pi in alignment.matched_units else parent_evidence)
                    gspans = {_gold_span(case, e) for e in evidence}
                    for gs in gspans:
                        gold_matches.setdefault(gs, [])
                    # Deduplicate within each predicted claim, preserving cross-claim attribution.
                    citations = {(c.get("index"), c.get("start_char"), c.get("end_char"), c.get("quote"))
                                 for c in pclaims[pi]["citations"]}
                    for index, start, end, quote in citations:
                        cit_total += 1
                        valid = (type(index) is int and 0 <= index < len(case.context_passages)
                                 and type(start) is int and type(end) is int
                                 and 0 <= start < end <= len(case.context_passages[index])
                                 and isinstance(quote, str) and bool(quote.strip())
                                 and case.context_passages[index][start:end] == quote)
                        if not valid:
                            scored_citation_invalid += 1
                            continue
                        ps = (index, start, end)
                        cit_hit += any(span_overlap(ps, gs) > 0 for gs in gspans)
                        cit_passage_hit += any(index == gs[0] for gs in gspans)
                        for gs in gspans:
                            gold_matches[gs].append(ps)
                gold_ev_total += len(gold_matches)
                gold_ev_hit += sum(any(span_overlap(ps, gs) >= SPAN_HIT for ps in spans)
                                   for gs, spans in gold_matches.items())
                gold_ev_passage_hit += sum(any(ps[0] == gs[0] for ps in spans)
                                          for gs, spans in gold_matches.items())

    per_label = _label_scores(confusion)
    matched_total = sum(sum(v for k, v in confusion[g].items() if k != "MISSED") for g in LABELS)
    matched_correct = sum(confusion[g][g] for g in LABELS)
    srt = sorted(latencies)
    return {
        "n_cases": len(cases), "errors": errors,
        "answer_level": dict(zip(("p", "r", "f1"), _prf(ans_tp, ans_fp, ans_fn)))
        | {"acc": (ans_tp + ans_tn) / max(1, len(cases))},
        "decomposition": {"recall": n_matched / max(1, n_gold),
                          "precision": n_used / max(1, n_pred),
                          "gold_claims": n_gold, "predicted_claims": n_pred,
                          "matched_pairs": n_matched, "used_predictions": n_used,
                          "missed_gold": n_gold - n_matched,
                          "extra_predictions": n_pred - n_used,
                          "duplicate_predictions": duplicate_predictions,
                          "added_predictions": n_pred - n_used - duplicate_predictions},
        "guard_rejected_pairs": guard_rejected_pairs,
        "scoring_units_registry_sha256": cases[0]._scoring_registry_sha256 if cases else None,
        "groups": {dimension: {name: _group_summary(group) for name, group in sorted(values.items())}
                   for dimension, values in sorted(groups.items())},
        # Shape of the decomposition, independent of the gold labels: does every sentence of the
        # answer reach the verifier, and does any claim conflate several sentences into one?
        "sentence_coverage": sent_covered / max(1, sent_total),
        "fused_claim_rate": fused_claims / max(1, n_pred),
        "claim_accuracy_matched": matched_correct / max(1, matched_total),
        "claim_accuracy_all_gold": matched_correct / max(1, n_gold),
        "macro_f1": mean(v["f1"] for v in per_label.values()),
        "per_label": per_label,
        "confusion": {g: dict(c) for g, c in confusion.items()},
        "per_tag_accuracy": {t: round(mean(v), 3) for t, v in sorted(per_tag.items())},
        "citation_counts": {"predicted": cit_total, "hit": cit_hit, "gold": gold_ev_total,
                            "gold_hit": gold_ev_hit, "invalid": scored_citation_invalid},
        "citation_precision": cit_hit / max(1, cit_total),
        "citation_recall": gold_ev_hit / max(1, gold_ev_total),
        # Same question, looser bar: is the cited passage one of the annotated evidence passages?
        # The strict numbers penalise a verifier for citing a different sentence of the right
        # passage, which is often exactly what a per-sentence verifier does.
        "citation_passage_precision": cit_passage_hit / max(1, cit_total),
        "citation_passage_recall": gold_ev_passage_hit / max(1, gold_ev_total),
        "raw_citation_invalid_rate": raw_invalid / max(1, raw_total),
        "latency_ms_p50": srt[len(srt) // 2] if srt else 0.0,
        "latency_ms_p95": srt[min(len(srt) - 1, int(0.95 * len(srt)))] if srt else 0.0,
        "avg_llm_calls": mean(calls) if calls else 0.0,
        "avg_input_tokens": mean(in_tok) if in_tok else 0.0,
        "avg_output_tokens": mean(out_tok) if out_tok else 0.0,
    }
