"""v2.4 CLI scenarios and exact-quote occurrence boundary cases."""
import copy
import json
import os
import re
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path

import pytest

from annotation.v24.evidence import locate

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('passages,index,quote,corrected',[
    (['header','one unique quote'],0,'unique',True),
    (['unique','unique'],0,'unique',False),
    (['header','unique unique'],0,'unique',None),
    (['header','unique','unique'],0,'unique',None),
    (['header','Exact Quote'],0,'exact quote',None),
    (['header','banana'],0,'ana',None),
    (['header','unique'],99,'unique',True),
    (['header','unique'],True,'unique',None),
])
def test_exact_quote_occurrences_control_index_repair(passages,index,quote,corrected):
    raw=[{'index':index,'quote':quote}];unchanged=copy.deepcopy(raw)
    exact,rejected=locate(passages,raw)
    assert raw==unchanged
    if corrected is None:
        assert not exact and rejected==raw
    else:
        assert not rejected and len(exact)==1
        e=exact[0]
        assert passages[e['index']][e['start_char']:e['end_char']]==quote
        assert bool(e.get('index_corrected'))==corrected
        if corrected:assert e['original_index']==index


def test_offline_and_rerun_cli_preserve_old_exact_and_fixed_labels(tmp_path):
    passages=['Header.','Alpha is red. Beta is blue. Gamma is yellow.']
    claims=[{'claim_id':f'c{i}','claim_text':text,'verdict':verdict,'evidence':[],
             'evidence_status':'none','label_source':'ragtruth_human'}
            for i,(text,verdict) in enumerate([('Alpha is red.','SUPPORTED'),('Beta is blue.','CONTRADICTED'),
                                                ('Gamma is yellow.','SUPPORTED'),('Delta exists.','UNSUPPORTED')])]
    claims[0].update(evidence_status='exact',evidence=[{'index':1,'quote':'Alpha is red.','start_char':0,'end_char':13,'match':'exact'}])
    case={'id':'local','context_passages':passages,'gold_claims':claims}
    data,old_calls=tmp_path/'data.jsonl',tmp_path/'calls.jsonl'
    data.write_text(json.dumps(case)+'\n');before=data.read_bytes()
    calls=[{'case_id':'local','claim_id':g['claim_id'],'verdict':g['verdict'],'evidence_status':g['evidence_status'],
            'provenance':{'prompt_sha256':'a'*64},'raw_evidence':{'evidence':
               [{'index':1 if i==0 else 0,'quote':g['claim_text']}] if i<2 else [],'doubt':''}}
           for i,g in enumerate(claims)]
    old_calls.write_text(''.join(json.dumps(c)+'\n' for c in calls))
    out=tmp_path/'out';requests=[]

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            user=json.loads(payload['messages'][0]['content']);requests.append(user)
            pieces=re.split(r'\[passage (\d+)\]\n',user['context'])
            numbered={int(pieces[i]):pieces[i+1].strip() for i in range(1,len(pieces),2)}
            quote=user['claim_text'];index=next(i for i,p in numbered.items() if quote in p)
            body={'id':'local','type':'message','role':'assistant','model':'mimo-v2.6-pro','stop_reason':'tool_use',
                  'content':[{'type':'tool_use','id':'tool','name':'submit_evidence','input':{
                      'evidence':[{'index':index,'quote':quote}],'doubt':''}}],
                  'usage':{'input_tokens':10,'output_tokens':5}}
            encoded=json.dumps(body).encode();self.send_response(200);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(encoded)));self.end_headers();self.wfile.write(encoded)
        def log_message(self,*args):pass

    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    env={k:v for k,v in os.environ.items() if not any(s in k.upper() for s in ('KEY','TOKEN','SECRET','PASSWORD'))}
    env.update(VERIFIER_ENV_FILE=str(tmp_path/'absent.env'),ANNOTATION_MODEL='mimo-v2.6-pro',ANTHROPIC_API_KEY='offline-only',
               ANTHROPIC_BASE_URL=f'http://127.0.0.1:{server.server_port}/anthropic',VERIFIER_MODEL='deepseek-under-test')
    common=['--data',str(data),'--calls',str(old_calls),'--out-dir',str(out)]
    try:
        result=subprocess.run([sys.executable,'-m','annotation.v24.evidence','offline',*common],cwd=ROOT,env=env,capture_output=True,text=True)
        assert result.returncode==0,result.stderr
        assert not requests and data.read_bytes()==before
        report=json.loads((out/'offline_report.json').read_text());assert report['recovered_claims']==1
        result=subprocess.run([sys.executable,'-m','annotation.v24.evidence','rerun',*common],cwd=ROOT,env=env,capture_output=True,text=True,timeout=30)
        assert result.returncode==0,result.stderr
        assert len(requests)==2 and {r['claim_text'] for r in requests}=={'Beta is blue.','Gamma is yellow.'}
        final=json.loads((out/'natural.evidenced.jsonl').read_text())
        assert [g['verdict'] for g in final['gold_claims']]==[g['verdict'] for g in claims]
        assert final['gold_claims'][0]['evidence']==claims[0]['evidence']
        assert [g['evidence_status'] for g in final['gold_claims']]==['exact','exact','exact','none']
        assert len(final['gold_claims'][1]['evidence'])==1
        report=json.loads((out/'rerun_report.json').read_text())
        assert report['new_prompt_additional_claims_after_offline']==1
        assert report['usage']['calls']==2 and data.read_bytes()==before
    finally:
        server.shutdown();server.server_close();thread.join()


