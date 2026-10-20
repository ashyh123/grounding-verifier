"""Build the v2.7 RAGTruth++ response-level track (track B).

    uv run python -m annotation.v27.ragtruthpp --stats
    uv run python -m annotation.v27.ragtruthpp --write

The CSV pairs are matched to the local RAGTruth snapshot by response id and exact answer text.
Both the loose (RAGTruth original) and strict (RAGTruth++) sentence gold are stored. No model calls.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import random
import statistics
from pathlib import Path

from annotation import select_cases as SC
from annotation import sources as S
from annotation.map_labels import write_new
from annotation.v25.select import segments
from annotation.v26.sentences import gold_sentences

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / 'data' / 'sources' / 'v2.7' / 'raw'
RULES = ROOT / 'data' / 'annotation' / 'v2.7' / 'rules.json'
DATASET = ROOT / 'data' / 'eval_ragtruthpp.v2.7.jsonl'
SELECTION = ROOT / 'data' / 'annotation' / 'v2.7' / 'selection.json'
V26 = ROOT / 'data' / 'eval_ragtruth_resp.v2.6.jsonl'
USED = [ROOT / 'data' / 'eval_hard.jsonl', ROOT / 'data' / 'eval_hard.v2.4.jsonl',
        ROOT / 'data' / 'eval_hard.v2.5.jsonl']
SEED = 20261024
NEW_ANSWERS = 200


def _read_csv(path: Path) -> list[dict]:
    with path.open(newline='', encoding='utf-8') as stream:
        return list(csv.DictReader(stream))


def _load_v26() -> tuple[dict[str, dict], dict[str, dict]]:
    rows = [json.loads(line) for line in V26.read_text(encoding='utf-8').splitlines() if line.strip()]
    test = {str(r['provenance']['response_id']): r for r in rows if r['split'] == 'test'}
    return test, {str(r['provenance']['response_id']): r for r in rows if r['split'] == 'dev'}


def _used_sources() -> set[str]:
    out = set()
    for path in USED:
        if not path.exists():
            continue
        for line in path.read_text(encoding='utf-8').splitlines():
            if line.strip():
                source_id = (json.loads(line).get('provenance') or {}).get('source_id')
                if source_id is not None:
                    out.add(str(source_id))
    return out


def load_pairs() -> list[tuple[dict, dict, list[dict]]]:
    """(RAGTruth response, RAGTruth++ assistant row, strict spans), all exact-matched."""
    responses = S.load_ragtruth_responses()
    sources = S.load_ragtruth_sources()
    by_id = {str(r['id']): r for r in responses}
    messages = _read_csv(RAW / 'ragtruthpp-messages.csv')
    spans = _read_csv(RAW / 'ragtruthpp-hallucination_spans.csv')
    by_message: dict[str, list[dict]] = collections.defaultdict(list)
    for span in spans:
        by_message[span['message_stable_id']].append(span)
    pairs, seen = [], set()
    for message in messages:
        if message['role'] != 'assistant':
            continue
        meta = json.loads(message['meta'])
        if meta.get('type') != 'response':
            raise SystemExit(f"STOP: assistant message {message['stable_id']} is not a response")
        rid = str(meta['original_id'])
        if rid in seen:
            raise SystemExit(f'STOP: duplicate RAGTruth++ response {rid}')
        seen.add(rid)
        response = by_id.get(rid)
        if response is None:
            raise SystemExit(f'STOP: RAGTruth response {rid} not found')
        if message['text'] != response['response']:
            raise SystemExit(f'STOP: answer text differs for response {rid}')
        if response['source_id'] not in sources:
            raise SystemExit(f'STOP: source {response["source_id"]} not found')
        strict = by_message.get(message['stable_id'], [])
        for span in strict:
            start, end = int(span['start_pos']), int(span['end_pos'])
            if message['text'][start:end] != span['span_text']:
                raise SystemExit(f'STOP: strict span offsets differ for response {rid}')
        pairs.append((response, message, strict))
    if len(pairs) != 408:
        raise SystemExit(f'STOP: expected 408 RAGTruth++ answers, got {len(pairs)}')
    return pairs


def _strict_labels(spans: list[dict]) -> list[dict]:
    return [{'start': int(s['start_pos']), 'end': int(s['end_pos']), 'text': s['span_text'],
             'label_type': s['label']} for s in spans]


def build_rows() -> tuple[list[dict], dict]:
    rules = json.loads(RULES.read_text(encoding='utf-8'))
    pairs = load_pairs()
    v26_test, v26_dev = _load_v26()
    used_sources = _used_sources()
    rows, excluded = [], collections.Counter()
    for response, message, spans in pairs:
        source = S.load_ragtruth_sources()[response['source_id']]
        source_id = str(response['source_id'])
        if source_id in used_sources:
            excluded['source_used_by_v2x'] += 1
            continue
        task = source['task_type']
        passages, _, _ = segments(source, task)
        context_words = S.words(' '.join(passages))
        item = {'record': response, 'source': source, 'context_words': context_words,
                'group': f'src-{source_id}', 'is_gpt': response['model'].startswith('gpt')}
        cand = SC._ragtruth_candidate(item, 'test', task, 'natural').to_json()
        answer = response['response']
        loose_labels = response['labels']
        strict_labels = _strict_labels(spans)
        loose_sentences = gold_sentences(answer, loose_labels)
        strict_sentences = gold_sentences(answer, strict_labels)
        rid = str(response['id'])
        v26_row = v26_test.get(rid)
        if v26_row is not None and v26_row['context_passages'] != cand['context_passages']:
            raise SystemExit(f'STOP: v2.6 context differs for reusable response {rid}')
        rank = random.Random(f'{SEED}:response:{rid}').random()
        row = {
            'id': f'ragtruthpp-{rid}',
            'split': 'test',
            'task': task,
            'generator_model': response['model'],
            'context_passages': cand['context_passages'],
            'passage_map': cand['passage_map'],
            'generated_answer': answer,
            'source_labels': {'labels': strict_labels},
            'gold_response': bool(strict_labels),
            'gold_sentences': strict_sentences,
            'loose_source_labels': {'labels': loose_labels},
            'loose_gold_response': bool(loose_labels),
            'loose_gold_sentences': loose_sentences,
            'selection': {'seed': SEED, 'rank': rank, 'selected': False,
                          'reuse_v26_prediction': f'ragtruth-{rid}' if v26_row else None,
                          'v26_split': 'test' if v26_row else ('dev' if rid in v26_dev else None)},
            'provenance': {
                'dataset': 'RAGTruth++',
                'response_id': rid,
                'source_id': source_id,
                'task_type': task,
                'upstream_split': response['split'],
                'upstream_quality': response['quality'],
                'ragtruthpp_message_stable_id': message['stable_id'],
                'ragtruthpp_revision': json.loads(
                    (ROOT / 'data' / 'annotation' / 'v2.7' / 'sources.json')
                    .read_text(encoding='utf-8'))['datasets']['ragtruthpp']['revision'],
                'gold_standards': ['ragtruth_original', 'ragtruth_plus_plus'],
                'sentence_rules': 'v2.6-sentences-1',
                'v26_case_id': f'ragtruth-{rid}' if v26_row else None,
                'context_sha256': cand['provenance']['context_sha256'],
            },
        }
        rows.append(row)
    rows.sort(key=lambda r: r['provenance']['response_id'])
    if len(rows) != 384:
        raise SystemExit(f'STOP: expected 384 answers after source exclusion, got {len(rows)}')
    # selection: all v2.6-test overlaps, plus the first 200 new answers by the registered rank
    overlaps = [r for r in rows if r['selection']['reuse_v26_prediction']]
    new = sorted([r for r in rows if not r['selection']['reuse_v26_prediction']],
                 key=lambda r: (r['selection']['rank'], r['id']))
    if len(new) < NEW_ANSWERS:
        raise SystemExit(f'STOP: only {len(new)} new answers, need {NEW_ANSWERS}')
    selected = {r['id'] for r in overlaps} | {r['id'] for r in new[:NEW_ANSWERS]}
    for row in rows:
        row['selection']['selected'] = row['id'] in selected
    summary = {
        'pairs': len(pairs),
        'after_source_exclusion': len(rows),
        'v26_test_overlaps': len(overlaps),
        'v26_dev_overlaps': sum(r['selection']['v26_split'] == 'dev' for r in rows),
        'new_available': len(new),
        'new_selected': NEW_ANSWERS,
        'selected_total': len(selected),
        'strict_positive_all': sum(r['gold_response'] for r in rows),
        'loose_positive_all': sum(r['loose_gold_response'] for r in rows),
        'strict_positive_selected': sum(r['gold_response'] for r in rows if r['selection']['selected']),
        'loose_positive_selected': sum(r['loose_gold_response'] for r in rows if r['selection']['selected']),
        'task_counts_selected': dict(sorted(collections.Counter(
            r['task'] for r in rows if r['selection']['selected']).items())),
        'excluded': dict(sorted(excluded.items())),
    }
    if summary['new_selected'] != NEW_ANSWERS:
        raise SystemExit('STOP: selection count mismatch')
    if summary['strict_positive_selected'] < 100:
        raise SystemExit('STOP: too few strict positives in the selected sample')
    return rows, summary


def _dist(values):
    return [min(values), statistics.median(values), max(values)] if values else None


def stats() -> dict:
    rows, summary = build_rows()
    for key in ('context_words', 'answer_words', 'sentences'):
        values = []
        for row in rows:
            if key == 'context_words':
                values.append(S.words(' '.join(row['context_passages'])))
            elif key == 'answer_words':
                values.append(S.words(row['generated_answer']))
            else:
                values.append(len(row['gold_sentences']))
        summary[key] = _dist(values)
    summary['models_all'] = dict(sorted(collections.Counter(r['generator_model'] for r in rows).items()))
    summary['models_selected'] = dict(sorted(collections.Counter(
        r['generator_model'] for r in rows if r['selection']['selected']).items()))
    summary['tasks_all'] = dict(sorted(collections.Counter(r['task'] for r in rows).items()))
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--stats', action='store_true')
    ap.add_argument('--write', action='store_true')
    args = ap.parse_args()
    if not (args.stats or args.write):
        ap.error('choose --stats or --write')
    rows, summary = build_rows()
    if args.stats:
        print(json.dumps(stats(), indent=2, ensure_ascii=False))
        return
    write_new(DATASET, rows)
    payload = {**summary, 'dataset': str(DATASET),
               'rules': 'data/annotation/v2.7/rules.json',
               'selected_ids': [r['id'] for r in rows if r['selection']['selected']],
               'reuse_ids': [r['id'] for r in rows if r['selection']['reuse_v26_prediction']]}
    SELECTION.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'wrote {DATASET} ({len(rows)} rows, {summary["selected_total"]} selected)')


if __name__ == '__main__':
    main()
