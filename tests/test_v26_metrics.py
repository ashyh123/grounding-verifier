"""v2.6 response-level metrics, sentence localisation, citations, groups and the data-file runner."""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from eval import v26

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data' / 'eval_ragtruth_resp.v2.6.jsonl'


def case(cid='c', gold=True, answer='Alpha is red. Beta is blue. Gamma is green.', bad=(1,),
         passages=('Alpha is red. Beta is blue.', 'Gamma is green.'), task='QA', model='m',
         label_type='Evident Conflict'):
    from annotation.v26.sentences import gold_sentences
    sentences = split = None
    labels = []
    for i in bad:
        # label the i-th sentence (by content)
        tiles = gold_sentences(answer, [])
        t = tiles[i]
        labels.append({'start': t['start'], 'end': t['start'] + len(t['text'].strip()),
                       'text': t['text'].strip(), 'label_type': label_type})
    row = {'id': cid, 'task': task, 'generator_model': model, 'generated_answer': answer,
           'context_passages': list(passages), 'source_labels': {'labels': labels if gold else []}}
    return v26.case_from_row(row)


def pred(*claims, meta=None):
    return {'id': 'c', 'claims': [{'claim_text': t, 'verdict': v, 'reasoning': '', 'citations': cits}
                                  for t, v, cits in claims], 'meta': meta or {}}


def cit(index, quote, passages=('Alpha is red. Beta is blue.', 'Gamma is green.')):
    start = passages[index].find(quote)
    return {'index': index, 'quote': quote, 'start_char': start, 'end_char': start + len(quote)}


# ---- registered prediction rule and failure handling
def test_prediction_rule_is_any_contradicted_or_unsupported():
    assert not v26.predicted_bad(pred(('x', 'SUPPORTED', [])))
    assert v26.predicted_bad(pred(('x', 'SUPPORTED', []), ('y', 'UNSUPPORTED', [])))
    assert v26.predicted_bad(pred(('y', 'CONTRADICTED', [])))
    assert not v26.predicted_bad(pred())


def test_failures_count_as_wrong_on_the_opposite_side_of_gold():
    positive, negative = case(gold=True), case(gold=False)
    assert list(v26.answer_vector(positive, {'id': 'c', 'error': 'boom'})) == [0, 0, 1, 0]
    assert list(v26.answer_vector(negative, {'id': 'c', 'error': 'boom'})) == [0, 1, 0, 0]
    assert list(v26.answer_vector(positive, None)) == [0, 0, 1, 0]
    assert list(v26.answer_vector(positive, pred(('y', 'UNSUPPORTED', [])))) == [1, 0, 0, 0]
    assert list(v26.answer_vector(negative, pred(('y', 'SUPPORTED', [])))) == [0, 0, 0, 1]


def test_excluding_failures_report_drops_failed_cases():
    cases = [case('a', True), case('b', False), case('c', True)]
    preds = {'a': pred(('y', 'UNSUPPORTED', [])), 'b': pred(('y', 'SUPPORTED', [])),
             'c': {'id': 'c', 'error': 'x'}}
    report = v26.compute(cases, {'minimal': preds}, price_in=0, price_out=0)['methods']['minimal']
    assert report['failures'] == 1
    assert report['answer_level']['main']['n_cases'] == 3
    assert report['answer_level']['excluding_failures']['n_cases'] == 2
    assert report['answer_level']['main']['metrics']['recall']['value'] == 0.5
    assert report['answer_level']['excluding_failures']['metrics']['recall']['value'] == 1.0


def test_answer_scores_known_values():
    p, r, f1, bal = v26.answer_scores(np.array([2, 1, 1, 4]))
    assert p == pytest.approx(2 / 3) and r == pytest.approx(2 / 3) and f1 == pytest.approx(2 / 3)
    assert bal == pytest.approx((2 / 3 + 4 / 5) / 2)
    nothing = v26.answer_scores(np.array([0, 0, 0, 5]))
    assert np.isnan(nothing[0]) and np.isnan(nothing[2])  # no positives anywhere: undefined, not 0


