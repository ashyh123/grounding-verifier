"""v2.3 public CLI scenarios plus overlap and scoring boundary failure modes."""
import copy
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from annotation.draft_claims import draft_ragtruth
from annotation.map_labels import map_case
from eval.dataset import EvalCase, load, validate
from eval.metrics import compute

ROOT = Path(__file__).resolve().parent.parent


def case_fixture():
    answer = 'Alpha is red. Beta is blue. Gamma is green.'
    raw = [{'claim_text': text, 'answer_spans': [{'quote': text}], 'reasoning': ''}
           for text in answer.split('. ') if text]
    # Preserve the sentence punctuation in exact answer quotes.
    for claim in raw:
        if not claim['claim_text'].endswith('.'):
            claim['claim_text'] += '.'
            claim['answer_spans'][0]['quote'] += '.'
    case = {'id': 'ragtruth-local', 'source': 'ragtruth_summary', 'split': 'dev',
            'generated_answer': answer, 'context_passages': ['Alpha is red. Beta is yellow.'],
            'source_labels': {'labels': [
                {'start': answer.index('Beta'), 'end': answer.index('Gamma'), 'label_type': 'Evident Conflict'},
                {'start': answer.index('Gamma'), 'end': len(answer), 'label_type': 'Subtle Baseless Info'}]},
            'generator_model': 'gpt-4-0613', 'context_words': 6,
            'source_group_id': 'local-source', 'difficulty_tags': [], 'truncated': False,
            'selection': {'seed': 20261019},
            'provenance': {'annotation_model': 'mimo-v2.6-pro', 'annotation_origin': 'llm_draft',
                           'annotation_parameters': {'temperature': 0}, 'prompt_sha256': 'a' * 64}}
    case['claims'], _ = draft_ragtruth(case, raw)
    for i, claim in enumerate(case['claims']):
        claim['claim_id'] = f'local-c{i}'
        claim['upstream_verdict'] = 'WRONG_MODEL_LABEL'
    return case


@pytest.mark.parametrize('outside', [20, 21])
def test_partial_overlap_recomputed_ignoring_old_waivers(outside):
    case = case_fixture()
    answer = 'x' * outside + 'BAD' + 'end'
    case['generated_answer'] = answer
    case['source_labels']['labels'] = [
        {'start': outside, 'end': outside + 3, 'label_type': 'Subtle Baseless Info'}]
    case['claims'] = [{'claim_id': 'partial', 'claim_text': 'claim',
                       'answer_spans': [{'quote': answer[:outside + 3]}],
                       'flags': [{'flag': 'partial_overlap', 'status': 'waived'}]}]
    mapped, removed = map_case(case)
    assert bool(removed) == (outside == 21)
    assert mapped['label_mapping']['status'] == ('excluded' if outside == 21 else 'ready')
    if outside == 21:
        assert {r['reason'] for r in removed} == {'partial_overlap', 'too_many_excluded'}
    else:
        assert mapped['claims'][0]['verdict'] == 'UNSUPPORTED'


def test_conflict_precedes_baseless_and_overlapping_spans_are_not_double_counted():
    case = case_fixture()
    case['source_labels']['labels'] = [
        {'start': 0, 'end': 13, 'label_type': 'Evident Conflict'},
        {'start': 0, 'end': 13, 'label_type': 'Subtle Baseless Info'}]
    case['claims'][0]['answer_spans'].append({'quote': 'Alpha is red'})
    mapped, _ = map_case(case)
    assert mapped['claims'][0]['verdict'] == 'CONTRADICTED'
    assert mapped['claims'][0]['label_source'] == 'ragtruth_human'


@pytest.mark.parametrize('excluded_count', [3, 4])
def test_exclusion_fraction_is_strictly_greater_than_thirty_percent(excluded_count):
    case = case_fixture()
    parts = [f'claim{i} ' + 'X' * 25 + 'BAD' for i in range(10)]
    case['generated_answer'] = '|'.join(parts)
    case['claims'] = [{'claim_id': str(i), 'claim_text': text, 'answer_spans': [{'quote': text}]}
                      for i, text in enumerate(parts)]
    case['source_labels']['labels'] = []
    for text in parts[:excluded_count]:
        start = case['generated_answer'].index(text) + len(text) - 3
        case['source_labels']['labels'].append({'start': start, 'end': start + 3,
                                                'label_type': 'Evident Conflict'})
    mapped, _ = map_case(case)
    assert mapped['label_mapping']['status'] == ('ready' if excluded_count == 3 else 'excluded')


