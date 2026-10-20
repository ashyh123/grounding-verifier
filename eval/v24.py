"""Preregistered v2.4 metrics over saved predictions; never calls a verifier/provider.

Preserves historical scoring modules. Alignment is inherited; unmatched predictions count
as false positives, missing gold as false negatives. Bootstrap resamples whole cases.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from .dataset import EvalCase, load
from .scoring import align_case, parent_verdict

LABELS = ('SUPPORTED', 'CONTRADICTED', 'UNSUPPORTED')
SUBSETS = ('all', 'natural', 'conflict_supplement')
BOOTSTRAP_REPLICATES = 10000
BOOTSTRAP_SEED = 20261020


def case_counts(case: EvalCase, prediction: dict, oracle: bool = False) -> np.ndarray:
    # Rows: gold S/C/U/EXTRA; columns: prediction S/C/U/MISSED.
    counts = np.zeros((4, 4), dtype=np.int64)
    claims = [] if 'error' in prediction else prediction['claims']
    if any(p['verdict'] not in LABELS for p in claims):
        raise ValueError('prediction has an unknown verdict')
    alignment = align_case(case, claims, oracle)
    for gi, gold in enumerate(case.gold_claims):
        indices = alignment.matches.get(gi)
        predicted = LABELS.index(parent_verdict(claims, indices)) if indices else 3
        counts[LABELS.index(gold.verdict.value), predicted] += 1
    for pi, claim in enumerate(claims):
        if pi not in alignment.used_predictions:
            counts[3, LABELS.index(claim['verdict'])] += 1
    return counts


def scores(counts: np.ndarray) -> np.ndarray:
    """Last axis: hallucination P/R/F1, macro-F1, S P/R/F1, C P/R/F1, U P/R/F1."""
    def prf(tp, fp, fn):
        p = np.divide(tp, tp + fp, out=np.zeros_like(tp, dtype=float), where=tp + fp != 0)
        r = np.divide(tp, tp + fn, out=np.zeros_like(tp, dtype=float), where=tp + fn != 0)
        f = np.divide(2 * tp, 2 * tp + fp + fn, out=np.zeros_like(tp, dtype=float),
                      where=2 * tp + fp + fn != 0)
        return p, r, f
    tp = counts[..., 1:3, 1:3].sum(axis=(-2, -1))
    fp = counts[..., (0, 3), 1:3].sum(axis=(-2, -1))
    fn = counts[..., 1:3, (0, 3)].sum(axis=(-2, -1))
    binary = prf(tp, fp, fn)
    per_label = []
    for i in range(3):
        correct = counts[..., i, i]
        per_label.append(prf(correct, counts[..., :, i].sum(axis=-1) - correct,
                             counts[..., i, :].sum(axis=-1) - correct))
    macro = np.mean([row[2] for row in per_label], axis=0)
    return np.stack([*binary, macro, *(v for row in per_label for v in row)], axis=-1)


def summarize(counts: list[np.ndarray]) -> dict:
    if not counts:
        return {'n_cases': 0, 'gold_claims': 0, 'metrics': None, 'reason': 'empty subset'}
    array = np.stack(counts)
    total = array.sum(axis=0)
    point = scores(total)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    # Index arrays preserve multiplicity: sampling a case twice doubles all its claims.
    draws = rng.integers(0, len(array), size=(BOOTSTRAP_REPLICATES, len(array)))
    sampled = scores(array[draws].sum(axis=1))
    low, high = np.percentile(sampled, [2.5, 97.5], axis=0)
    def metric(i):
        return {'value': float(point[i]), 'ci95': [float(low[i]), float(high[i])]}
    return {'n_cases': len(array), 'gold_claims': int(total[:3].sum()),
            'extra_predictions': int(total[3].sum()),
            'missed_gold': int(total[:3, 3].sum()),
            'confusion': {lab: {pred: int(total[i, j]) for j, pred in enumerate((*LABELS, 'MISSED'))}
                          for i, lab in enumerate((*LABELS, 'EXTRA'))},
            'hallucination_detection': {name: metric(i) for i, name in enumerate(('p', 'r', 'f1'))},
            'macro_f1': metric(3),
            'per_label': {lab: {'n': int(total[i].sum()),
                               'note': '仅供参考' if total[i].sum() < 20 else '',
                               **{name: metric(4 + 3 * i + j) for j, name in enumerate(('p', 'r', 'f1'))}}
                          for i, lab in enumerate(LABELS)}}


def compute(cases: list[EvalCase], subsets: dict[str, str], predictions: dict[str, dict], oracle=False) -> dict:
    if set(predictions) != {c.id for c in cases}:
        raise ValueError('prediction IDs must equal selected dataset IDs; use explicit error records for failures')
    if any(subsets.get(c.id) not in SUBSETS[1:] for c in cases):
        raise ValueError('every v2.4 case requires its registered subset')
    rows = [(c, case_counts(c, predictions[c.id], oracle)) for c in cases]
    return {'design_version': '2.4', 'oracle': oracle,
            'bootstrap': {'unit': 'case', 'replicates': BOOTSTRAP_REPLICATES,
                          'seed': BOOTSTRAP_SEED, 'interval': 'percentile 2.5/97.5'},
            'errors': sum('error' in p for p in predictions.values()),
            'reports': {subset: summarize([row for c, row in rows
                                          if subset == 'all' or subsets[c.id] == subset])
                        for subset in SUBSETS}}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--data', type=Path, default=Path('data/eval_hard.v2.4.jsonl'))
    ap.add_argument('--predictions', type=Path, required=True)
    ap.add_argument('--split', choices=['dev', 'test', 'all'], default='test')
    ap.add_argument('--oracle', action='store_true')
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    if args.out.exists():
        raise SystemExit('STOP: report already exists; choose a new output path')
    raw = [json.loads(l) for l in args.data.read_text().splitlines() if l.strip()]
    cases = [c for c in load(args.data) if args.split == 'all' or c.split == args.split]
    rows = [json.loads(l) for l in args.predictions.read_text().splitlines() if l.strip()]
    predictions = {r['id']: r for r in rows}
    if len(predictions) != len(rows):
        raise ValueError('duplicate prediction IDs')
    report = compute(cases, {c['id']: c['subset'] for c in raw}, predictions, args.oracle)
    report.update(split=args.split, dataset_sha256=hashlib.sha256(args.data.read_bytes()).hexdigest(),
                  predictions_sha256=hashlib.sha256(args.predictions.read_bytes()).hexdigest())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2); stream.write('\n')
    for subset, part in report['reports'].items():
        if part['n_cases']:
            print(subset, 'n=', part['n_cases'], 'hallucination=', part['hallucination_detection'],
                  'macro_f1=', part['macro_f1'])


if __name__ == '__main__':
    main()
