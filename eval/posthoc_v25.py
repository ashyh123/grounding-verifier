"""Post-hoc analyses of the saved v2.5 test predictions. NOT preregistered; never calls a provider.

(a) Paired bootstrap of minimal-vs-optimized differences in hallucination-detection F1 and
    macro-F1. Each method's per-case confusion counts are summed over its 3 e2e rounds; both
    methods are scored on the SAME resampled case indices.
(b) Claim coverage: gold claims that were aligned to some prediction / all gold claims, per
    round, split by gold verdict S / C / U.

Reuses `eval.v25.case_counts` and `eval.v24.scores`.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from .dataset import load
from .v24 import LABELS, scores
from .v25 import case_counts

REPLICATES = 10000
SEED = 20261020
METRICS = {'hallucination_f1': 2, 'macro_f1': 3}
RUN_FILES = ('e2e-r1/{m}_run0.jsonl', 'e2e-r2-3/{m}_run0.jsonl', 'e2e-r2-3/{m}_run1.jsonl')


def read_predictions(path: Path) -> dict[str, dict]:
    rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    out = {r['id']: r for r in rows}
    if len(out) != len(rows):
        raise ValueError(f'duplicate prediction IDs in {path}')
    return out


def run_counts(cases, predictions: dict[str, dict]) -> np.ndarray:
    """(n_cases, 4, 4) confusion counts for one round, in `cases` order."""
    if set(predictions) != {c.id for c in cases}:
        raise ValueError('prediction IDs must equal the selected case IDs')
    return np.stack([case_counts(c, predictions[c.id]) for c in cases])


def paired_bootstrap(counts_a: np.ndarray, counts_b: np.ndarray, replicates: int = REPLICATES,
                     seed: int = SEED) -> dict:
    """counts_*: (n_cases, 4, 4), already summed over rounds. Reports A - B."""
    if counts_a.shape != counts_b.shape:
        raise ValueError('count arrays must cover the same cases')
    n = len(counts_a)
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, n, size=(replicates, n))  # one draw set shared by both methods
    sa, sb = scores(counts_a.sum(axis=0)), scores(counts_b.sum(axis=0))
    ra, rb = scores(counts_a[draws].sum(axis=1)), scores(counts_b[draws].sum(axis=1))
    out = {}
    for name, i in METRICS.items():
        low, high = np.percentile(ra[:, i] - rb[:, i], [2.5, 97.5])
        out[name] = {'a': float(sa[i]), 'b': float(sb[i]), 'diff': float(sa[i] - sb[i]),
                     'ci95': [float(low), float(high)],
                     'excludes_zero': bool(low > 0 or high < 0)}
    return out


def coverage(counts: np.ndarray) -> dict:
    """Aligned gold claims / all gold claims for one round, by gold verdict."""
    total = counts.sum(axis=0)
    out = {}
    for i, label in enumerate(LABELS):
        gold = int(total[i].sum())
        missed = int(total[i, 3])
        out[label] = {'gold': gold, 'aligned': gold - missed, 'missed': missed,
                      'coverage': (gold - missed) / gold if gold else None}
    gold = sum(v['gold'] for v in out.values())
    missed = sum(v['missed'] for v in out.values())
    out['all'] = {'gold': gold, 'aligned': gold - missed, 'missed': missed,
                  'coverage': (gold - missed) / gold if gold else None}
    return out


def analyse(cases, rounds: dict[str, list[np.ndarray]], replicates: int = REPLICATES,
            seed: int = SEED) -> dict:
    summed = {m: sum(r) for m, r in rounds.items()}
    return {
        'preregistered': False,
        'note': 'post-hoc analyses added after the v2.5 test results were seen',
        'bootstrap': {'unit': 'case', 'replicates': replicates, 'seed': seed,
                      'interval': 'percentile 2.5/97.5',
                      'counts': 'per-case confusion counts summed over all rounds of a method'},
        'n_cases': len(cases),
        'paired_difference_minimal_minus_optimized': {
            'preregistered': False,
            'rounds': {m: len(rounds[m]) for m in ('minimal', 'optimized')},
            **paired_bootstrap(summed['minimal'], summed['optimized'], replicates, seed)},
        'claim_coverage': {
            'preregistered': False,
            'per_method': {m: [coverage(c) for c in runs] for m, runs in rounds.items()}},
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--data', type=Path, default=Path('data/eval_hard.v2.5.jsonl'))
    ap.add_argument('--results', type=Path, default=Path('results/v2.5-test'))
    ap.add_argument('--out', type=Path, default=Path('results/v2.5-test/posthoc'))
    args = ap.parse_args()
    out_file = args.out / 'posthoc.json'
    if out_file.exists():
        raise SystemExit('STOP: report already exists; choose a new output path')
    cases = [c for c in load(args.data) if c.split == 'test']
    rounds = {'baseline': [run_counts(cases, read_predictions(args.results / 'e2e-r1/baseline_run0.jsonl'))]}
    for m in ('minimal', 'optimized'):
        rounds[m] = [run_counts(cases, read_predictions(args.results / f.format(m=m))) for f in RUN_FILES]
    report = analyse(cases, rounds)
    args.out.mkdir(parents=True, exist_ok=True)
    with out_file.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps(report['paired_difference_minimal_minus_optimized'], indent=1))
    for m, runs in report['claim_coverage']['per_method'].items():
        for k, c in enumerate(runs):
            print(m, f'r{k + 1}', {l: (v['aligned'], v['gold'], round(v['coverage'], 3)) for l, v in c.items()})


if __name__ == '__main__':
    main()