def test_bootstrap_constants_and_reproducibility():
    assert (v26.BOOTSTRAP_REPLICATES, v26.BOOTSTRAP_SEED) == (10000, 20261022)
    per_case = np.array([[1, 0, 0, 0]] * 5 + [[0, 1, 0, 0]] * 3 + [[0, 0, 1, 0]] * 2 + [[0, 0, 0, 1]] * 4)
    a = v26.metric_block(per_case, v26.answer_scores, v26.ANSWER_NAMES)
    b = v26.metric_block(per_case, v26.answer_scores, v26.ANSWER_NAMES)
    assert a == b
    f1 = a['metrics']['f1']
    assert f1['ci95'][0] <= f1['value'] <= f1['ci95'][1]
    assert v26.metric_block(per_case[:0], v26.answer_scores, v26.ANSWER_NAMES)['metrics'] is None


# ---- paired comparison and wording rule
def matrix(rows):
    return np.array(rows, dtype=np.int64)


def test_paired_difference_identical_methods_has_no_evidence():
    m = matrix([[1, 0, 0, 0], [0, 0, 0, 1], [0, 1, 0, 0], [0, 0, 1, 0]] * 5)
    block = v26.paired_difference(m, m.copy(), replicates=500)
    assert block['f1']['value'] == 0 and block['f1']['ci95'] == [0.0, 0.0]
    assert block['f1']['excludes_zero'] is False
    assert 'no evidence of a difference' in v26.wording('A', 'B', block['f1'])


def test_paired_difference_clear_winner_and_antisymmetry():
    good = matrix([[1, 0, 0, 0], [0, 0, 0, 1]] * 20)
    bad = matrix([[0, 0, 1, 0], [0, 1, 0, 0]] * 20)
    ab = v26.paired_difference(good, bad, replicates=500)
    ba = v26.paired_difference(bad, good, replicates=500)
    assert ab['f1']['excludes_zero'] and ab['f1']['value'] > 0
    assert ab['f1']['ci95'][0] == pytest.approx(-ba['f1']['ci95'][1])  # same resamples for both
    assert v26.wording('good', 'bad', ab['f1']).startswith('good is better than bad')
    assert v26.wording('bad', 'good', ba['f1']).startswith('good is better than bad')
    with pytest.raises(ValueError):
        v26.paired_difference(good, bad[:-2])


def test_compute_emits_comparisons_and_the_wording_rule():
    cases = [case(f'c{i}', gold=i % 2 == 0) for i in range(8)]
    ok = {c.id: pred(('y', 'UNSUPPORTED' if c.gold_response else 'SUPPORTED', [])) for c in cases}
    flag_all = {c.id: pred(('y', 'UNSUPPORTED', [])) for c in cases}
    out = v26.compute(cases, {'baseline': flag_all, 'minimal': ok, 'optimized': ok})
    pairs = {(b['a'], b['b']) for b in out['paired_f1_difference']['main']}
    assert pairs == {('optimized', 'minimal'), ('minimal', 'baseline'), ('optimized', 'baseline')}
    assert 'excludes 0' in out['conclusion_wording_rule'] and 'prediction_rule' in out
    assert out['bootstrap'] == {'unit': 'case', 'replicates': 10000, 'seed': 20261022,
                                'interval': 'percentile 2.5/97.5'}


# ---- sentence-level localisation
def test_localize_maps_claims_to_most_similar_sentence_and_counts_unlocalized():
    c = case(bad=(1,))
    p = pred(('Beta is blue', 'CONTRADICTED', []), ('Completely unrelated words here', 'UNSUPPORTED', []),
             ('Alpha is red', 'SUPPORTED', []))
    links = v26.localize(c, p, threshold=60)
    assert [(l['claim'], l['sentence']) for l in links] == [(0, 1), (1, None)]  # S claims are ignored
    assert v26.localize(c, p, threshold=0)[1]['sentence'] is not None  # threshold is a parameter


