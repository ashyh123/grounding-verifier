"""Offline metadata revision CLI, review page and triage; no annotation/gold decisions."""
import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def inputs(tmp_path):
    from annotation.draft_claims import draft_ragtruth, case_diagnostics
    answer = 'Note: The graph is blue. They also stated that it is local.'
    case = {'id': 'case', 'source': 'ragtruth_qa', 'split': 'dev',
            'generated_answer': answer, 'context_passages': ['The graph is blue.'],
            'source_labels': {'labels': [{'start': answer.index('local'), 'end': answer.index('local') + 5, 'text': 'local',
                                          'label_type': 'Baseless'}]},
            'provenance': {'dataset': 'RAGTruth', 'annotation_model': 'mimo-v2.6-pro'},
            'raw_draft': {'claims': [
                {'claim_text': 'The graph is blue.', 'answer_spans': [{'quote': 'the graph is blue.'}], 'reasoning': ''},
                {'claim_text': 'They stated that it is local.', 'answer_spans': [{'quote': 'it is local.'}], 'reasoning': ''}]}}
    case['claims'], notes = draft_ragtruth(case, case['raw_draft']['claims'])
    for i, claim in enumerate(case['claims']):
        claim['claim_id'] = f'claim-{i}'
    case['flags'] = case_diagnostics(case, notes)
    source = tmp_path / 'original.jsonl'
    source.write_text(json.dumps(case) + '\n')
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    base = {'source_sha256': digest, 'approved_by': 'user', 'scope': 'annotation_metadata_only',
            'case_id': 'case', 'approved_at': '2026-10-19T00:00:00Z', 'reason': 'User-approved metadata revision.'}
    def span(start, end):
        return {'quote': answer[start:end], 'start': start, 'end': end, 'match': 'exact'}
    revisions = [
        {**base, 'revision_id': 'fix-case', 'op': 'replace_answer_spans', 'claim_id': 'claim-0',
         'before': case['claims'][0]['answer_spans'], 'after': [span(6, 24)]},
        {**base, 'revision_id': 'fix-attribution', 'op': 'replace_answer_spans', 'claim_id': 'claim-1',
         'before': case['claims'][1]['answer_spans'], 'after': [span(25, len(answer))]},
        {**base, 'revision_id': 'waive-prefix', 'op': 'waive_flag', 'claim_id': 'claim-1',
         'selector': {'flag': 'partial_overlap'}},
        {**base, 'revision_id': 'manual-hold', 'op': 'require_human_review', 'claim_id': 'claim-1',
         'reason': 'Upstream locality annotation requires human adjudication.'},
    ]
    return source, case, revisions


def invoke(tmp_path, source, revisions):
    journal = tmp_path / 'revisions.jsonl'
    journal.write_text(''.join(json.dumps(r) + '\n' for r in revisions))
    output = tmp_path / 'revised.jsonl'
    env = dict(os.environ, VERIFIER_ENV_FILE=str(tmp_path / 'absent.env'), PYTHONDONTWRITEBYTECODE='1',
               ANTHROPIC_API_KEY='offline-never-use', ANTHROPIC_BASE_URL='http://127.0.0.1:9/anthropic')
    result = subprocess.run([sys.executable, '-m', 'annotation.repair_drafts', '--input', str(source),
                             '--revisions', str(journal), '--out', str(output)],
                            cwd=ROOT, env=env, capture_output=True, text=True, timeout=15)
    return result, output, journal