def test_supplement_cli_uses_fixed_quotas_and_excludes_natural_sources(tmp_path):
    ids=[]
    for name in ['one','two']:
        destination=tmp_path/name
        result=subprocess.run([sys.executable,'-m','annotation.v24.select','--out-dir',str(destination)],
                              cwd=ROOT,capture_output=True,text=True,timeout=60)
        assert result.returncode==0,result.stderr
        cases=[json.loads(l) for l in (destination/'supplement_candidates.jsonl').read_text().splitlines()]
        natural=[json.loads(l) for l in (destination/'natural_cases.jsonl').read_text().splitlines()]
        assert len(cases)==20 and len(natural)==30
        from collections import Counter
        counts=Counter((c['provenance']['task_type'],c['split']) for c in cases)
        assert counts=={('Summary','dev'):2,('Summary','test'):6,('Data2txt','dev'):2,
                        ('Data2txt','test'):6,('QA','dev'):1,('QA','test'):3}
        assert len({c['source_group_id'] for c in cases})==20
        assert not {c['provenance']['source_id'] for c in natural}&{c['provenance']['source_id'] for c in cases}
        assert all(c['subset']=='conflict_supplement' and any('Conflict' in l['label_type'] for l in c['source_labels']['labels']) for c in cases)
        assert all(c['subset']=='natural' for c in natural)
        ids.append([c['id'] for c in cases])
    assert ids[0]==ids[1]


def test_partial_recovery_cli_sends_boundaries_without_upstream_types(tmp_path):
    text='Alpha is a sufficiently long red object and Beta is blue.'
    cut=text.index('Beta')
    parent={'claim_id':'parent','claim_text':text,'answer_spans':[{'quote':text,'start':0,'end':len(text),'match':'exact'}]}
    case={'id':'local','source':'ragtruth_summary','generated_answer':text,
          'source_labels':{'labels':[{'start':cut,'end':len(text),'label_type':'Evident Conflict'}]}}
    candidates,excluded=tmp_path/'candidates.jsonl',tmp_path/'excluded.jsonl'
    candidates.write_text(json.dumps(case)+'\n')
    excluded.write_text(json.dumps({'case_id':'local','claim_id':'parent','reason':'partial_overlap','claim':parent})+'\n')
    requests=[]

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            request=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append(request)
            outputs=[{'claim_text':q,'answer_spans':[{'quote':q}],'reasoning':'Split at the supplied boundary.'}
                     for q in ['Alpha is a sufficiently long red object','Beta is blue.']]
            body={'id':'local','type':'message','role':'assistant','model':'mimo-v2.6-pro','stop_reason':'tool_use',
                  'content':[{'type':'tool_use','id':'tool','name':'submit_claims','input':{'claims':outputs}}],
                  'usage':{'input_tokens':10,'output_tokens':5}}
            encoded=json.dumps(body).encode();self.send_response(200);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(encoded)));self.end_headers();self.wfile.write(encoded)
        def log_message(self,*args):pass

    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    env={k:v for k,v in os.environ.items() if not any(s in k.upper() for s in ('KEY','TOKEN','SECRET','PASSWORD'))}
    env.update(VERIFIER_ENV_FILE=str(tmp_path/'absent.env'),ANNOTATION_MODEL='mimo-v2.6-pro',ANTHROPIC_API_KEY='offline-only',
               ANTHROPIC_BASE_URL=f'http://127.0.0.1:{server.server_port}/anthropic',VERIFIER_MODEL='deepseek-under-test')
    try:
        out=tmp_path/'out'
        result=subprocess.run([sys.executable,'-m','annotation.v24.recover','--candidates',str(candidates),
                               '--excluded',str(excluded),'--out-dir',str(out)],cwd=ROOT,env=env,capture_output=True,text=True,timeout=30)
        assert result.returncode==0,result.stderr
        assert len(requests)==1
        wire=json.dumps(requests[0]);assert 'Evident Conflict' not in wire and 'source_labels' not in wire
        user=json.loads(requests[0]['messages'][0]['content'])
        assert user['original_sentence']==text and user['cut_positions_in_answer']==[cut]
        recovered=[json.loads(l) for l in (out/'partial_recovered.jsonl').read_text().splitlines()]
        assert [r['claim']['verdict'] for r in recovered]==['SUPPORTED','CONTRADICTED']
        assert all(r['claim']['derived_from']==['parent'] and r['claim']['claim_id']!='parent' for r in recovered)
        assert case['generated_answer']==json.loads(candidates.read_text())['generated_answer']
    finally:
        server.shutdown();server.server_close();thread.join()
