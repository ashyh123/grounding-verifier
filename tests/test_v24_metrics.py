"""CLI failures: C/U union, misses/extras, case multiplicity, small/empty classes,
deterministic bootstrap, provider errors and mismatched prediction IDs.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def case(cid, subset, texts, labels):
    return {'id':cid, 'split':'test', 'subset':subset, 'tags':[], 'context_passages':[],
            'generated_answer':' '.join(texts),
            'gold_claims':[{'claim_text':t, 'verdict':l, 'label_source':'ragtruth_human',
                            'evidence_status':'none', 'evidence':[]} for t,l in zip(texts, labels)]}


def run_report(tmp_path, cases, predictions, name='one', oracle=False):
    data, preds, out = (tmp_path / f'{name}.{ext}' for ext in ('data.jsonl','pred.jsonl','report.json'))
    data.write_text(''.join(json.dumps(c)+'\n' for c in cases))
    preds.write_text(''.join(json.dumps(p)+'\n' for p in predictions))
    result = subprocess.run([sys.executable, '-m', 'eval.v24', '--data', str(data),
                             '--predictions',str(preds),'--out',str(out), *(['--oracle'] if oracle else [])],
                            cwd=ROOT,capture_output=True,text=True,timeout=30)
    return result, json.loads(out.read_text()) if out.exists() else None


def test_cli_cu_union_misses_extras_and_subsets(tmp_path):
    texts = ['Alpha mass is ten kilograms.', 'Beta signal is green.', 'Gamma temperature is freezing.']
    cases = [case('natural','natural',texts,['SUPPORTED','CONTRADICTED','UNSUPPORTED']),
             case('supplement','conflict_supplement',['Delta velocity is slow.'],['SUPPORTED'])]
    predictions = [{'id':'natural','claims':[{'claim_text':t,'verdict':l} for t,l in
                    [(texts[0],'SUPPORTED'),(texts[1],'UNSUPPORTED'),
                     ('Zebras migrate across the savanna during summer.','UNSUPPORTED')]]},
                   {'id':'supplement','claims':[{'claim_text':'Delta velocity is slow.','verdict':'CONTRADICTED'}]}]
    result, report = run_report(tmp_path,cases,predictions)
    assert result.returncode == 0,result.stderr
    part = report['reports']['all']
    assert (part['gold_claims'],part['extra_predictions'],part['missed_gold']) == (4,1,1)
    binary = part['hallucination_detection']
    assert binary['p']['value'] == pytest.approx(1/3)
    assert binary['r']['value'] == .5 and binary['f1']['value'] == .4
    assert part['macro_f1']['value'] == pytest.approx(2/9)
    assert part['per_label']['CONTRADICTED']['n'] == 1
    assert part['per_label']['CONTRADICTED']['note'] == '仅供参考'
    assert report['reports']['natural']['hallucination_detection']['f1']['value'] == .5
    assert report['reports']['conflict_supplement']['n_cases'] == 1
    result, again = run_report(tmp_path,cases,predictions,'two')
    assert result.returncode == 0 and report == again
    result, invalid = run_report(tmp_path,cases,predictions[:-1],'missing')
    assert result.returncode != 0 and invalid is None


def test_cli_bootstrap_resamples_whole_cases_and_retains_multiplicity(tmp_path):
    cases = [case('large','natural',[f'Item {i} is valid.' for i in range(50)],['SUPPORTED']*50),
             case('small','natural',['The independent item is false.'],['CONTRADICTED'])]
    predictions = [{'id':c['id'],'claims':[{'claim_text':g['claim_text'],'verdict':'CONTRADICTED'} for g in c['gold_claims']]}
                   for c in cases]
    result, report = run_report(tmp_path,cases,predictions,oracle=True)
    assert result.returncode == 0,result.stderr
    part = report['reports']['all']
    # Case draws can be large/large or small/small; claim draws almost never have P=1.
    assert part['hallucination_detection']['p'] == {'value':1/51,'ci95':[0.,1.]}
    assert part['hallucination_detection']['f1']['ci95'] == [0.,1.]
    assert report['reports']['conflict_supplement']['metrics'] is None
    assert part['per_label']['SUPPORTED']['n'] == 50 and part['per_label']['SUPPORTED']['note'] == ''
    result, report = run_report(tmp_path,cases,[{'id':c['id'],'error':'provider failed'} for c in cases],'errors')
    assert result.returncode == 0,result.stderr
    assert report['errors'] == 2 and report['reports']['all']['missed_gold'] == 51
    assert report['reports']['all']['hallucination_detection']['f1']['value'] == 0.
