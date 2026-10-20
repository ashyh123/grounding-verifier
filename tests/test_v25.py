"""v2.5 overlap provenance: every gold verdict must replay from answer spans + upstream labels."""
import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from annotation.v25 import overlaps

ROOT = Path(__file__).resolve().parents[1]
V24 = ROOT / 'data' / 'eval_hard.v2.4.jsonl'
BACKFILLED = ROOT / 'data' / 'annotation' / 'v2.5' / 'v24_with_overlaps.jsonl'
V25 = ROOT / 'data' / 'eval_hard.v2.5.jsonl'
RULES = ROOT / 'data' / 'annotation' / 'v2.5' / 'sampling_rules.json'
SELECTION = ROOT / 'data' / 'annotation' / 'v2.5' / 'selection.json'
SUBTLE = ROOT / 'data' / 'annotation' / 'v2.5' / 'subtle_candidates.jsonl'


def case(*, answer='Alpha is red. Beta is blue.', spans=((0, 13),), labels=(), verdict='SUPPORTED'):
    return {
        'id': 'synthetic', 'generated_answer': answer,
        'source_labels': {'labels': [
            {'start': start, 'end': end, 'text': answer[start:end], 'label_type': label_type,
             'meta': '', 'implicit_true': False, 'due_to_null': False}
            for start, end, label_type in labels]},
        'gold_claims': [{
            'claim_id': 'c1', 'claim_text': 'unused', 'verdict': verdict,
            'answer_spans': [{'quote': answer[start:end], 'start': start, 'end': end, 'match': 'exact'}
                             for start, end in spans],
        }],
    }


@pytest.mark.parametrize('labels,expected,matches', [
    ([], 'SUPPORTED', 0),
    ([(0, 13, 'Evident Baseless Info')], 'UNSUPPORTED', 1),
    ([(0, 13, 'Subtle Conflict')], 'CONTRADICTED', 1),
    ([(0, 13, 'Evident Baseless Info'), (0, 13, 'Evident Conflict')], 'CONTRADICTED', 2),
    # label starts exactly where the claim span ends: half-open ranges do not overlap
    ([(13, 27, 'Evident Conflict')], 'SUPPORTED', 0),
])
def test_conflict_precedes_baseless_and_ranges_are_half_open(labels, expected, matches):
    updated, errors = overlaps.backfill_case(case(labels=labels, verdict=expected))
    assert not errors and updated['gold_claims'][0]['verdict'] == expected
    assert len(updated['gold_claims'][0]['overlapping_source_labels']) == matches


def test_multiple_answer_spans_report_each_label_once():
    data = case(answer='Alpha is red. Beta is blue.', spans=((0, 13), (14, 27)),
                labels=[(0, 13, 'Evident Conflict')], verdict='CONTRADICTED')
    updated, errors = overlaps.backfill_case(data)
    assert not errors
    assert len(updated['gold_claims'][0]['overlapping_source_labels']) == 1


def test_non_exact_answer_span_is_rejected():
    data = case()
    data['gold_claims'][0]['answer_spans'][0]['quote'] = 'alpha is red.'
    with pytest.raises(ValueError, match='non-exact answer span'):
        overlaps.backfill_case(data)


def test_v24_verdict_replays_for_every_claim():
    rows = overlaps.read_jsonl(V24)
    errors = []
    for row in rows:
        _, case_errors = overlaps.backfill_case(row)
        errors.extend(case_errors)
    assert not errors, '\n'.join(errors[:20])
    assert sum(len(row['gold_claims']) for row in rows) == 638


@pytest.mark.parametrize('path', [BACKFILLED, V25], ids=['v24_with_overlaps', 'v25_final'])
def test_stored_overlaps_replay_on_generated_datasets(path):
    if not path.exists():
        pytest.skip(f'{path.name} not generated yet')
    rows = overlaps.read_jsonl(path)
    errors = [error for row in rows for error in overlaps.verify_case(row)]
    assert not errors, '\n'.join(errors[:20])


def test_backfill_report_pins_output_when_present():
    report = BACKFILLED.with_name('overlap_report.json')
    if not BACKFILLED.exists():
        pytest.skip('v2.5 overlap artifact not generated yet')
    saved = json.loads(report.read_text(encoding='utf-8'))
    assert saved['output_sha256'] == overlaps.digest(BACKFILLED)
    assert saved['verdict_replay_mismatches'] == 0