def test_offline_repair_cli_preserves_labels_and_raw_output_and_requires_human_review(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from annotation import review_app, triage
    source, original, revisions = inputs(tmp_path)
    before = source.read_bytes()
    result, output, journal = invoke(tmp_path, source, revisions)
    assert result.returncode == 0, result.stderr
    assert source.read_bytes() == before
    journal_before = journal.read_bytes()
    case = json.loads(output.read_text())
    assert case['raw_draft'] == original['raw_draft']
    assert case['generated_answer'] == original['generated_answer']
    assert case['source_labels'] == original['source_labels']
    assert case['provenance'] == original['provenance']
    for old, new in zip(original['claims'], case['claims']):
        assert (new['claim_id'], new['claim_text'], new['upstream_verdict']) == (
            old['claim_id'], old['claim_text'], old['upstream_verdict'])
        for span in new['answer_spans']:
            assert case['generated_answer'][span['start']:span['end']] == span['quote']
    assert case['claims'][0]['flags'] == []
    assert 'answer_gap' not in [f['flag'] for f in case['flags']]
    flags = case['claims'][1]['flags']
    assert flags[0]['status'] == 'waived' and flags[0]['waiver']['revision_id'] == 'waive-prefix'
    assert [f['flag'] for f in triage.active_flags(flags)] == ['human_adjudication_required']
    blind = {c['claim_id']: {'blind_verdict': c['upstream_verdict'], 'evidence_candidates': []}
             for c in case['claims']}
    # Add a descendant without copying its parent's flags: the hold still follows derived_from.
    child = copy.deepcopy(case['claims'][1])
    child.update(claim_id='child', flags=[], derived_from=['claim-1'])
    case['claims'].append(child)
    blind['child'] = {'blind_verdict': child['upstream_verdict'], 'evidence_candidates': []}
    plan = triage.plan([case], blind)
    assert all(c['bucket'] == 'B' and 'human_adjudication_required' in c['reasons']
               for c in plan['claims'] if c['claim_id'] in ('claim-1', 'child'))
    monkeypatch.setattr(review_app, 'DRAFTS', output)
    monkeypatch.setattr(review_app, 'decisions_path', lambda n: tmp_path / f'decisions{n}.jsonl')
    page = TestClient(review_app.make_app(1)).get('/').text
    assert '回答定位覆盖缺口' in page and '已人工豁免' in page
    assert 'Upstream locality annotation requires human adjudication.' in page
    store = review_app.Store(1)
    assert store.progress(only_flagged=True)['total'] == 1
    second, _, _ = invoke(tmp_path, source, revisions)
    assert second.returncode != 0  # never overwrite the existing derived output
    assert journal.read_bytes() == journal_before and source.read_bytes() == before
    assert not (tmp_path / 'decisions1.jsonl').exists()


@pytest.mark.parametrize('failure', ['hash', 'approval', 'before', 'nonexact', 'label_edit', 'hold_waiver'])
def test_invalid_revision_fails_before_writing_a_derived_draft(tmp_path, failure):
    source, _, revisions = inputs(tmp_path)
    if failure == 'hash':
        revisions[0]['source_sha256'] = '0' * 64
    elif failure == 'approval':
        revisions[0]['approved_by'] = 'model'
    elif failure == 'before':
        revisions[0]['before'] = []
    elif failure == 'nonexact':
        revisions[0]['after'][0]['quote'] = 'the graph is blue.'
    elif failure == 'label_edit':
        revisions[0]['op'] = 'set_verdict'
    else:
        revisions.append({**revisions[-1], 'revision_id': 'unsafe-waiver', 'op': 'waive_flag',
                          'selector': {'flag': 'human_adjudication_required'}})
    before = source.read_bytes()
    result, output, _ = invoke(tmp_path, source, revisions)
    assert result.returncode != 0 and not output.exists()
    assert source.read_bytes() == before


def test_unapproved_waiver_cannot_suppress_a_new_coverage_gap():
    from annotation.draft_claims import answer_span_gaps
    from annotation.triage import active_flags
    case = {'generated_answer': 'A genuinely unlocated additional factual assertion.', 'claims': []}
    flags = answer_span_gaps(case)
    assert len(flags) == 1 and flags[0]['quote'] == case['generated_answer']
    flags[0]['status'] = 'waived'
    assert active_flags(flags) == flags
    hold = {'flag': 'human_adjudication_required', 'status': 'waived',
            'waiver': {'approved_by': 'user', 'revision_id': 'invalid-hold-waiver'}}
    assert active_flags([hold]) == [hold]


def test_gap_waiver_is_specific_and_keeps_another_unlocated_segment_pending(tmp_path):
    from annotation.draft_claims import draft_ragtruth, case_diagnostics
    from annotation.triage import active_flags
    source, case, revisions = inputs(tmp_path)
    case['generated_answer'] = ('A user-reviewed introductory statement. Alpha is red. '
                                'A different unlocated factual assertion remains.')
    case['source_labels'] = {'labels': []}
    case['raw_draft'] = {'claims': [{'claim_text': 'Alpha is red.',
                                   'answer_spans': [{'quote': 'Alpha is red.'}], 'reasoning': ''}]}
    case['claims'], notes = draft_ragtruth(case, case['raw_draft']['claims'])
    case['claims'][0]['claim_id'] = 'claim-0'
    case['flags'] = case_diagnostics(case, notes)
    assert len(case['flags']) == 2
    source.write_text(json.dumps(case) + '\n')
    first = case['flags'][0]
    revision = {**revisions[0], 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                'op': 'waive_flag', 'revision_id': 'waive-one-gap',
                'selector': {k: first[k] for k in ('flag', 'start', 'end', 'quote')}}
    for key in ('claim_id', 'before', 'after'):
        revision.pop(key)
    result, output, _ = invoke(tmp_path, source, [revision])
    assert result.returncode == 0, result.stderr
    repaired = json.loads(output.read_text())
    assert len(repaired['flags']) == 2
    active = active_flags(repaired['flags'])
    assert len(active) == 1 and 'different unlocated factual assertion' in active[0]['quote']
