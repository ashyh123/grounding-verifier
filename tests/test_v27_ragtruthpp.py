"""v2.7 track B data, selection, reuse and the free baseline."""
import json
from pathlib import Path

import pytest

from annotation.v26.sentences import gold_sentences
from annotation.v27 import ragtruthpp
from eval import v27

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data' / 'eval_ragtruthpp.v2.7.jsonl'
SELECTION = ROOT / 'data' / 'annotation' / 'v2.7' / 'selection.json'
V26_RESULTS = ROOT / 'results' / 'v2.6-test'

pytestmark = pytest.mark.skipif(not DATA.exists(),
                                reason='track B data is local-only; run annotation.v27.ragtruthpp --write')


def rows():
    return v27.load_rows(DATA)


def test_dataset_counts_and_selection():
    rs = rows()
    selected = v27.selected(rs)
    assert len(rs) == 384 and len(selected) == 229
    assert sum(bool(r['selection']['reuse_v26_prediction']) for r in selected) == 29
    assert sum(not r['selection']['reuse_v26_prediction'] for r in selected) == 200
    assert all(r['selection']['selected'] for r in rs if r['selection']['reuse_v26_prediction'])
    payload = json.loads(SELECTION.read_text(encoding='utf-8'))
    assert payload['selected_total'] == 229 and payload['v26_test_overlaps'] == 29
    assert set(payload['selected_ids']) == {r['id'] for r in selected}
    assert set(payload['reuse_ids']) == {r['id'] for r in selected
                                         if r['selection']['reuse_v26_prediction']}


def test_strict_and_loose_gold_recompute_from_spans():
    for row in rows():
        strict = gold_sentences(row['generated_answer'], row['source_labels']['labels'])
        loose = gold_sentences(row['generated_answer'], row['loose_source_labels']['labels'])
        assert strict == row['gold_sentences']
        assert loose == row['loose_gold_sentences']
        assert row['gold_response'] == bool(row['source_labels']['labels'])
        assert row['loose_gold_response'] == bool(row['loose_source_labels']['labels'])
        assert all(row['generated_answer'][x['start']:x['end']] == x['text']
                   for x in row['source_labels']['labels'])
        assert all(row['generated_answer'][x['start']:x['end']] == x['text']
                   for x in row['loose_source_labels']['labels'])


def test_ragtruthpp_mapping_is_complete():
    pairs = ragtruthpp.load_pairs()
    assert len(pairs) == 408
    assert sum(len(spans) for _, _, spans in pairs) == 865
    for response, message, spans in pairs:
        assert message['text'] == response['response']
        for span in spans:
            start, end = int(span['start_pos']), int(span['end_pos'])
            assert message['text'][start:end] == span['span_text']


def test_v26_reuse_predictions_exist_and_match_context():
    v26_rows = [json.loads(line) for line in
                (ROOT / 'data' / 'eval_ragtruth_resp.v2.6.jsonl').read_text(encoding='utf-8').splitlines()
                if line.strip()]
    v26_test = {str(r['provenance']['response_id']): r for r in v26_rows if r['split'] == 'test'}
    reused = [r for r in rows() if r['selection']['reuse_v26_prediction']]
    assert len(reused) == 29
    for row in reused:
        rid = row['provenance']['response_id']
        assert rid in v26_test
        assert row['context_passages'] == v26_test[rid]['context_passages']
        for method in ('baseline', 'minimal', 'optimized'):
            predictions = {json.loads(line)['id']: json.loads(line) for line in
                           (V26_RESULTS / f'{method}_run0.jsonl').read_text(encoding='utf-8').splitlines()
                           if line.strip()}
            assert f'ragtruth-{rid}' in predictions


def test_baseline_track_b_run_matches_predictions():
    run = ROOT / 'results' / 'v2.7-dev' / 'baseline' / 'baseline_run0.jsonl'
    if not run.exists():
        pytest.skip('baseline track B run not generated')
    preds = {json.loads(line)['id']: json.loads(line) for line in
             run.read_text(encoding='utf-8').splitlines() if line.strip()}
    rs = v27.selected(rows())
    assert len(preds) == 229 and set(preds) == {r['id'] for r in rs}
    assert sum('error' in p for p in preds.values()) == 0
    assert sum(bool(p.get('reused_from_v26')) for p in preds.values()) == 29
    report = v27.track_b_report(rows(), {'baseline': preds})
    assert report['standards']['strict']['methods']['baseline']['failures'] == 0
    assert report['standards']['strict']['gold_positives'] == 170
    assert report['standards']['loose']['gold_positives'] == 35
    assert report['standards']['strict']['methods']['baseline']['answer_level']['main'][
        'metrics']['balanced_accuracy']['value'] == pytest.approx(0.5390827517447657)
    assert report['standards']['loose']['methods']['baseline']['answer_level']['main'][
        'metrics']['balanced_accuracy']['value'] == pytest.approx(0.5257731958762887)


def test_paired_sentence_f1_is_zero_for_identical_predictions():
    rs = v27.selected(rows())
    run = ROOT / 'results' / 'v2.7-dev' / 'baseline' / 'baseline_run0.jsonl'
    if not run.exists():
        pytest.skip('baseline track B run not generated')
    preds = {json.loads(line)['id']: json.loads(line) for line in
             run.read_text(encoding='utf-8').splitlines() if line.strip()}
    block = v27.paired_sentence_f1(rs, {'minimal': preds, 'optimized': preds}, 'strict')
    assert block['n_cases'] == 229
    assert block['f1']['value'] == 0.0 and block['f1']['ci95'] == [0.0, 0.0]
