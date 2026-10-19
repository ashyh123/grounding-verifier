"""Real drafting CLI against a local HTTP provider: no paid/model calls."""
import hashlib
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize('mode', ['success', '401', 'schema', 'truncated'])
def test_drafting_cli_keeps_labels_off_the_wire_and_checkpoints(tmp_path, mode):
    requests = []
    claims = [
        {'claim_text': 'Alpha is red.', 'answer_spans': [{'quote': 'Alpha is red.'}],
         'reasoning': 'One assertion.'},
        {'claim_text': 'Beta is blue.', 'answer_spans': [{'quote': 'Beta is blue.'}],
         'reasoning': 'Another assertion.'},
    ]

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append((self.path, self.headers['api-key'], payload))
            data = {'claims': claims}
            if mode == 'schema':
                data = {'claims': [{**claims[0], 'verdict': 'SUPPORTED'}]}
            body = {'id': 'msg_offline', 'type': 'message', 'role': 'assistant',
                    'model': 'mimo-v2.6-pro', 'stop_reason': 'max_tokens' if mode == 'truncated' else 'tool_use',
                    'content': [{'type': 'tool_use', 'id': 'tool_offline', 'name': 'submit_claims',
                                 'input': data}],
                    'usage': {'input_tokens': 11, 'output_tokens': 7,
                              'cache_read_input_tokens': 3, 'cache_creation_input_tokens': 2}}
            encoded = json.dumps(body).encode()
            self.send_response(401 if mode == '401' else 200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, *args):
            pass

    cases = []
    for i, task in enumerate(['summary', 'summary', 'qa', 'qa', 'data2txt', 'summary']):
        cases.append({
            'id': f'ragtruth-{i}', 'source': f'ragtruth_{task}',
            'split': 'dev' if i < 5 else 'test',
            'context_passages': ['Alpha is red and square.', 'Beta is blue.'],
            'generated_answer': 'Alpha is red. Beta is blue.', 'generator_model': 'gpt-4-0613',
            'context_words': 8, 'source_group_id': f'source-{i}', 'difficulty_tags': [],
            'truncated': False, 'selection': {'seed': 20261019},
            'source_labels': {'question': 'PRIVATE_QUESTION_SENTINEL', 'labels': [
                {'start': 0, 'end': 13, 'text': 'PRIVATE_LABEL_SENTINEL', 'label_type': 'Conflict'}]},
            'provenance': {'dataset': 'RAGTruth'},
        })
    candidates, output = tmp_path / 'candidates.jsonl', tmp_path / 'drafts.jsonl'
    candidates.write_text(''.join(json.dumps(c) + '\n' for c in cases))
    candidate_bytes = candidates.read_bytes()
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env = {k: v for k, v in os.environ.items()
           if not any(s in k.upper() for s in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD'))}
    env.update(VERIFIER_ENV_FILE=str(tmp_path / 'absent.env'), ANNOTATION_MODEL='mimo-v2.6-pro',
               ANTHROPIC_API_KEY='offline-draft-key', VERIFIER_API_KEY='wrong-verifier-key',
               ANTHROPIC_BASE_URL=f'http://127.0.0.1:{server.server_port}/anthropic',
               VERIFIER_MODEL='deepseek-under-test', VERIFIER_BASE_URL='https://api.deepseek.com/v1',
               VERIFIER_EXTRA_BODY='{"model":"wrong-model","thinking":{"type":"enabled"}}')
    command = [sys.executable, '-m', 'annotation.draft_claims', '--split', 'dev',
               '--only', *(c['id'] for c in cases[:5]), '--candidates', str(candidates), '--out', str(output)]
    try:
        completed = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
        assert (completed.returncode == 0) == (mode == 'success'), completed.stdout + completed.stderr
        records = [json.loads(line) for line in output.read_text().splitlines()]
        assert len(records) == len(requests) == (5 if mode == 'success' else 1)
        assert candidates.read_bytes() == candidate_bytes
        for path, key, payload in requests:
            assert path == '/anthropic/v1/messages' and key == 'offline-draft-key'
            assert payload['model'] == 'mimo-v2.6-pro'
            assert payload['thinking'] == {'type': 'disabled'}
            wire = json.dumps(payload)
            assert 'PRIVATE_LABEL_SENTINEL' not in wire and 'PRIVATE_QUESTION_SENTINEL' not in wire
            assert 'source_labels' not in wire and 'deepseek' not in wire
            assert cases[0]['generated_answer'] in payload['messages'][0]['content']
            for passage in cases[0]['context_passages']:
                assert passage in payload['messages'][0]['content']
        for record in records:
            assert record['split'] == 'dev'
            provenance = record['provenance']
            assert provenance['annotation_model'] == 'mimo-v2.6-pro'
            assert len(provenance['prompt_sha256']) == 64
            call = provenance['draft_call']
            assert call['calls'] == 1 and call['retries'] == 0
            assert call['started_at'] <= call['finished_at']
            if mode == 'success':
                assert call['input_tokens'] == 16 and call['output_tokens'] == 7
                assert record['raw_draft'] == {'claims': claims}
                assert [c['upstream_verdict'] for c in record['claims']] == ['CONTRADICTED', 'SUPPORTED']
                assert record['generated_answer'] == cases[0]['generated_answer']
                assert all('model_verdict' not in c and c['evidence'] == [] for c in record['claims'])
                for claim in record['claims']:
                    for span in claim['answer_spans']:
                        assert record['generated_answer'][span['start']:span['end']] == span['quote']
            else:
                assert record['draft_error'] and not record['claims']
        if mode == 'success':
            previous = output.read_bytes()
            resumed = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
            assert resumed.returncode == 0
            assert output.read_bytes() == previous and len(requests) == 5
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize('outside', [20, 21])
def test_partial_overlap_threshold_and_disconnected_answer_spans(outside):
    from annotation.draft_claims import draft_ragtruth
    answer = 'A' * outside + ' bad ' + 'Z' * 40
    label = {'start': outside, 'end': outside + 5, 'label_type': 'Baseless', 'text': ' bad '}
    case = {'generated_answer': answer, 'source_labels': {'labels': [label]}}
    drafts, _ = draft_ragtruth(case, [{
        'claim_text': 'An atomic assertion.', 'answer_spans': [{'quote': answer[:outside + 5]}],
        'reasoning': 'Explanation.',
    }])
    assert drafts[0]['upstream_verdict'] == 'UNSUPPORTED'
    assert bool(drafts[0]['flags']) == (outside > 20)
    # A disjoint tail that is not selected must not affect the overlap calculation.
    assert len(drafts[0]['answer_spans']) == 1


@pytest.mark.parametrize('quote', ['Alpha  is red.', 'Alpha'])
def test_nonexact_or_ambiguous_answer_quote_does_not_assign_an_upstream_label(quote):
    from annotation.draft_claims import draft_ragtruth
    case = {'generated_answer': 'Alpha is red. Alpha is blue.', 'source_labels': {'labels': []}}
    drafts, notes = draft_ragtruth(case, [{'claim_text': 'Alpha is red.',
                                         'answer_spans': [{'quote': quote}], 'reasoning': ''}])
    claim = drafts[0]
    assert claim['answer_spans'][0] == {'quote': quote, 'start': None, 'end': None, 'match': 'candidate_only'}
    assert claim['upstream_verdict'] is None and notes and claim['flags']
