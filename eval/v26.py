"""v2.6 response-level metrics over saved predictions; never calls a verifier/provider.

Primary: response-level hallucination detection against upstream RAGTruth annotation.
  * prediction rule (registered): a response is predicted "hallucinated" iff the verifier emitted at
    least one CONTRADICTED or UNSUPPORTED claim. No threshold, no tuning.
  * failures: the main result counts every failed case as wrong (the opposite side of the gold);
    `excluding_failures` is a second report that drops failed cases.
  * precision / recall / F1 / balanced accuracy with case-level bootstrap (10000, seed 20261022).
  * paired comparison on the SAME resampled cases; wording rule below is written into the output.
Secondary: sentence-level localisation (rapidfuzz, threshold is a parameter), citation validity,
  groups (task, generator, evident-only / with-subtle, context length), cost and latency.

Alignment of claims to sentences is lexical and approximate; it is not a gold alignment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from rapidfuzz import fuzz

from annotation.v26.sentences import gold_sentences

BOOTSTRAP_REPLICATES = 10000
BOOTSTRAP_SEED = 20261022
DEFAULT_SENT_THRESHOLD = 60.0
SCORERS = {'token_set_ratio': fuzz.token_set_ratio, 'partial_ratio': fuzz.partial_ratio,
           'ratio': fuzz.ratio}
SMALL_N = 20
BAD = ('CONTRADICTED', 'UNSUPPORTED')
PREDICTION_RULE = ('predicted hallucinated iff the verifier output has at least one CONTRADICTED or '
                   'UNSUPPORTED claim')
FAILURE_RULE = ('main result: a failed case is always wrong (gold positive -> missed, gold negative -> '
                'false alarm); `excluding_failures` drops failed cases (paired comparisons then use '
                'the cases both methods completed)')
WORDING_RULE = ('"A is better than B" may be written only if the 95% interval of the paired difference '
                'excludes 0; otherwise write "no evidence of a difference" and give the interval. '
                'Never write "equally good".')
LENGTH_BUCKETS = (('0-399', 0, 400), ('400-799', 400, 800), ('800+', 800, 10 ** 9))


@dataclass
class Case:
    id: str
    task: str
    generator_model: str
    answer: str
    passages: list[str]
    gold_response: bool
    gold_sentences: list[dict]
    labels: list[dict] = field(default_factory=list)
    context_words: int = 0

    @property
    def hardness(self) -> str:
        """evident_only / with_subtle for positives, 'none' for gold-negative cases."""
        if not self.labels:
            return 'none'
        return 'with_subtle' if any(l['label_type'].startswith('Subtle') for l in self.labels) \
            else 'evident_only'


# ------------------------------------------------------------------------------------ loading
def case_from_row(row: dict) -> Case:
    """v2.6 rows carry gold; older rows (v2.5) have `source_labels` and the gold is derived here,
    with the same deterministic splitter and the same overlap rule."""
    labels = (row.get('source_labels') or {}).get('labels', [])
    task = row.get('task') or (row.get('provenance') or {}).get('task_type') or 'unknown'
    gold = row['gold_sentences'] if 'gold_sentences' in row \
        else gold_sentences(row['generated_answer'], labels)
    passages = row['context_passages']
    return Case(id=row['id'], task=task, generator_model=row.get('generator_model') or 'unknown',
                answer=row['generated_answer'], passages=passages,
                gold_response=row['gold_response'] if 'gold_response' in row else bool(labels),
                gold_sentences=gold, labels=labels,
                context_words=len(' '.join(passages).split()))


def validate_rows(rows: list[dict]) -> list[str]:
    """Consistency checks for v2.6 rows (older layouts without `gold_response` are not checked)."""
    errs = []
    ids = [r['id'] for r in rows]
    errs += [f'duplicate id {i}' for i in sorted({i for i in ids if ids.count(i) > 1})]
    for r in rows:
        if 'gold_response' not in r:
            continue
        labels = (r.get('source_labels') or {}).get('labels', [])
        if r.get('split') not in ('dev', 'test'):
            errs.append(f"{r['id']}: split must be dev|test")
        if r['gold_response'] != bool(labels):
            errs.append(f"{r['id']}: gold_response disagrees with the upstream fragments")
        if any(r['generated_answer'][x['start']:x['end']] != x['text'] for x in labels):
            errs.append(f"{r['id']}: upstream fragment offsets do not match the answer")
        if ''.join(s['text'] for s in r['gold_sentences']) != r['generated_answer']:
            errs.append(f"{r['id']}: gold_sentences do not tile the answer")
    return errs


def load_cases(path: Path, split: str = 'all') -> list[Case]:
    """Load a v2.6 (or older, labels-bearing) dataset without needing gold claims."""
    rows = [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines()
            if line.strip()]
    errors = validate_rows(rows)
    if errors:
        raise ValueError('dataset invalid:\n' + '\n'.join(errors))
    return [case_from_row(r) for r in rows if split == 'all' or r.get('split') == split]


def read_predictions(path: Path) -> dict[str, dict]:
    rows = [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines()
            if line.strip()]
    out = {r['id']: r for r in rows}
    if len(out) != len(rows):
        raise ValueError(f'duplicate prediction ids in {path}')
    return out


def is_failure(prediction: dict | None) -> bool:
    return prediction is None or 'error' in prediction


def predicted_bad(prediction: dict) -> bool:
    return any(c['verdict'] in BAD for c in prediction['claims'])


# ------------------------------------------------------------------------------------ numerics
def _div(num, den):
    num, den = np.asarray(num, dtype=float), np.asarray(den, dtype=float)
    return np.divide(num, den, out=np.full(np.broadcast(num, den).shape, np.nan), where=den != 0)


def answer_scores(counts: np.ndarray) -> np.ndarray:
    """Last axis in: tp, fp, fn, tn. Out: precision, recall, F1, balanced accuracy.

    Undefined ratios are NaN (e.g. no predicted positives); F1 is 0 when there are no true
    positives and some predicted or gold positives. Balanced accuracy needs both classes."""
    tp, fp, fn, tn = (counts[..., i].astype(float) for i in range(4))
    precision, recall = _div(tp, tp + fp), _div(tp, tp + fn)
    f1 = np.where(2 * tp + fp + fn == 0, np.nan, 2 * tp / np.where(2 * tp + fp + fn == 0, 1, 2 * tp + fp + fn))
    balanced = (recall + _div(tn, tn + fp)) / 2
    return np.stack([precision, recall, f1, balanced], axis=-1)


def prf_scores(counts: np.ndarray) -> np.ndarray:
    """Last axis in: tp, fp, fn, ... Out: precision, recall, F1 (sentence-level)."""
    tp, fp, fn = (counts[..., i].astype(float) for i in range(3))
    f1 = np.where(2 * tp + fp + fn == 0, np.nan, 2 * tp / np.where(2 * tp + fp + fn == 0, 1, 2 * tp + fp + fn))
    return np.stack([_div(tp, tp + fp), _div(tp, tp + fn), f1], axis=-1)


def _num(x) -> float | None:
    return None if x is None or not np.isfinite(x) else float(x)


def _draws(n: int, replicates: int, seed: int) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, n, size=(replicates, n))


def interval(point: float, samples: np.ndarray) -> dict:
    valid = samples[np.isfinite(samples)]
    if len(valid) == 0:
        return {'value': _num(point), 'ci95': [None, None]}
    low, high = np.percentile(valid, [2.5, 97.5])
    return {'value': _num(point), 'ci95': [float(low), float(high)]}


def metric_block(per_case: np.ndarray, fn, names: tuple[str, ...], replicates=BOOTSTRAP_REPLICATES,
                 seed=BOOTSTRAP_SEED) -> dict:
    """per_case: (n, k) count vectors. Whole cases are resampled, multiplicity preserved."""
    if len(per_case) == 0:
        return {'n_cases': 0, 'metrics': None}
    point = fn(per_case.sum(axis=0))
    sampled = fn(per_case[_draws(len(per_case), replicates, seed)].sum(axis=1))
    return {'n_cases': int(len(per_case)),
            'metrics': {name: interval(point[i], sampled[:, i]) for i, name in enumerate(names)}}


ANSWER_NAMES = ('precision', 'recall', 'f1', 'balanced_accuracy')


# ------------------------------------------------------------------------------------ answer level
def answer_vector(case: Case, prediction: dict | None) -> np.ndarray:
    """tp, fp, fn, tn for one case. Failures are wrong by construction."""
    gold = case.gold_response
    guess = (not gold) if is_failure(prediction) else predicted_bad(prediction)
    return np.array([gold and guess, (not gold) and guess, gold and not guess,
                     (not gold) and not guess], dtype=np.int64)


def answer_matrix(cases: list[Case], predictions: dict[str, dict]) -> np.ndarray:
    return np.stack([answer_vector(c, predictions.get(c.id)) for c in cases]) if cases \
        else np.zeros((0, 4), dtype=np.int64)


def paired_difference(a: np.ndarray, b: np.ndarray, replicates=BOOTSTRAP_REPLICATES,
                      seed=BOOTSTRAP_SEED) -> dict:
    """A minus B on the same resampled cases. a, b: (n, 4) answer count matrices."""
    if a.shape != b.shape or len(a) == 0:
        raise ValueError('paired comparison needs the same non-empty case set')
    draws = _draws(len(a), replicates, seed)
    sa, sb = answer_scores(a.sum(axis=0)), answer_scores(b.sum(axis=0))
    ra, rb = answer_scores(a[draws].sum(axis=1)), answer_scores(b[draws].sum(axis=1))
    out = {'n_cases': int(len(a))}
    for name, i in (('f1', 2), ('balanced_accuracy', 3)):
        diff = ra[:, i] - rb[:, i]
        block = interval(sa[i] - sb[i], diff)
        low, high = block['ci95']
        block['a'], block['b'] = _num(sa[i]), _num(sb[i])
        block['excludes_zero'] = None if low is None else bool(low > 0 or high < 0)
        out[name] = block
    return out


def wording(a_name: str, b_name: str, block: dict) -> str:
    low, high = block['ci95']
    if low is None:
        return 'undefined'
    interval_text = (f"paired difference {a_name} minus {b_name} {block['value']:+.3f}, "
                     f"95% CI [{low:+.3f}, {high:+.3f}]")
    if low > 0:
        return f'{a_name} is better than {b_name} ({interval_text})'
    if high < 0:
        return f'{b_name} is better than {a_name} ({interval_text})'
    return f'no evidence of a difference between {a_name} and {b_name} ({interval_text})'


# ------------------------------------------------------------------------------------ sentences
def localize(case: Case, prediction: dict, threshold: float, scorer: str = 'token_set_ratio') -> list[dict]:
    """Each CONTRADICTED / UNSUPPORTED claim -> the most similar answer sentence (earliest on ties)."""
    score = SCORERS[scorer]
    texts = [s['text'].strip().lower() for s in case.gold_sentences]
    out = []
    for ci, claim in enumerate(prediction['claims']):
        if claim['verdict'] not in BAD or not texts:
            continue
        claim_text = claim['claim_text'].strip().lower()
        scores = [score(claim_text, t) for t in texts]
        best = int(np.argmax(scores))
        out.append({'claim': ci, 'sentence': best if scores[best] >= threshold else None,
                    'score': float(scores[best])})
    return out


def sentence_vector(case: Case, prediction: dict | None, threshold: float, scorer: str) -> np.ndarray:
    """tp, fp, fn, localized claims, unlocalized claims, localized claims on a gold-bad sentence."""
    gold_bad = {s['index'] for s in case.gold_sentences if s['hallucinated']}
    if is_failure(prediction):
        return np.array([0, 0, len(gold_bad), 0, 0, 0], dtype=np.int64)
    links = localize(case, prediction, threshold, scorer)
    predicted = {l['sentence'] for l in links if l['sentence'] is not None}
    return np.array([len(predicted & gold_bad), len(predicted - gold_bad), len(gold_bad - predicted),
                     sum(l['sentence'] is not None for l in links),
                     sum(l['sentence'] is None for l in links),
                     sum(l['sentence'] in gold_bad for l in links if l['sentence'] is not None)],
                    dtype=np.int64)


def sentence_block(cases, predictions, threshold, scorer, replicates=BOOTSTRAP_REPLICATES) -> dict:
    matrix = np.stack([sentence_vector(c, predictions.get(c.id), threshold, scorer) for c in cases]) \
        if cases else np.zeros((0, 6), dtype=np.int64)
    block = metric_block(matrix, prf_scores, ('precision', 'recall', 'f1'), replicates)
    total = matrix.sum(axis=0) if len(matrix) else np.zeros(6, dtype=np.int64)
    localized, unlocalized = int(total[3]), int(total[4])
    return {**block, 'scorer': scorer, 'threshold': threshold,
            'gold_bad_sentences': int(total[0] + total[2]),
            'predicted_bad_sentences': int(total[0] + total[1]),
            'cu_claims': localized + unlocalized, 'localized_claims': localized,
            'unlocalized_claims': unlocalized,
            'localization_rate': _num(localized / (localized + unlocalized)) if localized + unlocalized else None,
            'localized_claims_on_gold_bad_sentence': int(total[5]),
            'localized_claim_hit_rate': _num(total[5] / localized) if localized else None,
            'note': 'lexical, approximate alignment; unlocalized claims count in no sentence'}


def threshold_sweep(cases, predictions, thresholds, scorer='token_set_ratio') -> list[dict]:
    """Candidate thresholds: localisation rate, and how often localised claims land on a bad sentence."""
    rows = []
    for t in thresholds:
        matrix = np.stack([sentence_vector(c, predictions.get(c.id), t, scorer) for c in cases])
        total = matrix.sum(axis=0)
        prf = prf_scores(total)
        loc, unloc = int(total[3]), int(total[4])
        rows.append({'threshold': t, 'cu_claims': loc + unloc,
                     'localization_rate': _num(loc / (loc + unloc)) if loc + unloc else None,
                     'localized_claim_hit_rate': _num(total[5] / loc) if loc else None,
                     'sentence_precision': _num(prf[0]), 'sentence_recall': _num(prf[1]),
                     'sentence_f1': _num(prf[2])})
    return rows


def best_score_quantiles(cases, predictions, scorer='token_set_ratio') -> dict:
    """Distribution of best sentence-match scores over all C/U claims (threshold-free)."""
    scores = [l['score'] for c in cases if not is_failure(predictions.get(c.id))
              for l in localize(c, predictions[c.id], 0.0, scorer)]
    if not scores:
        return {'n': 0}
    q = np.percentile(scores, [0, 10, 25, 50, 75, 90, 100])
    return {'n': len(scores), **{k: float(v) for k, v in zip(('min', 'p10', 'p25', 'p50', 'p75', 'p90', 'max'), q)}}


# ------------------------------------------------------------------------------------ citations
def citation_counts(case: Case, prediction: dict | None) -> np.ndarray:
    """valid, wrong passage index (quote exists in another passage), not found / malformed, total."""
    out = np.zeros(4, dtype=np.int64)
    if is_failure(prediction):
        return out
    for claim in prediction['claims']:
        for c in claim.get('citations') or []:
            out[3] += 1
            index, quote = c.get('index'), c.get('quote')
            in_range = type(index) is int and 0 <= index < len(case.passages)
            if not isinstance(quote, str) or not quote.strip():
                out[2] += 1
            elif in_range and quote in case.passages[index]:
                start, end = c.get('start_char'), c.get('end_char')
                exact = (type(start) is int and type(end) is int
                         and case.passages[index][start:end] == quote)
                out[0 if exact else 2] += 1
            elif any(quote in p for p in case.passages):
                out[1] += 1
            else:
                out[2] += 1
    return out


def citation_block(cases, predictions) -> dict:
    matrix = np.stack([citation_counts(c, predictions.get(c.id)) for c in cases]) if cases \
        else np.zeros((0, 4), dtype=np.int64)
    total = matrix.sum(axis=0) if len(matrix) else np.zeros(4, dtype=np.int64)
    if len(matrix) and total[3]:
        point = float(total[0] / total[3])
        draws = _draws(len(matrix), BOOTSTRAP_REPLICATES, BOOTSTRAP_SEED)
        sums = matrix[draws].sum(axis=1)
        ci = interval(point, _div(sums[:, 0], sums[:, 3]))
    else:
        ci = {'value': None, 'ci95': [None, None]}
    return {'citations': int(total[3]), 'valid': int(total[0]), 'wrong_passage_index': int(total[1]),
            'not_exact_substring': int(total[2]), 'valid_rate': ci,
            'definition': 'valid = quote is an exact substring of the cited passage and start/end '
                          'offsets reproduce it; wrong_passage_index = the quote exists only in '
                          'another passage'}


# ------------------------------------------------------------------------------------ groups
def _bucket(words: int) -> str:
    return next(name for name, lo, hi in LENGTH_BUCKETS if lo <= words < hi)


def group_blocks(cases, predictions) -> dict:
    out = {}

    def full(subset):
        matrix = answer_matrix(subset, predictions)
        block = metric_block(matrix, answer_scores, ANSWER_NAMES)
        block['positives'] = int(sum(c.gold_response for c in subset))
        block['note'] = 'for reference only (n < 20)' if len(subset) < SMALL_N else ''
        return block

    def recall_only(subset):
        matrix = answer_matrix(subset, predictions)
        block = metric_block(matrix, lambda c: answer_scores(c)[..., 1:2], ('recall',))
        block['note'] = 'for reference only (n < 20)' if len(subset) < SMALL_N else ''
        return block

    keys = {'task': lambda c: c.task, 'generator_model': lambda c: c.generator_model,
            'context_length_words': lambda c: _bucket(c.context_words)}
    for dim, key in keys.items():
        out[dim] = {name: full([c for c in cases if key(c) == name])
                    for name in sorted({key(c) for c in cases})}
    # evident-only / with-subtle: positives only, recall only
    out['upstream_label_type_positives_only'] = {
        name: recall_only([c for c in cases if c.hardness == name])
        for name in ('evident_only', 'with_subtle')}
    return out


# ------------------------------------------------------------------------------------ cost
def cost_block(cases, predictions, price_in: float, price_out: float) -> dict:
    metas = [(predictions.get(c.id) or {}).get('meta') or {} for c in cases]
    failures = sum(is_failure(predictions.get(c.id)) for c in cases)
    latency = sorted(m.get('latency_ms', 0.0) for m in metas)
    in_tok = sum(m.get('input_tokens', 0) for m in metas)
    out_tok = sum(m.get('output_tokens', 0) for m in metas)
    total = (in_tok * price_in + out_tok * price_out) / 1e6
    n = max(1, len(cases))
    pick = lambda q: latency[min(len(latency) - 1, int(q * len(latency)))] if latency else 0.0
    return {'cases': len(cases), 'failures': failures, 'failure_rate': failures / n,
            'input_tokens': in_tok, 'output_tokens': out_tok,
            'cost_usd_total': total, 'cost_usd_per_case': total / n,
            'price_usd_per_mtok': {'in': price_in, 'out': price_out},
            'latency_ms': {'mean': sum(latency) / n, 'p50': pick(0.5), 'p95': pick(0.95),
                           'max': latency[-1] if latency else 0.0},
            'retries': sum(m.get('retries', 0) for m in metas),
            'avg_llm_calls': sum(m.get('llm_calls', 0) for m in metas) / n}


# ------------------------------------------------------------------------------------ compute
def method_report(cases, predictions, threshold, scorer, price_in, price_out) -> dict:
    ok = [c for c in cases if not is_failure(predictions.get(c.id))]
    return {
        'failures': len(cases) - len(ok),
        'answer_level': {
            'main': metric_block(answer_matrix(cases, predictions), answer_scores, ANSWER_NAMES),
            'excluding_failures': metric_block(answer_matrix(ok, predictions), answer_scores,
                                               ANSWER_NAMES)},
        'sentence_level': {'main': sentence_block(cases, predictions, threshold, scorer),
                           'excluding_failures': sentence_block(ok, predictions, threshold, scorer)},
        'citations': citation_block(cases, predictions),
        'groups': group_blocks(cases, predictions),
        'cost_latency': cost_block(cases, predictions, price_in, price_out)}


COMPARISONS = (('optimized', 'minimal'), ('minimal', 'baseline'), ('optimized', 'baseline'))


def compute(cases: list[Case], predictions: dict[str, dict[str, dict]], threshold=DEFAULT_SENT_THRESHOLD,
            scorer='token_set_ratio', price_in=0.0, price_out=0.0) -> dict:
    """predictions: method -> {case id -> prediction row or {'id', 'error'}}."""
    ids = {c.id for c in cases}
    for method, preds in predictions.items():
        if set(preds) - ids:
            raise ValueError(f'{method}: predictions for unknown case ids')
    methods = {m: method_report(cases, p, threshold, scorer, price_in, price_out)
               for m, p in predictions.items()}
    paired = {'main': [], 'excluding_failures': []}
    for a, b in COMPARISONS:
        if a not in predictions or b not in predictions:
            continue
        for variant in paired:
            subset = cases if variant == 'main' else [
                c for c in cases if not is_failure(predictions[a].get(c.id))
                and not is_failure(predictions[b].get(c.id))]
            if not subset:
                continue
            block = paired_difference(answer_matrix(subset, predictions[a]),
                                      answer_matrix(subset, predictions[b]))
            block.update(a=a, b=b)
            block['statement'] = {m: wording(a, b, block[m]) for m in ('f1', 'balanced_accuracy')}
            paired[variant].append(block)
    return {'design_version': '2.6', 'n_cases': len(cases),
            'gold_positives': sum(c.gold_response for c in cases),
            'prediction_rule': PREDICTION_RULE, 'failure_handling': FAILURE_RULE,
            'conclusion_wording_rule': WORDING_RULE,
            'bootstrap': {'unit': 'case', 'replicates': BOOTSTRAP_REPLICATES,
                          'seed': BOOTSTRAP_SEED, 'interval': 'percentile 2.5/97.5'},
            'sentence_alignment': {'scorer': scorer, 'threshold': threshold,
                                   'note': 'lexical approximation, threshold set on dev only'},
            'methods': methods, 'paired_f1_difference': paired}


def summary_markdown(report: dict) -> str:
    lines = [f"# v2.6 response-level report ({report['n_cases']} cases, "
             f"{report['gold_positives']} gold-positive)\n",
             f"- prediction rule: {report['prediction_rule']}\n- failures: {report['failure_handling']}\n"
             f"- wording: {report['conclusion_wording_rule']}\n\n",
             '| method | failures | precision | recall | F1 [95% CI] | balanced acc | sentence F1 | '
             'localized | valid citations | cost/case |\n|---|---:|---:|---:|---|---:|---:|---:|---:|---:|\n']
    f = lambda m: 'n/a' if m['value'] is None else f"{m['value']:.3f}"
    for name, m in report['methods'].items():
        a = (m['answer_level']['main']['metrics'] or {})
        s = m['sentence_level']['main']
        sf1 = (s['metrics'] or {}).get('f1', {'value': None})
        lo, hi = a['f1']['ci95'] if a else (None, None)
        ci = f"{f(a['f1'])} [{lo:.3f}, {hi:.3f}]" if a and lo is not None else 'n/a'
        loc = 'n/a' if s['localization_rate'] is None else f"{s['localization_rate']:.2f}"
        lines.append(f"| {name} | {m['failures']} | {f(a['precision'])} | {f(a['recall'])} | {ci} | "
                     f"{f(a['balanced_accuracy'])} | {f(sf1)} | {loc} | "
                     f"{f(m['citations']['valid_rate'])} | ${m['cost_latency']['cost_usd_per_case']:.4f} |\n")
    for variant, blocks in report['paired_f1_difference'].items():
        for b in blocks:
            lines.append(f"\n- [{variant}] F1: {b['statement']['f1']}")
    return ''.join(lines) + '\n'


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--data', type=Path, default=Path('data/eval_ragtruth_resp.v2.6.jsonl'))
    ap.add_argument('--split', choices=['dev', 'test', 'all'], default='dev')
    ap.add_argument('--predictions', type=Path, nargs='+', required=True,
                    help='directories holding <method>_run0.jsonl; a method may appear in one only')
    ap.add_argument('--methods', nargs='+', default=['baseline', 'minimal', 'optimized'])
    ap.add_argument('--run', type=int, default=0)
    ap.add_argument('--sent-threshold', type=float, default=DEFAULT_SENT_THRESHOLD)
    ap.add_argument('--scorer', choices=sorted(SCORERS), default='token_set_ratio')
    ap.add_argument('--sweep', type=float, nargs='*', default=None,
                    help='also write a threshold sweep for these thresholds')
    ap.add_argument('--price-in', type=float, default=None)
    ap.add_argument('--price-out', type=float, default=None)
    ap.add_argument('--out', type=Path, required=True, help='output directory (new)')
    args = ap.parse_args()
    from verifier import config
    price_in = args.price_in if args.price_in is not None else config.float_env('PRICE_IN_PER_MTOK', 0.0)
    price_out = args.price_out if args.price_out is not None else config.float_env('PRICE_OUT_PER_MTOK', 0.0)
    report_path = args.out / 'v26_report.json'
    if report_path.exists():
        raise SystemExit('STOP: report already exists; choose a new output path')
    cases = load_cases(args.data, args.split)
    predictions, sources = {}, {}
    for method in args.methods:
        for directory in args.predictions:
            path = directory / f'{method}_run{args.run}.jsonl'
            if path.exists():
                predictions[method] = read_predictions(path)
                sources[method] = hashlib.sha256(path.read_bytes()).hexdigest()
                break
    if not predictions:
        raise SystemExit('STOP: no prediction files found')
    report = compute(cases, predictions, args.sent_threshold, args.scorer, price_in, price_out)
    report.update(split=args.split, dataset=str(args.data),
                  dataset_sha256=hashlib.sha256(args.data.read_bytes()).hexdigest(),
                  predictions_sha256=sources)
    if args.sweep:
        report['threshold_sweep'] = {m: threshold_sweep(cases, p, args.sweep, args.scorer)
                                     for m, p in predictions.items()}
        report['best_score_quantiles'] = {m: best_score_quantiles(cases, p, args.scorer)
                                          for m, p in predictions.items()}
    args.out.mkdir(parents=True, exist_ok=True)
    with report_path.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    (args.out / 'v26_report.md').write_text(summary_markdown(report), encoding='utf-8')
    print(summary_markdown(report))


if __name__ == '__main__':
    main()