def test_localize_ties_go_to_the_earliest_sentence():
    c = case(answer='Same words here. Same words here.', bad=(0,), passages=('x',))
    assert v26.localize(c, pred(('same words here', 'UNSUPPORTED', [])), 60)[0]['sentence'] == 0


def test_sentence_vector_precision_recall_and_failures():
    c = case(bad=(1,))
    hit = pred(('Beta is blue', 'CONTRADICTED', []))
    miss = pred(('Alpha is red', 'UNSUPPORTED', []), ('Nothing matches this claim', 'UNSUPPORTED', []))
    assert list(v26.sentence_vector(c, hit, 60, 'token_set_ratio')) == [1, 0, 0, 1, 0, 1]
    assert list(v26.sentence_vector(c, miss, 60, 'token_set_ratio')) == [0, 1, 1, 1, 1, 0]
    assert list(v26.sentence_vector(c, {'id': 'c', 'error': 'x'}, 60, 'token_set_ratio')) == [0, 0, 1, 0, 0, 0]
    block = v26.sentence_block([c], {'c': miss}, 60, 'token_set_ratio', replicates=200)
    assert block['unlocalized_claims'] == 1 and block['localization_rate'] == 0.5
    sweep = v26.threshold_sweep([c], {'c': hit}, [0, 100])
    assert [r['threshold'] for r in sweep] == [0, 100] and sweep[0]['localization_rate'] == 1.0


# ---- citation validity
def test_citation_validity_classes():
    c = case()
    good = cit(0, 'Beta is blue')
    wrong_index = {**cit(1, 'Gamma is green'), 'index': 0}  # quote lives in passage 1
    missing = {'index': 0, 'quote': 'not in any passage', 'start_char': 0, 'end_char': 18}
    bad_offsets = {**cit(0, 'Beta is blue'), 'start_char': 0}
    out_of_range = {'index': 9, 'quote': 'Beta is blue', 'start_char': 0, 'end_char': 12}
    p = pred(('y', 'SUPPORTED', [good, wrong_index, missing, bad_offsets, out_of_range]))
    assert list(v26.citation_counts(c, p)) == [1, 2, 2, 5]
    block = v26.citation_block([c], {'c': p})
    assert block['valid'] == 1 and block['wrong_passage_index'] == 2 and block['not_exact_substring'] == 2
    assert v26.citation_block([c], {})['valid_rate']['value'] is None


# ---- groups, cost
def test_groups_flag_small_n_and_report_recall_only_for_label_types():
    cases = [case('a', task='QA', label_type='Evident Conflict'),
             case('b', task='Summary', label_type='Subtle Baseless Info'), case('n', gold=False)]
    preds = {c.id: pred(('y', 'UNSUPPORTED', [])) for c in cases}
    groups = v26.group_blocks(cases, preds)
    assert groups['task']['QA']['note'] == 'for reference only (n < 20)'
    typed = groups['upstream_label_type_positives_only']
    assert set(typed['evident_only']['metrics']) == {'recall'} and set(typed['with_subtle']['metrics']) == {'recall'}
    assert typed['evident_only']['n_cases'] == 1 and typed['with_subtle']['n_cases'] == 1
    assert set(groups['context_length_words']) == {'0-399'}
    big = [case(f'g{i}', task='QA') for i in range(20)]
    assert v26.group_blocks(big, {c.id: pred() for c in big})['task']['QA']['note'] == ''


def test_cost_and_latency_from_meta():
    cases = [case('a'), case('b')]
    preds = {'a': pred(meta={'latency_ms': 100.0, 'input_tokens': 1000, 'output_tokens': 500,
                             'retries': 1, 'llm_calls': 2}),
             'b': {'id': 'b', 'error': 'x'}}
    block = v26.cost_block(cases, preds, price_in=1.0, price_out=2.0)
    assert block['failures'] == 1 and block['retries'] == 1
    assert block['cost_usd_total'] == pytest.approx(0.002) and block['cost_usd_per_case'] == pytest.approx(0.001)
    assert block['latency_ms']['max'] == 100.0


