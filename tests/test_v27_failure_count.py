"""Claim-count mismatches are failures, and the excluding-failures report drops them."""
from eval import v27


def _row(cid, labels):
    return {'id': cid, 'subset': 'X', 'labels': labels, 'claims': [str(i) for i in range(len(labels))]}


def _pred(claims, verdict='SUPPORTED'):
    return {'id': '', 'claims': [{'claim_text': str(i), 'verdict': verdict} for i in range(claims)]}


def test_claim_count_mismatch_is_a_failure():
    row = _row('b', [1, 0])
    assert v27.is_failure(row, _pred(1)) is True
    assert v27.is_failure(row, _pred(2)) is False
    assert v27.is_failure(row, {'id': 'b', 'error': 'boom'}) is True
    assert v27.is_failure(row, None) is True


def test_main_counts_mismatch_wrong_and_excluding_drops_it():
    rows = [_row('a', [1, 0]), _row('b', [1, 0])]
    preds = {'a': _pred(2), 'b': _pred(1)}
    preds['a']['id'], preds['b']['id'] = 'a', 'b'
    report = v27.track_a_report(rows, {'minimal': preds}, replicates=20)
    main = report['methods']['main']['minimal']
    drop = report['methods']['excluding_failures']['minimal']
    assert main['failures'] == 1 and main['docs'] == 2 and main['claims'] == 4
    assert drop['failures'] == 1 and drop['docs'] == 1 and drop['claims'] == 2
    # doc b is one positive missed and one negative false-alarmed; doc a is perfect
    assert main['macro_balanced_accuracy']['value'] == 0.25
    assert drop['macro_balanced_accuracy']['value'] == 0.5