def test_uncovered_source_requires_exactly_one_redraft_then_exclusion():
    case = case_fixture()
    case['claims'] = case['claims'][:1]
    mapped, removed = map_case(case)
    assert mapped['label_mapping']['status'] == 'needs_redraft'
    assert not removed
    mapped, removed = map_case(case, redrafted=True)
    assert mapped['label_mapping']['exclusion_reason'] == 'source_label_uncovered'
    assert removed[0]['reason'] == 'source_label_uncovered'


def test_missing_evidence_retains_accuracy_but_excludes_citation_denominators(tmp_path):
    data = {'id': 'reference', 'split': 'dev', 'tags': [],
            'generated_answer': 'Alpha is red. Beta is yellow.',
            'context_passages': ['Alpha is red. Beta is yellow.'], 'gold_claims': [
                {'claim_text': 'Alpha is red.', 'verdict': 'SUPPORTED', 'evidence': [],
                 'label_source': 'ragtruth_human', 'evidence_status': 'none'},
                {'claim_text': 'Beta is yellow.', 'verdict': 'CONTRADICTED',
                 'evidence': [{'index': 0, 'quote': 'Beta is yellow.'}],
                 'label_source': 'ragtruth_human', 'evidence_status': 'exact'}]}
    path = tmp_path / 'hard.jsonl'
    path.write_text(json.dumps(data) + '\n')
    cases = load(path)
    predictions = {'reference': {'claims': [
        {'claim_text': g['claim_text'], 'verdict': g['verdict'], 'citations': [
            {'index': 0, 'start_char': 0, 'end_char': 13, 'quote': 'Alpha is red.'}]
         if i == 0 else [{'index': 0, 'start_char': 14, 'end_char': 29, 'quote': 'Beta is yellow.'}]}
        for i, g in enumerate(data['gold_claims'])]}}
    score = compute(cases, predictions)
    assert score['claim_accuracy_all_gold'] == 1
    assert score['citation_counts'] == {'predicted': 1, 'hit': 1, 'gold': 1, 'gold_hit': 1, 'invalid': 0}
    assert score['citation_precision'] == score['citation_recall'] == 1
    for field, value in [('label_source', None), ('evidence_status', 'exact')]:
        invalid = copy.deepcopy(data)
        invalid['gold_claims'][0][field] = value
        assert validate([EvalCase.model_validate(invalid)])
    # Historical data still requires S/C reference evidence.
    for g in data['gold_claims']:
        g.pop('label_source'); g.pop('evidence_status')
    assert validate([EvalCase.model_validate(data)])


