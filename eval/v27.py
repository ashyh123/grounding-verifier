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


def load_aggrefact(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines()
            if line.strip()]
    ids = [r['id'] for r in rows]
    if len(ids) != len(set(ids)):
        raise SystemExit(f'{path}: duplicate ids')
    for row in rows:
        if len(row['claims']) != len(row['labels']):
            raise SystemExit(f"{row['id']}: claims and labels differ")
        if set(row['labels']) - {0, 1}:
            raise SystemExit(f"{row['id']}: labels must be 0/1")
        for passage, entry in zip(row['context_passages'], row['passage_map']):
            if not passage or len(passage) > 20000:
                raise SystemExit(f"{row['id']}: passage violates the service limit")
    return rows


def is_failure(row: dict, prediction: dict | None) -> bool:
    """A missing/error prediction or a claim-count mismatch is a document failure."""
    if prediction is None or 'error' in prediction:
        return True
    return len(prediction.get('claims') or []) != len(row['labels'])


def _doc_counts(row: dict, prediction: dict | None) -> np.ndarray:
    """tp, fp, fn, tn for one document; a failed document is wrong on every claim."""
    labels = row['labels']
    positives = sum(labels)
    negatives = len(labels) - positives
    if is_failure(row, prediction):
        return np.array([0, negatives, positives, 0], dtype=np.int64)
    claims = prediction.get('claims') or []
    predicted = [1 if c.get('verdict') == 'SUPPORTED' else 0 for c in claims]
    tp = sum(g == 1 and p == 1 for g, p in zip(labels, predicted))
    fp = sum(g == 0 and p == 1 for g, p in zip(labels, predicted))
    fn = sum(g == 1 and p == 0 for g, p in zip(labels, predicted))
    tn = sum(g == 0 and p == 0 for g, p in zip(labels, predicted))
    return np.array([tp, fp, fn, tn], dtype=np.int64)


def _bacc(counts: np.ndarray) -> float:
    tp, fp, fn, tn = (float(x) for x in counts)
    sensitivity = tp / (tp + fn) if tp + fn else float('nan')
    specificity = tn / (tn + fp) if tn + fp else float('nan')
    return (sensitivity + specificity) / 2


def _prf(counts: np.ndarray) -> tuple[float, float, float]:
    tp, fp, fn = (float(x) for x in counts[:3])
    p = tp / (tp + fp) if tp + fp else float('nan')
    r = tp / (tp + fn) if tp + fn else float('nan')
    f = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else float('nan')
    return p, r, f


def _macro(values: dict[str, float]) -> float:
    vals = [v for v in values.values() if np.isfinite(v)]
    return float(np.mean(vals)) if vals else float('nan')


def _subset_blocks(rows: list[dict], predictions: dict[str, dict[str, dict]],
                   exclude_failures: bool) -> tuple[dict, dict]:
    """Per-subset per-document counts and the reporting block."""
    subsets = sorted({r['subset'] for r in rows})
    per_doc: dict[str, dict[str, list[np.ndarray]]] = {m: {} for m in predictions}
    blocks: dict[str, dict] = {m: {} for m in predictions}
    for method, preds in predictions.items():
        for subset in subsets:
            all_docs = [r for r in rows if r['subset'] == subset]
            failures = sum(is_failure(r, preds.get(r['id'])) for r in all_docs)
            docs = all_docs if not exclude_failures else [
                r for r in all_docs if not is_failure(r, preds.get(r['id']))]
            counts = [_doc_counts(r, preds.get(r['id'])) for r in docs]
            per_doc[method][subset] = np.stack(counts) if counts else np.zeros((0, 4), dtype=np.int64)
            total = np.sum(counts, axis=0) if counts else np.zeros(4, dtype=np.int64)
            p, r, f = _prf(total)
            blocks[method][subset] = {
                'docs': len(docs), 'claims': int(total.sum()), 'positives': int(total[2] + total[0]),
                'failures': failures,
                'tp': int(total[0]), 'fp': int(total[1]), 'fn': int(total[2]), 'tn': int(total[3]),
                'balanced_accuracy': _bacc(total), 'precision': p, 'recall': r, 'f1': f,
            }
    return per_doc, blocks


