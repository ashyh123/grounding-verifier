"""v2.7 track A: document splitting, selection counts, oracle baseline and metrics."""
import json
from pathlib import Path

import pytest

from annotation.v27 import aggrefact
from eval import v27

ROOT = Path(__file__).resolve().parents[1]
TEST = ROOT / 'data' / 'eval_aggrefact.v2.7.test.jsonl'
DEV = ROOT / 'data' / 'eval_aggrefact.v2.7.dev.jsonl'
RUN = ROOT / 'results' / 'v2.7-dev' / 'aggrefact-baseline-test'

pytestmark = pytest.mark.skipif(not TEST.exists() or not DEV.exists(),
                                reason='track A data is local-only; run annotation.v27.aggrefact --write')


def test_split_document_is_verbatim_and_within_limits():
    text = ('First sentence. Second sentence is longer.\n\n'
            'A third paragraph has several words. Another sentence follows here.\n\n'
            'Final paragraph.')
    passages, mapping = aggrefact.split_document(text, target_words=5)
    assert passages and len(passages) <= 50
    assert all(p and len(p) <= 20000 and any(c.isalnum() for c in p) for p in passages)
    assert len(passages) == len(mapping)
    previous_end = -1
    for passage, entry in zip(passages, mapping):
        assert entry['index'] == mapping.index(entry)
        assert entry['start_char'] >= previous_end
        assert text[entry['start_char']:entry['end_char']] == passage
        previous_end = entry['end_char']


def test_test_selection_counts_and_limits():
    rows = v27.load_aggrefact(TEST)
    manifest = json.loads((ROOT / 'data' / 'annotation' / 'v2.7' /
                           'aggrefact-selection-test.json').read_text(encoding='utf-8'))
    assert len(rows) == 461
    assert sum(len(r['claims']) for r in rows) == 854
    assert sum(sum(r['labels']) for r in rows) == 512
    assert {r['subset'] for r in rows} == set(aggrefact.SUBSETS)
    assert manifest['totals']['docs'] == 461
    assert manifest['totals']['claims'] == 854
    assert manifest['totals']['positives'] == 512
    assert manifest['totals']['selected_positives_rate'] == pytest.approx(512 / 854)
    assert max(r['provenance']['passages'] for r in rows) <= 50
    assert max(len(p) for r in rows for p in r['context_passages']) <= 20000


def test_dev_selection_counts():
    rows = v27.load_aggrefact(DEV)
    manifest = json.loads((ROOT / 'data' / 'annotation' / 'v2.7' /
                           'aggrefact-selection-dev.json').read_text(encoding='utf-8'))
    assert len(rows) == 58
    assert sum(len(r['claims']) for r in rows) == 196
    assert sum(sum(r['labels']) for r in rows) == 108
    assert manifest['totals']['claims'] == 196 and manifest['totals']['positives'] == 108


def test_baseline_track_a_report_matches_predictions():
    run = RUN / 'baseline_run0.jsonl'
    report_path = RUN / 'report' / 'v27_aggrefact_report.json'
    if not run.exists() or not report_path.exists():
        pytest.skip('track A baseline run/report not generated')
    rows = v27.load_aggrefact(TEST)
    preds = {json.loads(line)['id']: json.loads(line) for line in
             run.read_text(encoding='utf-8').splitlines() if line.strip()}
    assert len(preds) == 461 and set(preds) == {r['id'] for r in rows}
    assert sum('error' in p for p in preds.values()) == 0
    report = v27.track_a_report(rows, {'baseline': preds}, replicates=200)
    block = report['methods']['main']['baseline']
    assert block['macro_balanced_accuracy']['value'] == pytest.approx(0.6077143049100848)
    assert block['claims'] == 854 and block['docs'] == 461
    saved = json.loads(report_path.read_text(encoding='utf-8'))
    assert saved['methods']['main']['baseline']['macro_balanced_accuracy']['value'] == pytest.approx(
        0.6077143049100848)
    assert saved['methods']['main']['baseline']['subsets']['AggreFact-CNN']['positives'] == 70


def test_failed_document_is_wrong_on_every_claim():
    row = {'labels': [1, 0, 1]}
    counts = v27._doc_counts(row, {'id': 'x', 'error': 'boom'})
    assert counts.tolist() == [0, 1, 2, 0]
    assert v27._bacc(counts) == 0.0
    # a malformed claim count is also a failed document
    counts = v27._doc_counts(row, {'id': 'x', 'claims': []})
    assert counts.tolist() == [0, 1, 2, 0]


def test_paired_macro_bacc_is_zero_for_identical_predictions():
    run = RUN / 'baseline_run0.jsonl'
    if not run.exists():
        pytest.skip('track A baseline run not generated')
    rows = v27.load_aggrefact(TEST)
    preds = {json.loads(line)['id']: json.loads(line) for line in
             run.read_text(encoding='utf-8').splitlines() if line.strip()}
    report = v27.track_a_report(rows, {'baseline': preds, 'minimal': preds, 'optimized': preds},
                                replicates=100)
    paired = report['paired']['main']
    assert paired['value'] == 0.0 and paired['ci95'] == [0.0, 0.0]
    assert paired['excludes_zero'] is False