def test_subtle_selection_pins_rules_quotas_and_source_isolation():
    if not SUBTLE.exists():
        pytest.skip('v2.5 subtle supplement not sampled yet')
    rules = json.loads(RULES.read_text(encoding='utf-8'))
    selection = json.loads(SELECTION.read_text(encoding='utf-8'))
    rows = overlaps.read_jsonl(SUBTLE)
    assert selection['rules_sha256'] == hashlib.sha256(RULES.read_bytes()).hexdigest()
    assert selection['existing_sha256'] == hashlib.sha256(V24.read_bytes()).hexdigest()
    assert selection['counts'] == {'dev': 3, 'test': 10}
    assert selection['gpt_cases'] >= rules['generator_preference']['minimum_cases']
    assert len(rows) == rules['total_cases']
    assert Counter(row['split'] for row in rows) == Counter({'test': 10, 'dev': 3})
    assert Counter((row['provenance']['task_type'], row['split']) for row in rows) == Counter({
        ('Summary', 'test'): 4, ('QA', 'test'): 3, ('Data2txt', 'test'): 3,
        ('Summary', 'dev'): 1, ('QA', 'dev'): 1, ('Data2txt', 'dev'): 1})
    assert all(row['subset'] == 'subtle_supplement' for row in rows)
    assert all(row['provenance']['upstream_split'] in ('train', 'test') for row in rows)
    assert all(any('Subtle Conflict' in label['label_type']
                   for label in row['source_labels']['labels']) for row in rows)
    assert all(row['selection']['upstream_subtle_conflict_spans'] >= 1 for row in rows)
    assert len({row['provenance']['source_id'] for row in rows}) == len(rows)
    assert len({row['source_group_id'] for row in rows}) == len(rows)
    existing_sources = {row['provenance']['source_id']
                        for row in overlaps.read_jsonl(V24)}
    assert not existing_sources & {row['provenance']['source_id'] for row in rows}


V25_AUDIT = ROOT / 'data' / 'annotation' / 'v2.5' / 'audit.json'
V25_FREEZE = ROOT / 'data' / 'annotation' / 'v2.5' / 'freeze.json'
DOUBT_CLASSES = ROOT / 'data' / 'annotation' / 'v2.5' / 'doubt_classes.jsonl'


def test_v25_final_dataset_replays_labels_evidence_and_subsets():
    if not V25.exists():
        pytest.skip('v2.5 final dataset not merged yet')
    rows = overlaps.read_jsonl(V25)
    audit = json.loads(V25_AUDIT.read_text(encoding='utf-8'))
    assert len(rows) == 63
    assert Counter(row['subset'] for row in rows) == Counter({
        'natural': 30, 'conflict_supplement': 20, 'subtle_supplement': 13})
    assert audit['retained_cases'] == len(rows)
    assert audit['retained_claims'] == sum(len(row['gold_claims']) for row in rows)
    for row in rows:
        assert not overlaps.verify_case(row)
        for claim in row['gold_claims']:
            assert 'overlapping_source_labels' in claim
            for evidence in claim['evidence']:
                assert (row['context_passages'][evidence['index']]
                        [evidence['start_char']:evidence['end_char']] == evidence['quote'])
    target = audit['targets']['test_contradicted_from_subtle_conflict']
    assert target['met'] == (target['observed'] >= 8)
    assert audit['doubt_categories']['errors'] == 0
    if DOUBT_CLASSES.exists():
        doubt_rows = overlaps.read_jsonl(DOUBT_CLASSES)
        assert audit['doubt_categories']['protocol_errors'] == sum(
            bool(row.get('protocol_error')) for row in doubt_rows)


def test_v25_freeze_check_when_frozen():
    if not V25_FREEZE.exists():
        pytest.skip('v2.5 freeze not written yet')
    result = subprocess.run([sys.executable, '-m', 'annotation.v25.freeze', '--check'],
                            cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr


def test_doubt_items_union_cu_claims_and_existing_doubts():
    from annotation.v25 import doubts
    claims = [
        {'claim_id': 'x-c1', 'claim_text': 'a', 'verdict': 'SUPPORTED'},
        {'claim_id': 'x-c2', 'claim_text': 'b', 'verdict': 'CONTRADICTED'},
    ]
    case = {'id': 'x', 'context_passages': ['A.'], 'gold_claims': claims}
    index = {('x', claim['claim_id']): claim for claim in claims}
    items, skipped = doubts.build_items({'x': case}, index,
                                        {('x', 'x-c1'): 2, ('x', 'missing'): 1})
    assert {item['claim_id'] for item in items} == {'x-c1', 'x-c2'}
    assert {item['claim_id']: item['origin'] for item in items} == {
        'x-c1': 'existing_doubt', 'x-c2': 'c_u_claim'}
    assert skipped == [{'case_id': 'x', 'claim_id': 'missing',
                        'reason': 'case_or_claim_not_found'}]
    assert set(doubts.CATEGORIES) == {'agree', 'suspected_wrong_label', 'c_vs_u_boundary',
                                      'partial_claim', 'evidence_not_found'}
