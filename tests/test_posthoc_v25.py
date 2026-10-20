"""Post-hoc v2.5 analyses: paired bootstrap and claim coverage (not preregistered)."""
import json
from pathlib import Path

import numpy as np

from eval.posthoc_v25 import analyse, coverage, paired_bootstrap
from eval.v24 import scores

ROOT = Path(__file__).resolve().parents[1]


def counts(rows):
    """rows: list of (gold, pred, n) with gold in S/C/U/EXTRA = 0..3, pred in S/C/U/MISSED = 0..3."""
    out = np.zeros((4, 4), dtype=np.int64)
    for g, p, n in rows:
        out[g, p] += n
    return out


def test_identical_methods_have_zero_difference_and_interval_containing_zero():
    cases = np.stack([counts([(1, 1, 1), (0, 0, 3)]), counts([(1, 0, 1), (0, 1, 1)]),
                      counts([(2, 2, 1), (0, 0, 2)]), counts([(0, 0, 4)])])
    r = paired_bootstrap(cases, cases.copy(), replicates=500, seed=1)
    for name in ('hallucination_f1', 'macro_f1'):
        assert r[name]['diff'] == 0 and r[name]['ci95'] == [0.0, 0.0]
        assert r[name]['excludes_zero'] is False


def test_point_estimate_uses_summed_counts_and_clear_winner_excludes_zero():
    good = np.stack([counts([(1, 1, 2), (0, 0, 2)])] * 30)   # every C found, no false alarms
    bad = np.stack([counts([(1, 3, 2), (0, 1, 2)])] * 30)    # every C missed, false alarms
    r = paired_bootstrap(good, bad, replicates=500, seed=2)
    assert abs(r['hallucination_f1']['a'] - scores(good.sum(axis=0))[2]) < 1e-12
    assert r['hallucination_f1']['diff'] > 0 and r['hallucination_f1']['excludes_zero']


def test_bootstrap_is_paired_and_reproducible():
    rng = np.random.default_rng(0)
    a = rng.integers(0, 3, size=(20, 4, 4))
    b = a.copy()
    b[:, 1, 1] += 1  # b is strictly better on every case: paired difference has no spread issue
    first = paired_bootstrap(a, b, replicates=300, seed=7)
    second = paired_bootstrap(a, b, replicates=300, seed=7)
    assert first == second
    third = paired_bootstrap(a, b, replicates=300, seed=8)
    assert third['hallucination_f1']['ci95'] != first['hallucination_f1']['ci95']


def test_coverage_by_verdict():
    c = np.stack([counts([(0, 0, 5), (0, 3, 3), (1, 1, 1), (2, 3, 1), (3, 1, 7)]),
                  counts([(0, 2, 2), (1, 3, 1)])])
    out = coverage(c)
    assert out['SUPPORTED'] == {'gold': 10, 'aligned': 7, 'missed': 3, 'coverage': 0.7}
    assert out['CONTRADICTED']['aligned'] == 1 and out['CONTRADICTED']['gold'] == 2
    assert out['UNSUPPORTED']['coverage'] == 0.0
    assert out['all']['gold'] == 13  # EXTRA predictions are not gold claims


def test_analyse_marks_everything_post_hoc():
    arr = np.stack([counts([(0, 0, 2), (1, 1, 1)])] * 5)
    rounds = {'baseline': [arr], 'minimal': [arr, arr], 'optimized': [arr, arr, arr]}
    report = analyse([object()] * 5, rounds, replicates=100, seed=3)
    assert report['preregistered'] is False
    assert report['paired_difference_minimal_minus_optimized']['preregistered'] is False
    assert report['claim_coverage']['preregistered'] is False
    assert len(report['claim_coverage']['per_method']['optimized']) == 3


def test_committed_posthoc_report_matches_reference_values():
    path = ROOT / 'results' / 'v2.5-test' / 'posthoc' / 'posthoc.json'
    report = json.loads(path.read_text(encoding='utf-8'))
    assert report['preregistered'] is False
    d = report['paired_difference_minimal_minus_optimized']['hallucination_f1']
    assert abs(d['diff'] - 0.021) < 0.001 and d['ci95'][0] < 0 < d['ci95'][1]
    r1 = report['claim_coverage']['per_method']
    assert r1['minimal'][0]['SUPPORTED']['missed'] == 109
    assert r1['optimized'][0]['SUPPORTED']['missed'] == 53
