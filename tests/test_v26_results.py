"""The committed v2.6 test predictions must reproduce the reported test summary."""
import json
from pathlib import Path

import pytest

from eval import v26

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data' / 'eval_ragtruth_resp.v2.6.jsonl'


def test_committed_test_results_match_predictions():
    d = ROOT / 'results' / 'v2.6-test'
    cases = v26.load_cases(DATA, 'test')
    summary = json.loads((d / 'summary.json').read_text(encoding='utf-8'))
    assert summary['n_cases'] == 180 and set(summary['methods']) == {'baseline', 'minimal', 'optimized'}
    for method in summary['methods']:
        rows = {json.loads(l)['id']: json.loads(l)
                for l in (d / f'{method}_run0.jsonl').read_text(encoding='utf-8').splitlines()}
        assert set(rows) == {c.id for c in cases}
        f1 = summary['methods'][method][0]['answer_level']['main']['metrics']['f1']['value']
        point = v26.answer_scores(v26.answer_matrix(cases, rows).sum(axis=0))[2]
        assert f1 == pytest.approx(point)
    assert summary['methods']['baseline'][0]['failures'] == 0
    assert summary['methods']['minimal'][0]['failures'] == 0
    assert summary['methods']['optimized'][0]['failures'] == 1
    report = json.loads((d / 'report' / 'v26_report.json').read_text(encoding='utf-8'))
    assert report['methods']['minimal']['answer_level']['main']['metrics']['f1']['value'] == pytest.approx(
        0.7195121951219512)
    assert report['methods']['optimized']['answer_level']['main']['metrics']['f1']['value'] == pytest.approx(
        0.6091370558375635)
