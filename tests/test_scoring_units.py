"""Production rescore scenarios: full/split coverage, missing units, changed numbers/negation,
wrong child labels, duplicate output, prediction reuse, registry drift, and oracle isolation.
"""
import asyncio
import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

from eval import report, run

ROOT = Path(__file__).resolve().parent.parent


def registry_records(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_registry(path, records):
    lines = []
    for record in records:
        entry = dict(record)
        if lines:
            entry['supersedes_sha256'] = hashlib.sha256(lines[-1].encode()).hexdigest()
        else:
            entry.pop('supersedes_sha256', None)
        lines.append(json.dumps(entry, ensure_ascii=False))
    path.write_text('\n'.join(lines) + '\n')


def fixture(tmp_path):
    original = next(line for line in (ROOT / 'data/eval.jsonl').read_text().splitlines()
                    if json.loads(line)['id'] == 'kafka-retention-11')
    data = tmp_path / 'dataset.jsonl'
    data.write_text(original + '\n')
    # Keep the regression fixture independent of local, uncommitted annotation data.
    parent = json.loads(original)['gold_claims'][1]
    approval = {
        'dataset_sha256': hashlib.sha256(data.read_bytes()).hexdigest(),
        'case_id': 'kafka-retention-11',
        'parent_claim_text': parent['claim_text'],
        'parent_verdict': 'SUPPORTED',
        'units': [
            {'claim_text': 'The retention check interval defaults to 300000 milliseconds.',
             'verdict': 'SUPPORTED'},
            {'claim_text': 'Deletion is not immediate.', 'verdict': 'SUPPORTED'},
        ],
        'approved_by': 'user',
        'approved_on': '2026-10-19',
    }
    revision = copy.deepcopy(approval)
    for unit, quote in zip(revision['units'], [
        'log.retention.check.interval.ms defaults to 300000 milliseconds',
        'segments are not deleted the moment a limit is exceeded',
    ]):
        unit['evidence'] = [{'index': 1, 'quote': quote}]
    records = [approval, revision]
    registry = data.with_suffix('.scoring_units.jsonl')
    write_registry(registry, records)
    prediction = next(json.loads(line) for line in (ROOT / 'results/final_e2e/minimal_run0.jsonl').read_text().splitlines()
                      if json.loads(line)['id'] == 'kafka-retention-11')
    return data, registry, prediction


def rescore(tmp_path, data, prediction, monkeypatch, oracle=False):
    import httpx

    async def no_network(*args, **kwargs):
        raise AssertionError('rescore must not call a model')

    monkeypatch.setattr(httpx.AsyncClient, 'send', no_network)
    summary = tmp_path / 'summary.json'
    summary.write_text(json.dumps({'split': 'test', 'oracle': oracle, 'n_cases': 1,
                                   'methods': {'minimal': [{}]}}))
    predictions = tmp_path / ('minimal_oracle_run0.jsonl' if oracle else 'minimal_run0.jsonl')
    predictions.write_text(json.dumps(prediction) + '\n')
    before = {p: p.read_bytes() for p in (data, data.with_suffix('.scoring_units.jsonl'), predictions)}
    monkeypatch.setattr(sys, 'argv', ['eval.run', '--data', str(data), '--rescore', str(tmp_path)])
    asyncio.run(run.main())
    for path, content in before.items():
        assert path.read_bytes() == content
    return json.loads(summary.read_text())


@pytest.mark.parametrize('mode', ['split', 'whole', 'missing_number_unit', 'missing_negation_unit',
                                  'wrong_number', 'deleted_negation', 'wrong_label', 'duplicate'])
def test_scoring_units_rescore_keeps_guards_and_parent_denominator(tmp_path, monkeypatch, mode):
    data, registry, prediction = fixture(tmp_path)
    claims = prediction['claims']
    if mode == 'whole':
        parent = json.loads(data.read_text())['gold_claims'][1]
        claims[1] = dict(claims[1], claim_text=parent['claim_text'],
                         citations=claims[1]['citations'] + claims[2]['citations'])
        claims.pop(2)
    elif mode == 'missing_number_unit':
        claims.pop(1)
    elif mode == 'missing_negation_unit':
        claims.pop(2)
    elif mode == 'wrong_number':
        claims[1]['claim_text'] = claims[1]['claim_text'].replace('300000', '600000')
    elif mode == 'deleted_negation':
        claims[2]['claim_text'] = 'Deletion is immediate.'
    elif mode == 'wrong_label':
        claims[1].update(verdict='UNSUPPORTED', citations=[])
    elif mode == 'duplicate':
        claims.append(dict(claims[1]))
    summary = rescore(tmp_path, data, prediction, monkeypatch)
    m = summary['methods']['minimal'][0]
    d = m['decomposition']
    assert d['gold_claims'] == 2  # two parents, never three atomic scoring units
    assert m['scoring_units_registry_sha256'] == hashlib.sha256(registry.read_bytes()).hexdigest()
    if mode in ('split', 'whole', 'duplicate'):
        assert m['claim_accuracy_all_gold'] == 1
        assert d['matched_pairs'] == 2 and d['missed_gold'] == 0
        assert d['used_predictions'] == (2 if mode == 'whole' else 3)
        assert d['extra_predictions'] == (1 if mode == 'duplicate' else 0)
        assert d['duplicate_predictions'] == (1 if mode == 'duplicate' else 0)
        assert d['precision'] == (0.75 if mode == 'duplicate' else 1)
        assert m['groups']['task']['unknown']['correct'] == 2
    elif mode == 'wrong_label':
        assert d['matched_pairs'] == 2 and d['missed_gold'] == 0
        assert m['claim_accuracy_all_gold'] == 0.5
        assert m['confusion']['SUPPORTED']['UNSUPPORTED'] == 1
    else:
        assert m['claim_accuracy_all_gold'] == 0.5
        assert d['matched_pairs'] == 1 and d['missed_gold'] == 1
        assert m['confusion']['SUPPORTED']['MISSED'] == 1
        if mode in ('wrong_number', 'deleted_negation'):
            assert d['extra_predictions'] == 1
            assert m['guard_rejected_pairs'] > 0
    failures = report.failures(tmp_path, 'minimal', str(data))
    assert ('MISSED gold claim' in failures) == (mode in (
        'missing_number_unit', 'missing_negation_unit', 'wrong_number', 'deleted_negation'))
    assert 'Used predicted claims' in report.table(summary)


def test_scoring_units_cannot_reuse_a_prediction_for_another_parent(tmp_path, monkeypatch):
    data, registry, prediction = fixture(tmp_path)
    case = json.loads(data.read_text())
    # A synthetic overlapping parent consumes the number claim before the compound fallback.
    case['gold_claims'][0] = dict(case['gold_claims'][1],
                                 claim_text=prediction['claims'][1]['claim_text'])
    data.write_text(json.dumps(case) + '\n')
    records = registry_records(registry)
    approval = records[-1]
    for record in records:
        record['dataset_sha256'] = hashlib.sha256(data.read_bytes()).hexdigest()
    write_registry(registry, records)
    prediction['claims'].pop(0)
    m = rescore(tmp_path, data, prediction, monkeypatch)['methods']['minimal'][0]
    assert m['decomposition']['used_predictions'] == 2
    assert m['decomposition']['matched_pairs'] == 1
    assert m['decomposition']['missed_gold'] == 1
    assert m['claim_accuracy_all_gold'] == 0.5


def test_scoring_units_do_not_change_oracle_position_scoring(tmp_path, monkeypatch):
    data, registry, prediction = fixture(tmp_path)
    parent = json.loads(data.read_text())['gold_claims'][1]
    prediction['claims'][1] = dict(prediction['claims'][1], claim_text=parent['claim_text'])
    prediction['claims'].pop(2)
    m = rescore(tmp_path, data, prediction, monkeypatch, oracle=True)['methods']['minimal'][0]
    assert m['claim_accuracy_all_gold'] == 1
    assert m['decomposition']['used_predictions'] == 2
    assert m['guard_rejected_pairs'] == 0


@pytest.mark.parametrize('mode', ['hash', 'parent', 'approval', 'label', 'duplicate_unit'])
def test_scoring_registry_drift_is_rejected_before_any_result_write(tmp_path, monkeypatch, mode):
    data, registry, prediction = fixture(tmp_path)
    records = registry_records(registry)
    approval = records[-1]
    if mode == 'hash':
        approval['dataset_sha256'] = '0' * 64
    elif mode == 'parent':
        approval['parent_claim_text'] += ' Changed.'
    elif mode == 'approval':
        approval['approved_by'] = 'model'
    elif mode == 'label':
        approval['units'][0]['verdict'] = 'CONTRADICTED'
    elif mode == 'duplicate_unit':
        approval['units'][1] = approval['units'][0]
    write_registry(registry, records)
    summary = tmp_path / 'summary.json'
    summary.write_text(json.dumps({'split': 'test', 'oracle': False, 'methods': {'minimal': [{}]}}))
    original = summary.read_bytes()
    monkeypatch.setattr(sys, 'argv', ['eval.run', '--data', str(data), '--rescore', str(tmp_path)])
    with pytest.raises(ValueError):
        asyncio.run(run.main())
    assert summary.read_bytes() == original


@pytest.mark.parametrize('mode', ['valid_split', 'valid_whole', 'crossed_units', 'unrelated_exact',
                                  'non_exact_quote', 'wrong_offset', 'missing_citation'])
def test_registered_unit_citations_are_scored_against_their_own_evidence(tmp_path, monkeypatch, mode):
    data, registry, prediction = fixture(tmp_path)
    claims = prediction['claims']
    if mode == 'valid_whole':
        case = json.loads(data.read_text())
        claims[1]['claim_text'] = case['gold_claims'][1]['claim_text']
        quote = case['context_passages'][1]
        claims[1]['citations'] = [{'index': 1, 'start_char': 0, 'end_char': len(quote), 'quote': quote}]
        claims.pop(2)
    elif mode == 'crossed_units':
        claims[1]['citations'], claims[2]['citations'] = claims[2]['citations'], claims[1]['citations']
    elif mode == 'unrelated_exact':
        quote = 'retention.ms controls how long a log is kept'
        claims[2]['citations'] = [{'index': 0, 'start_char': 0, 'end_char': len(quote), 'quote': quote}]
    elif mode == 'non_exact_quote':
        claims[2]['citations'][0]['quote'] = 'segments are deleted the moment a limit is exceeded'
    elif mode == 'wrong_offset':
        claims[2]['citations'][0]['start_char'] = 0
    elif mode == 'missing_citation':
        claims[2]['citations'] = []
    m = rescore(tmp_path, data, prediction, monkeypatch)['methods']['minimal'][0]
    assert m['claim_accuracy_all_gold'] == 1  # citation scoring does not rewrite verdicts/alignment
    counts = m['citation_counts']
    assert counts['gold'] == 3  # one reference for parent 0, two unique references for parent 1
    if mode in ('valid_split', 'valid_whole'):
        assert m['citation_precision'] == 1 and m['citation_recall'] == 1
        assert counts['predicted'] == (2 if mode == 'valid_whole' else 3)
        assert counts['invalid'] == 0
    elif mode == 'crossed_units':
        assert counts['hit'] == 1 and counts['predicted'] == 3
        assert m['citation_precision'] == 1 / 3 and m['citation_recall'] == 1 / 3
        assert m['citation_passage_precision'] == 1  # right passage alone cannot prove support
    elif mode == 'missing_citation':
        assert m['citation_precision'] == 1 and m['citation_recall'] == 2 / 3
        assert counts['predicted'] == 2 and counts['gold_hit'] == 2
    else:
        assert counts['hit'] == 2 and counts['predicted'] == 3
        assert m['citation_precision'] == 2 / 3 and m['citation_recall'] == 2 / 3
        assert counts['invalid'] == int(mode in ('non_exact_quote', 'wrong_offset'))
    assert 'Invalid scored citations' in report.table({'split': 'test', 'oracle': False,
                                                       'n_cases': 1, 'methods': {'minimal': [m]}})


@pytest.mark.parametrize('failure', ['non_exact', 'normalized', 'missing', 'wrong_index', 'broken_chain'])
def test_unit_evidence_and_revision_chain_are_validated_before_rescore(tmp_path, monkeypatch, failure):
    data, registry, prediction = fixture(tmp_path)
    records = registry_records(registry)
    evidence = records[-1]['units'][1]['evidence']
    if failure == 'non_exact':
        evidence[0]['quote'] = evidence[0]['quote'].replace('not deleted', 'deleted')
    elif failure == 'normalized':
        evidence[0]['quote'] = evidence[0]['quote'].replace('are not', 'are  not')
    elif failure == 'missing':
        evidence.clear()
    elif failure == 'wrong_index':
        evidence[0]['index'] = 0
    write_registry(registry, records)
    if failure == 'broken_chain':
        lines = registry.read_text().splitlines()
        latest = json.loads(lines[-1])
        latest['supersedes_sha256'] = '0' * 64
        lines[-1] = json.dumps(latest)
        registry.write_text('\n'.join(lines) + '\n')
    summary = tmp_path / 'summary.json'
    summary.write_text(json.dumps({'split': 'test', 'oracle': False, 'methods': {'minimal': [{}]}}))
    before = summary.read_bytes()
    monkeypatch.setattr(sys, 'argv', ['eval.run', '--data', str(data), '--rescore', str(tmp_path)])
    with pytest.raises(ValueError):
        asyncio.run(run.main())
    assert summary.read_bytes() == before
