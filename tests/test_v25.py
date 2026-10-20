"""v2.5 overlap provenance: every gold verdict must replay from answer spans + upstream labels."""
import hashlib
import json
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