@pytest.mark.parametrize('mode', ['exact', 'not_found', 'nonexact', 'doubt', 'label_injection', 'no_tool', '401'])
def test_mapping_and_evidence_cli_with_local_provider(tmp_path, mode):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append(payload)
            fixed = json.loads(payload['messages'][0]['content'])['fixed_label']
            quote = 'Alpha is red.' if fixed == 'SUPPORTED' else 'Beta is yellow.'
            data = {'evidence': [{'index': 0, 'quote': quote}], 'doubt': ''}
            if mode == 'not_found':
                data['evidence'] = []
            elif mode == 'nonexact':
                data['evidence'][0]['quote'] = quote.lower()
            elif mode == 'doubt':
                data['doubt'] = 'The human label may be wrong.'
            elif mode == 'label_injection':
                data['verdict'] = 'UNSUPPORTED'
            body = {'id': 'msg_local', 'type': 'message', 'role': 'assistant',
                    'model': 'mimo-v2.6-pro', 'stop_reason': 'end_turn' if mode == 'no_tool' else 'tool_use',
                    'content': [{'type': 'text', 'text': 'No quotation found.'}] if mode == 'no_tool' else [{'type': 'tool_use', 'id': 'tool_local', 'name': 'submit_evidence', 'input': data}],
                    'usage': {'input_tokens': 11, 'output_tokens': 7}}
            encoded = json.dumps(body).encode()
            self.send_response(401 if mode == '401' else 200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(encoded)))
            self.end_headers(); self.wfile.write(encoded)

        def log_message(self, *args):
            pass

    drafts, out = tmp_path / 'drafts.jsonl', tmp_path / 'pilot'
    drafts.write_text(json.dumps(case_fixture()) + '\n')
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    env = {k: v for k, v in os.environ.items() if not any(s in k.upper() for s in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD'))}
    env.update(VERIFIER_ENV_FILE=str(tmp_path / 'absent.env'), ANNOTATION_MODEL='mimo-v2.6-pro',
               ANTHROPIC_API_KEY='local-only', VERIFIER_MODEL='deepseek-under-test',
               ANTHROPIC_BASE_URL=f'http://127.0.0.1:{server.server_port}/anthropic')
    try:
        mapped = subprocess.run([sys.executable, '-m', 'annotation.map_labels', '--drafts', str(drafts),
                                 '--out-dir', str(out)], cwd=ROOT, env=env, capture_output=True, text=True)
        assert mapped.returncode == 0, mapped.stderr
        assert not requests
        mapping = (out / 'mapped.jsonl').read_bytes()
        command = [sys.executable, '-m', 'annotation.find_evidence', '--mapped', str(out / 'mapped.jsonl')]
        result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
        failed = mode == '401'
        assert (result.returncode != 0) == failed, result.stdout + result.stderr
        assert (out / 'mapped.jsonl').read_bytes() == mapping
        calls = [json.loads(s) for s in (out / 'evidence_calls.jsonl').read_text().splitlines()]
        assert len(requests) == (1 if failed else 2)  # UNSUPPORTED never calls the provider.
        for request in requests:
            user = json.loads(request['messages'][0]['content'])
            assert set(user) == {'context_passages', 'claim_text', 'fixed_label'}
            assert request['model'] == 'mimo-v2.6-pro'
        if failed:
            assert calls[0]['error']
            assert not (out / 'evidenced.jsonl').exists()
            resumed = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
            assert resumed.returncode != 0 and len(requests) == 1
        else:
            evidenced = json.loads((out / 'evidenced.jsonl').read_text())
            assert [c['verdict'] for c in evidenced['claims']] == ['SUPPORTED', 'CONTRADICTED', 'UNSUPPORTED']
            assert [r['evidence_status'] for r in calls[:2]] == [
                'none' if mode in ('not_found', 'nonexact', 'label_injection', 'no_tool') else 'exact'] * 2
            assert all(len(r['provenance']['prompt_sha256']) == 64 for r in calls)
            assert sum(r['provenance']['input_tokens'] for r in calls) == 22
            doubts = (out / 'model_doubts.jsonl').read_text().splitlines()
            assert len(doubts) == (2 if mode in ('not_found', 'doubt', 'label_injection', 'no_tool') else 0)
            # A crash after all checkpoints but before final materialization must not spend again.
            (out / 'evidenced.jsonl').unlink()
            (out / 'evidence-report.json').unlink()
            previous = (out / 'evidence_calls.jsonl').read_bytes()
            resumed = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
            assert resumed.returncode == 0, resumed.stderr
            assert (out / 'evidence_calls.jsonl').read_bytes() == previous
            assert len(requests) == 2
            merged, audit, frozen = tmp_path / 'hard.jsonl', tmp_path / 'audit.json', tmp_path / 'freeze.json'
            merge_command = [sys.executable, '-m', 'annotation.merge', '--runs', str(out),
                             '--drafts', str(drafts), '--candidates', str(drafts),
                             '--out', str(merged), '--audit', str(audit)]
            merge = subprocess.run(merge_command, cwd=ROOT, env=env, capture_output=True, text=True)
            assert merge.returncode == 0, merge.stderr
            gold = load(merged)[0].gold_claims
            assert [g.verdict.value for g in gold] == ['SUPPORTED', 'CONTRADICTED', 'UNSUPPORTED']
            assert all(g.label_source == 'ragtruth_human' for g in gold)
            counts = json.loads(audit.read_text())
            assert counts['retained_claims'] == 3 and counts['excluded_claims'] == 0
            assert counts['by_label']['CONTRADICTED']['retained'] == 1
            assert counts['evidence']['exact_claims'] == (0 if mode in (
                'not_found', 'nonexact', 'label_injection', 'no_tool') else 2)
            freeze = subprocess.run([sys.executable, '-m', 'annotation.freeze', '--data', str(merged),
                                     '--audit', str(audit), '--out', str(frozen)],
                                    cwd=ROOT, env=env, capture_output=True, text=True)
            assert freeze.returncode == 0, freeze.stderr
            check_command = [sys.executable, '-m', 'annotation.freeze', '--check', '--out', str(frozen)]
            assert subprocess.run(check_command, cwd=ROOT, env=env, capture_output=True).returncode == 0
            # Frozen inputs are checked, and merging refuses later label edits or missing cases.
            (out / 'mapped.jsonl').write_bytes(mapping + b'\n')
            assert subprocess.run(check_command, cwd=ROOT, env=env, capture_output=True).returncode != 0
            (out / 'mapped.jsonl').write_bytes(mapping)
            original_evidenced = (out / 'evidenced.jsonl').read_bytes()
            corrupted = json.loads(original_evidenced)
            corrupted['claims'][0]['verdict'] = 'UNSUPPORTED'
            (out / 'evidenced.jsonl').write_text(json.dumps(corrupted) + '\n')
            merged.unlink(); audit.unlink()
            rejected = subprocess.run(merge_command, cwd=ROOT, env=env, capture_output=True, text=True)
            assert rejected.returncode != 0 and not merged.exists()
            assert len(requests) == 2
    finally:
        server.shutdown(); server.server_close(); thread.join()


@pytest.mark.parametrize('still_uncovered', [False, True])
def test_uncovered_redraft_cli_preserves_source_and_records_one_attempt(tmp_path, still_uncovered):
    original = case_fixture()
    full_claims = copy.deepcopy(original['claims'])
    original['claims'] = original['claims'][:1]
    original.update(generator_model='gpt-4-0613', context_words=7, source_group_id='local-source',
                    difficulty_tags=[], truncated=False, selection={'seed': 20261019})
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append(request)
            claims = full_claims[:1] if still_uncovered else full_claims
            output = {'claims': [{'claim_text': c['claim_text'],
                                  'answer_spans': [{'quote': s['quote']} for s in c['answer_spans']],
                                  'reasoning': ''} for c in claims]}
            body = {'id': 'msg_local', 'type': 'message', 'role': 'assistant',
                    'model': 'mimo-v2.6-pro', 'stop_reason': 'tool_use',
                    'content': [{'type': 'tool_use', 'id': 'tool_local', 'name': 'submit_claims', 'input': output}],
                    'usage': {'input_tokens': 11, 'output_tokens': 7}}
            encoded = json.dumps(body).encode()
            self.send_response(200); self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(encoded)))
            self.end_headers(); self.wfile.write(encoded)

        def log_message(self, *args):
            pass

    source, out = tmp_path / 'drafts.jsonl', tmp_path / 'pilot'
    source.write_text(json.dumps(original) + '\n')
    before = source.read_bytes()
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    env = {k: v for k, v in os.environ.items() if not any(s in k.upper() for s in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD'))}
    env.update(VERIFIER_ENV_FILE=str(tmp_path / 'absent.env'), ANNOTATION_MODEL='mimo-v2.6-pro',
               ANTHROPIC_API_KEY='local-only', VERIFIER_MODEL='deepseek-under-test',
               ANTHROPIC_BASE_URL=f'http://127.0.0.1:{server.server_port}/anthropic')
    command = [sys.executable, '-m', 'annotation.map_labels', '--drafts', str(source),
               '--out-dir', str(out), '--redraft-uncovered']
    try:
        result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        assert source.read_bytes() == before and len(requests) == 1
        # The model still receives context + full answer, not the upstream labels or missed spans.
        wire = json.dumps(requests[0])
        assert 'label_type' not in wire and 'source_labels' not in wire and 'Evident Conflict' not in wire
        mapped = json.loads((out / 'mapped.jsonl').read_text())
        assert mapped['label_mapping']['status'] == ('excluded' if still_uncovered else 'ready')
        assert mapped['label_mapping']['redraft_attempted']
        revision = json.loads((out / 'redrafts.jsonl').read_text())
        assert revision['provenance']['draft_call']['input_tokens'] == 11
        assert revision['provenance']['draft_call']['finished_at']
        assert all(c['derived_from'] == ['local-c0'] and '-redraft1-' in c['claim_id'] for c in revision['claims'])
        for name in ['mapped.jsonl', 'excluded.jsonl', 'mapping-report.json']:
            (out / name).unlink()
        rerun = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
        assert rerun.returncode == 0 and len(requests) == 1
    finally:
        server.shutdown(); server.server_close(); thread.join()
