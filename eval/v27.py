"""v2.7 metrics: RAGTruth++ sentence/answer sensitivity (track B) and AggreFact oracle (track A).

Track B stores two sentence golds per answer: loose (RAGTruth original) and strict (RAGTruth++).
The metrics themselves are the v2.6 definitions; this module only builds the two case views and
adds a paired sentence-F1 bootstrap. No provider calls.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from . import v26

BOOTSTRAP_SEED = 20261024
THRESHOLD = 60.0
SCORER = 'token_set_ratio'
BAD = v26.BAD


def load_rows(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines()
            if line.strip()]
    if not rows:
        raise SystemExit(f'{path}: no rows')
    ids = [r['id'] for r in rows]
    if len(ids) != len(set(ids)):
        raise SystemExit(f'{path}: duplicate ids')
    for row in rows:
        for key in ('gold_response', 'gold_sentences', 'loose_gold_response',
                    'loose_gold_sentences'):
            if key not in row:
                raise SystemExit(f"{row['id']}: missing {key}")
        if row['gold_response'] != bool(row['source_labels']['labels']):
            raise SystemExit(f"{row['id']}: strict gold flag disagrees with strict spans")
        if row['loose_gold_response'] != bool(row['loose_source_labels']['labels']):
            raise SystemExit(f"{row['id']}: loose gold flag disagrees with loose spans")
        if ''.join(s['text'] for s in row['gold_sentences']) != row['generated_answer']:
            raise SystemExit(f"{row['id']}: strict sentences do not tile the answer")
        if ''.join(s['text'] for s in row['loose_gold_sentences']) != row['generated_answer']:
            raise SystemExit(f"{row['id']}: loose sentences do not tile the answer")
    return rows


def selected(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r['selection']['selected']]


def case(row: dict, standard: str) -> v26.Case:
    if standard == 'strict':
        gold, sentences, labels = row['gold_response'], row['gold_sentences'], row['source_labels']['labels']
    elif standard == 'loose':
        gold, sentences, labels = (row['loose_gold_response'], row['loose_gold_sentences'],
                                   row['loose_source_labels']['labels'])
    else:
        raise ValueError(standard)
    return v26.Case(id=row['id'], task=row['task'], generator_model=row['generator_model'],
                    answer=row['generated_answer'], passages=row['context_passages'],
                    gold_response=gold, gold_sentences=sentences, labels=labels,
                    context_words=len(' '.join(row['context_passages']).split()))


def read_predictions(path: Path) -> dict[str, dict]:
    return v26.read_predictions(path)


def sentence_f1(counts: np.ndarray) -> np.ndarray:
    tp, fp, fn = (counts[..., i].astype(float) for i in range(3))
    denom = 2 * tp + fp + fn
    return np.where(denom == 0, np.nan, 2 * tp / np.where(denom == 0, 1, denom))


def paired_sentence_f1(rows: list[dict], predictions: dict[str, dict[str, dict]],
                       standard: str, replicates: int = v26.BOOTSTRAP_REPLICATES) -> dict:
    """optimized minus minimal sentence F1 on the same resampled answers."""
    cases = [case(r, standard) for r in rows]
    a, b = 'optimized', 'minimal'
    if a not in predictions or b not in predictions:
        return {'n_cases': 0, 'statement': 'missing method'}
    ma = np.stack([v26.sentence_vector(c, predictions[a].get(c.id), THRESHOLD, SCORER) for c in cases])
    mb = np.stack([v26.sentence_vector(c, predictions[b].get(c.id), THRESHOLD, SCORER) for c in cases])
    draws = v26._draws(len(cases), replicates, BOOTSTRAP_SEED)
    sa, sb = sentence_f1(ma.sum(axis=0)), sentence_f1(mb.sum(axis=0))
    ra, rb = sentence_f1(ma[draws].sum(axis=1)), sentence_f1(mb[draws].sum(axis=1))
    diff = ra - rb
    block = v26.interval(sa - sb, diff)
    low, high = block['ci95']
    block['a'], block['b'] = v26._num(sa), v26._num(sb)
    block['excludes_zero'] = None if low is None else bool(low > 0 or high < 0)
    block['statement'] = v26.wording('optimized', 'minimal', block)
    return {'n_cases': len(cases), 'standard': standard, 'f1': block}


def track_b_report(rows: list[dict], predictions: dict[str, dict[str, dict]],
                   price_in: float = 0.0, price_out: float = 0.0) -> dict:
    sel = selected(rows)
    strict_cases = [case(r, 'strict') for r in sel]
    loose_cases = [case(r, 'loose') for r in sel]
    reports = {}
    for standard, cases in (('strict', strict_cases), ('loose', loose_cases)):
        reports[standard] = v26.compute(cases, predictions, THRESHOLD, SCORER, price_in, price_out)
        reports[standard]['paired_sentence_f1'] = paired_sentence_f1(sel, predictions, standard)
    return {
        'design_version': '2.7', 'track': 'ragtruthpp', 'n_rows': len(rows),
        'n_selected': len(sel), 'n_reused': sum(bool(r['selection']['reuse_v26_prediction']) for r in sel),
        'n_new': sum(not r['selection']['reuse_v26_prediction'] for r in sel),
        'sentence_threshold': THRESHOLD, 'bootstrap_seed': BOOTSTRAP_SEED,
        'standards': reports,
        'rules': 'data/annotation/v2.7/rules.json',
        'dataset_sha256': hashlib.sha256(Path('data/eval_ragtruthpp.v2.7.jsonl').read_bytes()).hexdigest(),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--data', type=Path, default=Path('data/eval_ragtruthpp.v2.7.jsonl'))
    ap.add_argument('--predictions', type=Path, required=True,
                    help='directory holding <method>_run0.jsonl')
    ap.add_argument('--methods', nargs='+', default=['baseline', 'minimal', 'optimized'])
    ap.add_argument('--price-in', type=float, default=0.0)
    ap.add_argument('--price-out', type=float, default=0.0)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    rows = load_rows(args.data)
    preds = {m: read_predictions(args.predictions / f'{m}_run0.jsonl') for m in args.methods}
    report = track_b_report(rows, preds, args.price_in, args.price_out)
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / 'v27_report.json'
    if path.exists():
        raise SystemExit('STOP: report already exists')
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    for standard in ('strict', 'loose'):
        print(standard)
        for m in args.methods:
            x = report['standards'][standard]['methods'][m]
            a = x['answer_level']['main']['metrics']
            s = x['sentence_level']['main']
            print(f"  {m}: answer BAcc={a['balanced_accuracy']['value']:.3f} "
                  f"sentence F1={s['metrics']['f1']['value']:.3f} failures={x['failures']}")
        pair = report['standards'][standard]['paired_sentence_f1']
        print('  ', pair.get('f1', {}).get('statement', pair.get('statement')))


if __name__ == '__main__':
    main()
