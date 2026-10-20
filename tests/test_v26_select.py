"""v2.6 sampling and sentence-level gold: determinism, coverage, recomputable gold, no reuse."""
import hashlib
import json
import random
from collections import Counter
from pathlib import Path

import pytest

from annotation import select_cases as original
from annotation import sources as S
from annotation.v26 import select as sel
from annotation.v26.sentences import content_bounds, gold_sentences, split_sentences

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data' / 'eval_ragtruth_resp.v2.6.jsonl'
RULES = json.loads((ROOT / 'data/annotation/v2.6/sampling_rules.json').read_text(encoding='utf-8'))
RAW = ROOT / 'data' / 'sources' / 'v2' / 'raw'
needs_raw = pytest.mark.skipif(not (RAW / 'response.jsonl').exists(), reason='upstream snapshot not present')


def rows():
    return [json.loads(line) for line in DATA.read_text(encoding='utf-8').splitlines() if line.strip()]


def read(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


SAMPLES = [
    '', 'One.', 'One. Two. Three.', '  Lead space. Next one.', 'Dr. Smith met J. K. Rowling in St. Louis. Fine.',
    'Costs $4.5 now.\nNew line here. "Quoted." Then (Paren) text!  Done?  Yes.',
    '1. Alpha item\n2. Beta item. Gamma continues\n\n\nTrailing newline.\n',
    'Ends without terminator', 'Ellipsis... Then more. e.g. this one. U.S. Navy rules.',
]


@pytest.mark.parametrize('text', SAMPLES)
def test_sentences_are_deterministic_cover_text_and_do_not_overlap(text):
    first = split_sentences(text)
    assert first == split_sentences(text)
    assert ''.join(s['text'] for s in first) == text
    cursor = 0
    for i, s in enumerate(first):
        assert s['index'] == i and s['start'] == cursor and s['end'] > s['start']
        assert text[s['start']:s['end']] == s['text']
        cursor = s['end']
    assert cursor == len(text)


def test_sentence_rules_examples():
    texts = [s['text'].strip() for s in split_sentences('Dr. Smith met J. K. Rowling in St. Louis. Fine. 1. x')]
    assert texts == ['Dr. Smith met J. K. Rowling in St. Louis.', 'Fine.', '1. x']
    assert [s['text'] for s in split_sentences('A b.\nc d')] == ['A b.\n', 'c d']
    assert len(split_sentences('Version 2.5 is out. Done.')) == 2


def test_gold_sentences_overlap_is_half_open_and_ignores_whitespace():
    answer = 'Alpha is red. Beta is blue.'
    inside = {'start': 14, 'end': 18, 'label_type': 'Evident Conflict'}
    touching = {'start': 13, 'end': 14, 'label_type': 'Evident Conflict'}  # the gap between sentences
    gs = gold_sentences(answer, [inside])
    assert [s['hallucinated'] for s in gs] == [False, True]
    assert gs[1]['overlapping_labels'] == [inside]
    assert [s['hallucinated'] for s in gold_sentences(answer, [touching])] == [False, False]
    assert content_bounds(split_sentences(answer)[0]) == (0, 13)


def test_dataset_fields_and_sentence_invariants():
    data = rows()
    assert len(data) == 210 and Counter(r['split'] for r in data) == {'dev': 30, 'test': 180}
    for r in data:
        assert set(r) == {'id', 'split', 'task', 'generator_model', 'context_passages', 'passage_map',
                          'generated_answer', 'source_labels', 'gold_response', 'gold_sentences',
                          'provenance'}
        sentences = r['gold_sentences']
        assert ''.join(s['text'] for s in sentences) == r['generated_answer']
        assert [(s['start'], s['end']) for s in sentences] == [
            (s['start'], s['end']) for s in split_sentences(r['generated_answer'])]
        assert all(a['end'] == b['start'] for a, b in zip(sentences, sentences[1:]))


def test_gold_recomputes_from_upstream_fragments_alone():
    for r in rows():
        labels = r['source_labels']['labels']
        for label in labels:
            assert r['generated_answer'][label['start']:label['end']] == label['text']
        assert r['gold_response'] is bool(labels)
        assert r['gold_sentences'] == gold_sentences(r['generated_answer'], labels)
        assert (any(s['hallucinated'] for s in r['gold_sentences'])) is r['gold_response']


def test_counts_match_registered_quotas():
    for task, quotas in RULES['quotas'].items():
        for split, n in quotas.items():
            assert sum(r['task'] == task and r['split'] == split for r in rows()) == n


def test_no_overlap_with_used_cases_and_caps_hold():
    used = read(ROOT / 'data/eval_hard.v2.5.jsonl')
    used_resp = {u['provenance']['response_id'] for u in used} | S.LEGACY_RESPONSE_IDS
    used_src = {u['provenance']['source_id'] for u in used}
    data = rows()
    sources = [r['provenance']['source_id'] for r in data]
    assert len(set(sources)) == len(sources)  # one response per source_id
    for r in data:
        assert r['provenance']['response_id'] not in used_resp
        assert r['provenance']['source_id'] not in used_src
        assert r['provenance']['upstream_split'] == 'test' and r['provenance']['upstream_quality'] == 'good'
        assert r['provenance']['context_words'] <= RULES['technical_caps']['max_context_words']
        assert r['provenance']['answer_words'] <= RULES['technical_caps']['max_answer_words']


def test_near_duplicate_groups_do_not_cross_splits_or_touch_used_data():
    data = rows()
    docs = {f"new-{r['id']}": '\n\n'.join(r['context_passages']) for r in data}
    old = {f"old-{u['id']}": '\n\n'.join(u['context_passages'])
           for u in read(ROOT / 'data/eval_hard.v2.5.jsonl')}
    old.update({f"syn-{u['id']}": '\n\n'.join(u['context_passages'])
                for u in read(ROOT / 'data/eval.jsonl')})
    groups = original.duplicate_groups({**docs, **old})
    by_group = {}
    for r in data:
        by_group.setdefault(groups[f"new-{r['id']}"], set()).add(r['split'])
    assert all(len(v) == 1 for v in by_group.values())
    old_groups = {groups[k] for k in old}
    assert not [r['id'] for r in data if groups[f"new-{r['id']}"] in old_groups]


def synthetic_pool(n_sources=40, tasks=sel.TASKS):
    pool = []
    for t, task in enumerate(tasks):
        for s in range(n_sources):
            sid = f'{task}-{s}'
            # pairs of sources share a near-duplicate group
            group = f'g-{task}-{s // 2}'
            for m in ('a', 'b', 'c'):
                pool.append({'response_id': f'{sid}-{m}', 'source_id': sid, 'task': task, 'model': m,
                             'group': group, 'context_words': 10, 'answer_words': 10})
    return pool


SMALL_RULES = {'seed': 7, 'quotas': {t: {'dev': 3, 'test': 8} for t in sel.TASKS}}


def test_draw_is_reproducible_and_independent_of_input_order():
    pool = synthetic_pool()
    first = sel.draw(pool, SMALL_RULES)
    shuffled = pool[:]
    random.Random(1).shuffle(shuffled)
    again = sel.draw(shuffled, SMALL_RULES)
    key = lambda chosen: sorted((i['response_id'], s) for i, s in chosen)
    assert key(first) == key(again) == key(sel.draw(pool, SMALL_RULES))
    other = sel.draw(pool, {**SMALL_RULES, 'seed': 8})
    assert key(other) != key(first)


def test_draw_quotas_one_source_and_group_split_consistency():
    chosen = sel.draw(synthetic_pool(), SMALL_RULES)
    assert Counter((i['task'], s) for i, s in chosen) == {(t, sp): n for t in sel.TASKS
                                                          for sp, n in (('dev', 3), ('test', 8))}
    assert len({i['source_id'] for i, _ in chosen}) == len(chosen)
    splits = {}
    for item, split in chosen:
        assert splits.setdefault(item['group'], split) == split


def test_draw_stops_when_quotas_are_infeasible():
    with pytest.raises(SystemExit, match='infeasible'):
        sel.draw(synthetic_pool(n_sources=5), SMALL_RULES)


def test_pool_building_never_needs_labels():
    responses = [{'id': '1', 'source_id': 'x', 'model': 'm', 'split': 'test', 'quality': 'good',
                  'response': 'short answer'}]  # no `labels` key at all
    sources = {'x': {'source_id': 'x', 'task_type': 'Summary', 'source_info': 'Para one.\n\nPara two.'}}
    pool, summary = sel.build_pool(RULES, responses, sources, [], [])
    assert [p['response_id'] for p in pool] == ['1'] and summary['excluded_responses'] == {}


@needs_raw
def test_selection_reproduces_from_the_upstream_snapshot(tmp_path):
    import subprocess, sys
    out = tmp_path / 'v26'
    dataset = tmp_path / 'resp.jsonl'
    subprocess.run([sys.executable, '-m', 'annotation.v26.select', '--out-dir', str(out),
                    '--dataset', str(dataset)], cwd=ROOT, check=True, capture_output=True)
    assert hashlib.sha256(dataset.read_bytes()).hexdigest() == hashlib.sha256(DATA.read_bytes()).hexdigest()
    committed = json.loads((ROOT / 'data/annotation/v2.6/selection.json').read_text(encoding='utf-8'))
    assert json.loads((out / 'selection.json').read_text(encoding='utf-8')) == committed


@needs_raw
def test_answers_labels_and_contexts_match_upstream_exactly():
    responses = {r['id']: r for r in S.load_ragtruth_responses()}
    sources = S.load_ragtruth_sources()
    for r in rows():
        up = responses[r['provenance']['response_id']]
        assert r['generated_answer'] == up['response']          # answer never altered
        assert r['source_labels']['labels'] == up['labels']      # fragments kept verbatim
        assert r['generator_model'] == up['model']
        source = sources[up['source_id']]
        passages, original_text, prefixes = sel.segments(source, source['task_type'])
        assert r['context_passages'] == passages
        assert S.check_segmentation(r['id'], passages, original_text, prefixes).ok
        for p, m in zip(passages, r['passage_map']):
            assert original_text[m['start_char']:m['end_char']] == p
