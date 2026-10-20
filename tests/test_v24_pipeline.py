"""Real CLIs with a local HTTP provider, then offline merge/freeze replay and tampering.
No hard-test verifier is executed; model boundary checks use annotation calls only.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT/'data/annotation/v2.4'


def cli(module, *args, env=None):
    return subprocess.run([sys.executable,'-m',module,*map(str,args)],cwd=ROOT,
                          capture_output=True,text=True,env=env,timeout=60)


def test_recovered_evidence_cli_preserves_labels_and_skips_u(tmp_path):
    root = tmp_path/'annotation'; root.mkdir()
    for name in ('natural.evidenced.jsonl','partial_recovered.jsonl','partial_still_excluded.jsonl','partial_split_calls.jsonl'):
        shutil.copy2(ARTIFACTS/name,root/name)
    requests = []
    expected = [json.loads(l) for l in (root/'partial_recovered.jsonl').read_text().splitlines()]
    malformed_text = next(r['claim']['claim_text'] for r in expected if r['claim']['verdict']=='SUPPORTED')

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            user = json.loads(payload['messages'][0]['content']); requests.append(user)
            numbered = re.split(r'\[passage (\d+)\]\n',user['context'])
            quote = numbered[2].strip()
            response = {'id':'fixture','type':'message','role':'assistant','model':'mimo-v2.6-pro',
                        'stop_reason':'tool_use','content':[{'type':'tool_use','id':'ev','name':'submit_evidence',
                        'input':{'evidence':[{'index':int(numbered[1]),'quote':quote}],'doubt':''}}],
                        'usage':{'input_tokens':10,'output_tokens':5}}
            if user['claim_text'] == malformed_text:
                response.update(stop_reason='end_turn',content=[{'type':'text','text':'Cannot locate a source.'}])
            body = json.dumps(response).encode()
            self.send_response(200); self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
        def log_message(self,*args): pass

    server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread = threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    env = {k:v for k,v in os.environ.items() if not any(s in k.upper() for s in ('KEY','TOKEN','SECRET','PASSWORD'))}
    env.update(VERIFIER_ENV_FILE=str(tmp_path/'absent.env'),ANNOTATION_MODEL='mimo-v2.6-pro',
               ANTHROPIC_API_KEY='offline-only',ANTHROPIC_BASE_URL=f'http://127.0.0.1:{server.server_port}/anthropic',
               VERIFIER_MODEL='deepseek-under-test')
    try:
        result = cli('annotation.v24.complete','recovered','--root',root,env=env)
        assert result.returncode == 0,result.stderr
        output = [json.loads(l) for l in (root/'recovered/evidenced.jsonl').read_text().splitlines()]
        expected_labels = {r['claim']['claim_id']:r['claim']['verdict'] for r in expected}
        assert len(requests) == sum(v!='UNSUPPORTED' for v in expected_labels.values())
        assert all(r['fixed_label']!='UNSUPPORTED' for r in requests)
        for c in output:
            for g in c['gold_claims']:
                assert g['verdict'] == expected_labels[g['claim_id']]
                assert g['evidence_status'] == ('none' if g['verdict']=='UNSUPPORTED' or g['claim_text']==malformed_text else 'exact')
                assert all(c['context_passages'][e['index']][e['start_char']:e['end_char']]==e['quote'] for e in g['evidence'])
        journal = [json.loads(l) for l in (root/'recovered/evidence_reruns.jsonl').read_text().splitlines()]
        assert sum(bool(r.get('protocol_error')) for r in journal)==1
        again = cli('annotation.v24.complete','recovered','--root',root,env=env)
        assert again.returncode != 0 and len(requests) == 10
    finally:
        server.shutdown(); server.server_close(); thread.join()


def test_merge_and_freeze_clis_replay_journals_and_reject_tampering(tmp_path):
    root = tmp_path/'annotation'
    shutil.copytree(ARTIFACTS,root,ignore=shutil.ignore_patterns('audit.json','freeze.json','final_report.md'))
    dataset = tmp_path/'hard.jsonl'
    result = cli('annotation.v24.merge','--root',root,'--out',dataset)
    assert result.returncode == 0,result.stderr
    audit = json.loads((root/'audit.json').read_text())
    assert audit['selected_cases']==50 and audit['retained_cases']<=50
    assert not audit['hard_test_verifier_run']
    assert len(audit['splits_subsets'])==9
    merged = {r['id']:r for r in (json.loads(l) for l in dataset.read_text().splitlines())}
    for row in audit['recovered_representations']['duplicates_not_scored_twice']:
        gold = merged[row['case_id']]['gold_claims']
        assert row['claim_id'] not in {g['claim_id'] for g in gold}
        original = next(g for g in gold if g['claim_id']==row['represented_by'])
        assert row['claim_id'] in {g['claim_id'] for g in original['merged_derivations']}
    replay = cli('annotation.v24.merge','--root',root,'--out',dataset,'--check')
    assert replay.returncode == 0,replay.stderr
    frozen = cli('annotation.v24.freeze','--root',root,'--data',dataset)
    assert frozen.returncode == 0,frozen.stderr
    check = cli('annotation.v24.freeze','--root',root,'--check')
    assert check.returncode == 0,check.stderr
    original = dataset.read_text()
    rows = [json.loads(l) for l in original.splitlines()]
    rows[0]['gold_claims'][0]['verdict'] = 'UNSUPPORTED' if rows[0]['gold_claims'][0]['verdict']!='UNSUPPORTED' else 'SUPPORTED'
    dataset.write_text(''.join(json.dumps(r)+'\n' for r in rows))
    assert cli('annotation.v24.merge','--root',root,'--out',dataset,'--check').returncode != 0
    assert cli('annotation.v24.freeze','--root',root,'--check').returncode != 0
    dataset.write_text(original)
    changed = root/'supplement/evidenced.jsonl'
    rows = [json.loads(l) for l in changed.read_text().splitlines()]
    rows[0]['generated_answer'] += ' Altered answer.'
    changed.write_text(''.join(json.dumps(r)+'\n' for r in rows))
    assert cli('annotation.v24.merge','--root',root,'--out',dataset,'--check').returncode != 0