def _bootstrap_macro(per_doc: dict[str, dict[str, list[np.ndarray]]], subsets: list[str],
                     replicates: int) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    draws = {}
    for method in per_doc:
        for subset in subsets:
            n = len(per_doc[method][subset])
            draws[(method, subset)] = (rng.integers(0, n, size=(replicates, n))
                                       if n else np.zeros((replicates, 0), dtype=int))
    samples = {}
    for method in per_doc:
        out = np.empty(replicates, dtype=float)
        for rep in range(replicates):
            values = {}
            for subset in subsets:
                counts = per_doc[method][subset]
                if len(counts) == 0:
                    continue
                picked = draws[(method, subset)][rep]
                values[subset] = _bacc(counts[picked].sum(axis=0))
            out[rep] = _macro(values)
        samples[method] = out
    return samples


def _paired_macro(rows: list[dict], predictions: dict[str, dict[str, dict]],
                  subsets: list[str], exclude_failures: bool,
                  replicates: int) -> dict:
    """Paired macro BAcc on the documents both methods completed (or all docs in main)."""
    a, b = 'optimized', 'minimal'
    if a not in predictions or b not in predictions:
        return {'n_cases': 0, 'statement': 'missing method'}
    pa, pb = predictions[a], predictions[b]
    common = [r for r in rows if not exclude_failures or
              (not is_failure(r, pa.get(r['id'])) and not is_failure(r, pb.get(r['id'])))]
    if not common:
        return {'n_cases': 0, 'statement': 'no common completed documents'}
    per = {a: {}, b: {}}
    for subset in subsets:
        docs = [r for r in common if r['subset'] == subset]
        for method, preds in ((a, pa), (b, pb)):
            per[method][subset] = (np.stack([_doc_counts(r, preds.get(r['id'])) for r in docs])
                                   if docs else np.zeros((0, 4), dtype=np.int64))
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    draws = {}
    for subset in subsets:
        n = len(per[a][subset])
        draws[subset] = rng.integers(0, n, size=(replicates, n)) if n else np.zeros((replicates, 0), dtype=int)
    sa, sb = [], []
    for rep in range(replicates):
        va, vb = {}, {}
        for subset in subsets:
            if not len(per[a][subset]):
                continue
            picked = draws[subset][rep]
            va[subset] = _bacc(per[a][subset][picked].sum(axis=0))
            vb[subset] = _bacc(per[b][subset][picked].sum(axis=0))
        sa.append(_macro(va))
        sb.append(_macro(vb))
    point_a = _macro({s: _bacc(per[a][s].sum(axis=0)) for s in subsets if len(per[a][s])})
    point_b = _macro({s: _bacc(per[b][s].sum(axis=0)) for s in subsets if len(per[b][s])})
    block = v26.interval(point_a - point_b, np.asarray(sa) - np.asarray(sb))
    low, high = block['ci95']
    block.update({'n_cases': len(common), 'a': point_a, 'b': point_b,
                  'excludes_zero': None if low is None else bool(low > 0 or high < 0)})
    block['statement'] = v26.wording(a, b, block)
    return block


