"""Pure metric functions over saved predictions. No LLM calls here."""
from __future__ import annotations

from collections import Counter, defaultdict
from statistics import mean

import re

from rapidfuzz import fuzz

from verifier.align import align_claims, span_overlap
from verifier.segment import split_answer

from .dataset import EvalCase

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


def compute(cases: list[EvalCase], preds: dict[str, dict], oracle: bool = False) -> dict:
    """preds: case_id -> VerifyResponse dict (with meta) or {"error": "..."}.
    oracle=True means preds were produced from gold claims in the same order (no alignment)."""
    ans_tp = ans_fp = ans_fn = ans_tn = 0
    confusion: dict[str, Counter] = {g: Counter() for g in LABELS}
    per_tag: dict[str, list[int]] = defaultdict(list)
    n_gold = n_pred = n_matched = 0
    cit_hit = cit_total = gold_ev_hit = gold_ev_total = 0
    cit_passage_hit = gold_ev_passage_hit = 0
    raw_total = raw_invalid = errors = 0
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

        # claim level
        gold_texts = [g.claim_text for g in case.gold_claims]
        if oracle:
            pairs = [(i, i, 100.0) for i in range(min(len(pclaims), len(gold_texts)))]
        else:
            pairs = align_claims([c["claim_text"] for c in pclaims], gold_texts)
        n_gold += len(gold_texts)
        n_pred += len(pclaims)
        n_matched += len(pairs)

        # decomposition shape, measured against the answer itself (no gold labels needed):
        # every answer sentence should be covered by some claim, and no claim should fuse two.
        sentences = split_answer(case.generated_answer)
        sent_total += len(sentences)
        for s in sentences:
            if any(fuzz.token_set_ratio(s.lower(), c["claim_text"].lower()) >= SENT_MATCH
                   for c in pclaims):
                sent_covered += 1
        fused_claims += _fused_claims([c["claim_text"] for c in pclaims], sentences)

        matched_gold = {g for _, g, _ in pairs}
        for gi, g in enumerate(case.gold_claims):  # unmatched gold claim = "MISSED"
            if gi not in matched_gold:
                confusion[g.verdict.value]["MISSED"] += 1
                for t in g.tags or case.tags:
                    per_tag[t].append(0)
        for pi, gi, _ in pairs:
            g, p = case.gold_claims[gi], pclaims[pi]
            confusion[g.verdict.value][p["verdict"]] += 1
            ok = int(g.verdict.value == p["verdict"])
            for t in g.tags or case.tags:
                per_tag[t].append(ok)
            # citations, only when gold and pred agree on a non-UNSUPPORTED verdict
            if ok and g.evidence:
                pspans = [(c["index"], c["start_char"], c["end_char"]) for c in p["citations"]]
                gspans = [_gold_span(case, e) for e in g.evidence]
                gold_idx = {e.index for e in g.evidence}
                cit_total += len(pspans)
                cit_hit += sum(any(span_overlap(ps, gs) > 0 for gs in gspans) for ps in pspans)
                # passage-level credit: cites the right passage, not necessarily the annotated span
                cit_passage_hit += sum(1 for ps in pspans if ps[0] in gold_idx)
                gold_ev_total += len(gspans)
                gold_ev_hit += sum(any(span_overlap(ps, gs) >= SPAN_HIT for ps in pspans)
                                   for gs in gspans)
                gold_ev_passage_hit += sum(1 for gs in gspans if any(ps[0] == gs[0] for ps in pspans))

    per_label = {}
    for lab in LABELS:
        tp = confusion[lab][lab]
        fp = sum(confusion[g][lab] for g in LABELS if g != lab)
        fn = sum(v for k, v in confusion[lab].items() if k != lab)
        per_label[lab] = dict(zip(("p", "r", "f1"), _prf(tp, fp, fn)))
    matched_total = sum(sum(v for k, v in confusion[g].items() if k != "MISSED") for g in LABELS)
    matched_correct = sum(confusion[g][g] for g in LABELS)
    srt = sorted(latencies)
    return {
        "n_cases": len(cases), "errors": errors,
        "answer_level": dict(zip(("p", "r", "f1"), _prf(ans_tp, ans_fp, ans_fn)))
        | {"acc": (ans_tp + ans_tn) / max(1, len(cases))},
        "decomposition": {"recall": n_matched / max(1, n_gold),
                          "precision": n_matched / max(1, n_pred)},
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
