"""Preregistered v2.5 metrics over saved predictions; never calls a verifier/provider.

Extends the v2.4 report with the `subtle_supplement` subset, a preregistered sensitivity
analysis that removes claims whose doubt category is `suspected_wrong_label` or
`c_vs_u_boundary`, and evident/subtle and generator-model groupings.

Alignment is inherited; unmatched predictions count as false positives, missing gold as false
negatives. Bootstrap resamples whole cases. Filtered reports ignore predictions that were
matched only to removed claims, so a dropped claim cannot reappear as a false positive.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from .dataset import EvalCase, load
from .scoring import align_case, parent_verdict
from .v24 import LABELS, BOOTSTRAP_REPLICATES, BOOTSTRAP_SEED, summarize

SUBSETS = ('all', 'natural', 'conflict_supplement', 'subtle_supplement')
ORIGINS = ('evident', 'subtle', 'clean')
SENSITIVE = {'suspected_wrong_label', 'c_vs_u_boundary'}


def origin(raw_claim: dict) -> str:
    types = [label['label_type'] for label in raw_claim.get('overlapping_source_labels') or []]
    if any(name.startswith('Subtle') for name in types):
        return 'subtle'
    if any(name.startswith('Evident') for name in types):
        return 'evident'
    return 'clean'


def case_counts(case: EvalCase, prediction: dict, oracle: bool = False,
                claim_ids: list[str] | None = None, keep=None) -> np.ndarray:
    # Rows: gold S/C/U/EXTRA; columns: prediction S/C/U/MISSED.
    counts = np.zeros((4, 4), dtype=np.int64)
    claims = [] if 'error' in prediction else prediction['claims']
    if any(p['verdict'] not in LABELS for p in claims):
        raise ValueError('prediction has an unknown verdict')
    alignment = align_case(case, claims, oracle)
    ids = claim_ids or [str(i) for i in range(len(case.gold_claims))]
    for gi, gold in enumerate(case.gold_claims):
        if keep is not None and not keep(gi, ids[gi]):
            continue
        indices = alignment.matches.get(gi)
        predicted = LABELS.index(parent_verdict(claims, indices)) if indices else 3
        counts[LABELS.index(gold.verdict.value), predicted] += 1
    # A prediction matched to a removed claim disappears with it; only never-matched
    # predictions remain false positives.
    for pi, claim in enumerate(claims):
        if pi not in alignment.used_predictions:
            counts[3, LABELS.index(claim['verdict'])] += 1
    return counts


def _summary(rows: list[tuple[EvalCase, dict, dict]], keep, oracle: bool) -> dict:
    counts = []
    for case, prediction, raw in rows:
        ids = [gold['claim_id'] for gold in raw['gold_claims']]
        if any(keep(i, ids[i]) for i in range(len(ids))):
            counts.append(case_counts(case, prediction, oracle, ids, keep))
    return summarize(counts)


def compute(cases: list[EvalCase], subsets: dict[str, str], predictions: dict[str, dict],
            raw_by_id: dict[str, dict], sensitive_ids: set[str], oracle: bool = False) -> dict:
    if set(predictions) != {case.id for case in cases}:
        raise ValueError('prediction IDs must equal selected dataset IDs; use explicit error records for failures')
    if any(subsets.get(case.id) not in SUBSETS[1:] for case in cases):
        raise ValueError('every v2.5 case requires its registered subset')
    rows = [(case, predictions[case.id], raw_by_id[case.id]) for case in cases]
    for case, _prediction, raw in rows:
        if len(case.gold_claims) != len(raw['gold_claims']):
            raise ValueError(f'{case.id}: raw and validated gold claim counts differ')
    claim_by_id = {gold['claim_id']: gold for _case, _prediction, raw in rows
                   for gold in raw['gold_claims']}
    dropped = sorted(sensitive_ids & set(claim_by_id))
    keep_all = lambda _index, _claim_id: True
    keep_sensitive = lambda _index, claim_id: claim_id not in sensitive_ids

    def subset_rows(name):
        return [row for row in rows if name == 'all' or subsets[row[0].id] == name]

    reports = {name: _summary(subset_rows(name), keep_all, oracle) for name in SUBSETS}
    sensitivity = {name: _summary(subset_rows(name), keep_sensitive, oracle) for name in SUBSETS}

    by_origin = {}
    for name in ORIGINS:
        origin_rows = []
        for case, prediction, raw in rows:
            def keep(index, _claim_id, raw=raw, name=name):
                return origin(raw['gold_claims'][index]) == name
            ids = [gold['claim_id'] for gold in raw['gold_claims']]
            if any(keep(i, ids[i]) for i in range(len(ids))):
                origin_rows.append((case, prediction, raw, keep))
        by_origin[name] = {
            'primary': summarize([
                case_counts(case, prediction, oracle,
                            [gold['claim_id'] for gold in raw['gold_claims']], keep)
                for case, prediction, raw, keep in origin_rows]),
            'sensitivity': summarize([
                case_counts(case, prediction, oracle,
                            [gold['claim_id'] for gold in raw['gold_claims']],
                            lambda index, claim_id, keep=keep: (keep(index, claim_id)
                                                                and claim_id not in sensitive_ids))
                for case, prediction, raw, keep in origin_rows]),
        }

    by_generator = {}
    for generator in sorted({case.generator_model or 'unknown' for case in cases}):
        generator_rows = [row for row in rows
                          if (row[0].generator_model or 'unknown') == generator]
        by_generator[generator] = {
            'primary': _summary(generator_rows, keep_all, oracle),
            'sensitivity': _summary(generator_rows, keep_sensitive, oracle),
        }
    return {'design_version': '2.5', 'oracle': oracle,
            'preregistration': {
                'subset': 'subtle_supplement added; all other subsets unchanged',
                'sensitivity': 'remove claims whose doubt_category is suspected_wrong_label or c_vs_u_boundary',
                'groups': 'by_origin uses the most specific upstream fragment type: subtle > evident > clean',
                'bootstrap': {'unit': 'case', 'replicates': BOOTSTRAP_REPLICATES,
                              'seed': BOOTSTRAP_SEED, 'interval': 'percentile 2.5/97.5'}},
            'errors': sum('error' in prediction for prediction in predictions.values()),
            'dropped_sensitive_claims': dropped,
            'dropped_sensitive_by_label': {
                label: sum(claim_by_id[claim_id]['verdict'] == label for claim_id in dropped)
                for label in LABELS},
            'reports': reports, 'sensitivity': sensitivity,
            'groups': {'by_origin': by_origin, 'by_generator_model': by_generator}}


def read_doubts(path: Path) -> tuple[set[str], list[dict]]:
    if not path.exists():
        return set(), []
    rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    sensitive = {row['claim_id'] for row in rows if row.get('category') in SENSITIVE}
    return sensitive, rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--data', type=Path, default=Path('data/eval_hard.v2.5.jsonl'))
    ap.add_argument('--predictions', type=Path, required=True)
    ap.add_argument('--split', choices=['dev', 'test', 'all'], default='test')
    ap.add_argument('--oracle', action='store_true')
    ap.add_argument('--doubts', type=Path, default=Path('data/annotation/v2.5/doubt_classes.jsonl'))
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    if args.out.exists():
        raise SystemExit('STOP: report already exists; choose a new output path')
    raw_rows = [json.loads(line) for line in args.data.read_text().splitlines() if line.strip()]
    raw_by_id = {row['id']: row for row in raw_rows}
    cases = [case for case in load(args.data) if args.split == 'all' or case.split == args.split]
    predictions = {}
    for line in args.predictions.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            if row['id'] in predictions:
                raise ValueError('duplicate prediction IDs')
            predictions[row['id']] = row
    sensitive, doubt_rows = read_doubts(args.doubts)
    report = compute(cases, {case.id: raw_by_id[case.id]['subset'] for case in cases},
                     predictions, raw_by_id, sensitive, args.oracle)
    report.update(split=args.split, dataset_sha256=hashlib.sha256(args.data.read_bytes()).hexdigest(),
                  predictions_sha256=hashlib.sha256(args.predictions.read_bytes()).hexdigest(),
                  doubt_classes_sha256=(hashlib.sha256(args.doubts.read_bytes()).hexdigest()
                                        if args.doubts.exists() else None),
                  doubt_classes=len(doubt_rows))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    for subset, part in report['reports'].items():
        if part['n_cases']:
            print(subset, 'n=', part['n_cases'], 'hallucination=', part['hallucination_detection'],
                  'macro_f1=', part['macro_f1'])
    print('sensitivity dropped', len(report['dropped_sensitive_claims']))


if __name__ == '__main__':
    main()
