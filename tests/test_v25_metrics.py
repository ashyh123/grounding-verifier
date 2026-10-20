"""v2.5 metrics: sensitivity drops claims without turning them into extras; new groups."""
import json
import subprocess
import sys
from pathlib import Path

from eval.dataset import EvalCase
from eval.v25 import compute

ROOT = Path(__file__).resolve().parents[1]


def case(case_id, claims, subset='natural', generator='gpt-4-0613', split='test'):
    raw = {
        'id': case_id, 'split': split, 'subset': subset, 'tags': [],
        'context_passages': ['Alpha is red.'], 'generated_answer': ' '.join(c['text'] for c in claims),
        'generator_model': generator,
        'gold_claims': [{
            'claim_id': f'{case_id}-c{i}', 'claim_text': c['text'], 'verdict': c['verdict'],
            'label_source': 'ragtruth_human', 'evidence_status': 'none', 'evidence': [],
            'overlapping_source_labels': c.get('labels', []),
        } for i, c in enumerate(claims, 1)],
    }
    return raw, EvalCase.model_validate(raw)


def prediction(case_id, claims):
    return {'id': case_id, 'claims': [{'claim_text': c['text'], 'verdict': c['verdict']}
                                      for c in claims]}


def test_sensitivity_drops_claim_and_its_prediction_without_extra():
    claims = [
        {'text': 'Alpha is red.', 'verdict': 'SUPPORTED'},
        {'text': 'Beta is blue.', 'verdict': 'CONTRADICTED'},
        {'text': 'Gamma is green.', 'verdict': 'UNSUPPORTED'},
    ]
    raw, validated = case('one', claims)
    preds = {'one': prediction('one', claims)}
    report = compute([validated], {'one': 'natural'}, preds, {'one': raw}, {'one-c2'})
    assert report['reports']['all']['gold_claims'] == 3
    assert report['sensitivity']['all']['gold_claims'] == 2
    assert report['dropped_sensitive_claims'] == ['one-c2']
    assert report['dropped_sensitive_by_label'] == {'SUPPORTED': 0, 'CONTRADICTED': 1, 'UNSUPPORTED': 0}
    assert report['sensitivity']['all']['extra_predictions'] == 0
    assert report['sensitivity']['all']['hallucination_detection']['f1']['value'] == 1.0


def test_by_origin_and_generator_groups():
    claims = [
        {'text': 'Alpha is red.', 'verdict': 'SUPPORTED'},
        {'text': 'Beta is blue.', 'verdict': 'UNSUPPORTED',
         'labels': [{'label_type': 'Subtle Baseless Info'}]},
        {'text': 'Gamma is green.', 'verdict': 'CONTRADICTED',
         'labels': [{'label_type': 'Evident Conflict'}]},
    ]
    raw_a, case_a = case('a', claims, generator='gpt-4-0613')
    raw_b, case_b = case('b', [{'text': 'Delta is warm.', 'verdict': 'SUPPORTED'}],
                         subset='subtle_supplement', generator='mistral-7B-instruct')
    preds = {'a': prediction('a', claims), 'b': prediction('b', [{'text': 'Delta is warm.',
                                                                   'verdict': 'SUPPORTED'}])}
    report = compute([case_a, case_b], {'a': 'natural', 'b': 'subtle_supplement'}, preds,
                     {'a': raw_a, 'b': raw_b}, set())
    assert report['reports']['subtle_supplement']['n_cases'] == 1
    assert report['groups']['by_origin']['clean']['primary']['gold_claims'] == 2
    assert report['groups']['by_origin']['subtle']['primary']['gold_claims'] == 1
    assert report['groups']['by_origin']['evident']['primary']['gold_claims'] == 1
    assert set(report['groups']['by_generator_model']) == {'gpt-4-0613', 'mistral-7B-instruct'}


def test_cli_writes_preregistered_report(tmp_path):
    claims = [{'text': 'Alpha is red.', 'verdict': 'SUPPORTED'}]
    raw, _ = case('one', claims)
    data, preds, doubts, out = (tmp_path / name for name in
                                ('data.jsonl', 'pred.jsonl', 'doubts.jsonl', 'report.json'))
    data.write_text(json.dumps(raw) + '\n')
    preds.write_text(json.dumps(prediction('one', claims)) + '\n')
    doubts.write_text(json.dumps({'case_id': 'one', 'claim_id': 'one-c1',
                                  'category': 'agree'}) + '\n')
    result = subprocess.run([sys.executable, '-m', 'eval.v25', '--data', str(data),
                             '--predictions', str(preds), '--doubts', str(doubts),
                             '--out', str(out), '--split', 'all'],
                            cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    report = json.loads(out.read_text())
    assert report['design_version'] == '2.5'
    assert report['reports']['all']['per_label']['SUPPORTED']['f1']['value'] == 1.0
    assert report['sensitivity']['all']['gold_claims'] == 1
    assert report['doubt_classes'] == 1