# ---- data file and runner
def test_new_dataset_loads_without_gold_claims_and_eval_run_cannot_read_it():
    cases = v26.load_cases(DATA)
    assert len(cases) == 210 and sum(c.gold_response for c in cases) == sum(
        any(s['hallucinated'] for s in c.gold_sentences) for c in cases)
    from eval.dataset import load
    with pytest.raises(Exception):  # eval.run's loader needs claim-level fields
        load(DATA)


def test_validate_rows_catches_inconsistent_gold():
    row = json.loads(DATA.read_text(encoding='utf-8').splitlines()[0])
    assert v26.validate_rows([row]) == []
    assert v26.validate_rows([row, row]) == [f"duplicate id {row['id']}"]
    broken = {**row, 'gold_response': not row['gold_response']}
    assert any('disagrees' in e for e in v26.validate_rows([broken]))
    broken = {**row, 'gold_sentences': row['gold_sentences'][1:]}
    assert any('tile' in e for e in v26.validate_rows([broken]))


def test_v25_rows_derive_the_same_gold_as_v26_rows_would():
    row = json.loads((ROOT / 'data' / 'eval_hard.v2.5.jsonl').read_text(encoding='utf-8').splitlines()[0])
    derived = v26.case_from_row(row)
    assert derived.gold_response == bool(row['source_labels']['labels'])
    assert ''.join(s['text'] for s in derived.gold_sentences) == row['generated_answer']


def test_run_v26_scores_baseline_on_the_new_data_without_a_model(tmp_path):
    out = tmp_path / 'run'
    done = subprocess.run([sys.executable, '-m', 'eval.run_v26', '--data', str(DATA), '--methods', 'baseline',
                           '--split', 'dev', '--out', str(out)], cwd=ROOT, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    summary = json.loads((out / 'summary.json').read_text(encoding='utf-8'))
    run = summary['methods']['baseline'][0]
    assert summary['n_cases'] == 30 and run['errors'] == 0
    rows = [json.loads(l) for l in (out / 'baseline_run0.jsonl').read_text(encoding='utf-8').splitlines()]
    cases = v26.load_cases(DATA, 'dev')
    again = v26.method_report(cases, {r['id']: r for r in rows}, v26.DEFAULT_SENT_THRESHOLD,
                              'token_set_ratio', run['cost_latency']['price_usd_per_mtok']['in'],
                              run['cost_latency']['price_usd_per_mtok']['out'])
    assert again['answer_level'] == run['answer_level']
    # rescoring from the saved JSONL reproduces the summary
    done = subprocess.run([sys.executable, '-m', 'eval.run_v26', '--data', str(DATA), '--rescore', str(out)],
                          cwd=ROOT, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert json.loads((out / 'summary.json').read_text(encoding='utf-8'))['methods']['baseline'][0][
        'answer_level'] == run['answer_level']


def test_committed_baseline_dev_result_matches_its_predictions():
    d = ROOT / 'results' / 'v2.6-dev' / 'baseline'
    rows = {json.loads(l)['id']: json.loads(l)
            for l in (d / 'baseline_run0.jsonl').read_text(encoding='utf-8').splitlines()}
    cases = v26.load_cases(DATA, 'dev')
    assert set(rows) == {c.id for c in cases}
    summary = json.loads((d / 'summary.json').read_text(encoding='utf-8'))
    f1 = summary['methods']['baseline'][0]['answer_level']['main']['metrics']['f1']['value']
    point = v26.answer_scores(v26.answer_matrix(cases, rows).sum(axis=0))[2]
    assert f1 == pytest.approx(point)