def track_a_report(rows: list[dict], predictions: dict[str, dict[str, dict]],
                   price_in: float = 0.0, price_out: float = 0.0,
                   replicates: int = v26.BOOTSTRAP_REPLICATES) -> dict:
    subsets = sorted({r['subset'] for r in rows})
    output = {'design_version': '2.7', 'track': 'aggrefact', 'n_docs': len(rows),
              'n_claims': sum(len(r['claims']) for r in rows), 'subsets': subsets,
              'bootstrap': {'unit': 'document within subset', 'replicates': replicates,
                            'seed': BOOTSTRAP_SEED, 'interval': 'percentile 2.5/97.5'},
              'methods': {}, 'paired': {}}
    for variant, drop in (('main', False), ('excluding_failures', True)):
        per_doc, blocks = _subset_blocks(rows, predictions, drop)
        samples = _bootstrap_macro(per_doc, subsets, replicates)
        methods = {}
        for method in predictions:
            macro_bacc = _macro({s: blocks[method][s]['balanced_accuracy'] for s in subsets})
            macro_prf = [_macro({s: blocks[method][s][k] for s in subsets})
                         for k in ('precision', 'recall', 'f1')]
            ci = v26.interval(macro_bacc, samples[method])
            methods[method] = {
                'macro_balanced_accuracy': ci,
                'macro_precision': macro_prf[0], 'macro_recall': macro_prf[1],
                'macro_f1': macro_prf[2], 'subsets': blocks[method],
                'docs': sum(blocks[method][s]['docs'] for s in subsets),
                'claims': sum(blocks[method][s]['claims'] for s in subsets),
                'failures': sum(blocks[method][s]['failures'] for s in subsets),
            }
        output['methods'][variant] = methods
        if 'optimized' in predictions and 'minimal' in predictions:
            output['paired'][variant] = _paired_macro(rows, predictions, subsets, drop, replicates)
    # cost/latency per method over the full document set
    output['cost_latency'] = {}
    for method, preds in predictions.items():
        metas = [(preds.get(r['id']) or {}).get('meta') or {} for r in rows]
        failures = sum(is_failure(r, preds.get(r['id'])) for r in rows)
        in_tok = sum(m.get('input_tokens', 0) for m in metas)
        out_tok = sum(m.get('output_tokens', 0) for m in metas)
        latency = sorted(m.get('latency_ms', 0.0) for m in metas)
        n = max(1, len(rows))
        pick = lambda q: latency[min(len(latency) - 1, int(q * len(latency)))] if latency else 0.0
        total = (in_tok * price_in + out_tok * price_out) / 1e6
        output['cost_latency'][method] = {
            'docs': len(rows), 'failures': failures, 'failure_rate': failures / n,
            'input_tokens': in_tok, 'output_tokens': out_tok,
            'cost_usd_total': total, 'cost_usd_per_doc': total / n,
            'latency_ms': {'mean': sum(latency) / n, 'p50': pick(.5), 'p95': pick(.95),
                           'max': latency[-1] if latency else 0.0},
            'retries': sum(m.get('retries', 0) for m in metas),
            'avg_llm_calls': sum(m.get('llm_calls', 0) for m in metas) / n,
        }
    return output


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--track', choices=['ragtruthpp', 'aggrefact'], default='ragtruthpp')
    ap.add_argument('--data', type=Path, default=None)
    ap.add_argument('--predictions', type=Path, required=True,
                    help='directory holding <method>_run0.jsonl')
    ap.add_argument('--methods', nargs='+', default=['baseline', 'minimal', 'optimized'])
    ap.add_argument('--price-in', type=float, default=0.0)
    ap.add_argument('--price-out', type=float, default=0.0)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    preds = {m: read_predictions(args.predictions / f'{m}_run0.jsonl') for m in args.methods}
    if args.track == 'ragtruthpp':
        rows = load_rows(args.data or Path('data/eval_ragtruthpp.v2.7.jsonl'))
        report = track_b_report(rows, preds, args.price_in, args.price_out)
        filename = 'v27_report.json'
    else:
        data = args.data or Path('data/eval_aggrefact.v2.7.test.jsonl')
        rows = load_aggrefact(data)
        report = track_a_report(rows, preds, args.price_in, args.price_out)
        filename = 'v27_aggrefact_report.json'
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / filename
    if path.exists():
        raise SystemExit('STOP: report already exists')
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    if args.track == 'ragtruthpp':
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
    else:
        for variant in ('main', 'excluding_failures'):
            print(variant)
            for m in args.methods:
                x = report['methods'][variant][m]
                print(f"  {m}: macro BAcc={x['macro_balanced_accuracy']['value']:.3f} "
                      f"failure docs={x['failures']}")
            if variant in report['paired']:
                print('  ', report['paired'][variant]['statement'])


if __name__ == '__main__':
    main()
