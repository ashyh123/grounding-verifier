"""The v2.6 freeze must keep pinning the exact data, metrics and verifier it recorded."""
import hashlib
import json
from pathlib import Path

from eval import v26

ROOT = Path(__file__).resolve().parents[1]
FREEZE = ROOT / 'data' / 'annotation' / 'v2.6' / 'freeze.json'
V25_FREEZE = ROOT / 'data' / 'annotation' / 'v2.5' / 'freeze.json'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze() -> dict:
    return json.loads(FREEZE.read_text(encoding='utf-8'))


def test_v26_freeze_pins_dataset_and_sampling():
    f = freeze()
    path = ROOT / f['dataset']['path']
    assert sha(path) == f['dataset']['sha256']
    assert sha(ROOT / f['sampling']['rules']) == f['sampling']['rules_sha256']
    assert sha(ROOT / f['sampling']['selection']) == f['sampling']['selection_sha256']
    rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    assert len(rows) == f['dataset']['n_cases'] == 210
    assert len(v26.load_cases(path)) == 210
    for split, n in f['dataset']['splits'].items():
        subset = [r for r in rows if r['split'] == split]
        assert len(subset) == n
        assert sum(r['gold_response'] for r in subset) == f['dataset']['gold_positives'][split]
        assert len(v26.load_cases(path, split)) == n


def test_v26_freeze_verifier_is_still_the_v25_verifier():
    f = freeze()
    assert sha(V25_FREEZE) == f['verifier']['frozen_baseline_sha256']
    v25 = json.loads(V25_FREEZE.read_text(encoding='utf-8'))
    changed = {p for p, h in v25['files'].items() if sha(ROOT / p) != h}
    assert changed == set()
    resealed = set(f['verifier']['frozen_files_changed'])
    assert resealed == set(v25['documentation_updates']['files'])
    assert resealed == {'README.md', 'docs/DATASET.md', 'docs/EVALUATION.md'}
    assert f['post_freeze_documentation_reconciliation']['documentation_only'] is True
    assert f['post_freeze_documentation_reconciliation']['verifier_code_prompt_data_unchanged'] is True
    assert sha(ROOT / 'verifier/prompts.py') == f['verifier']['prompt_source_sha256']


def test_v26_freeze_pins_metric_code_and_threshold():
    f = freeze()
    for path, digest in f['metrics']['metric_files'].items():
        assert sha(ROOT / path) == digest, path
    assert f['metrics']['secondary']['sentence_localisation']['threshold'] == 60.0
    assert f['metrics']['primary'].startswith('response-level')
    assert f['metrics']['oracle'] is False and f['metrics']['preregistered'] is True


def test_v26_freeze_pins_dev_results():
    f = freeze()
    assert sha(ROOT / 'results/v2.6-dev/run1/summary.json') == f['dev_diagnostic']['summary_sha256']
    assert sha(ROOT / 'results/v2.6-dev/report/v26_report.json') == f['dev_diagnostic']['report_sha256']
    summary = json.loads((ROOT / 'results/v2.6-dev/run1/summary.json').read_text(encoding='utf-8'))
    assert set(summary['methods']) == {'baseline', 'minimal', 'optimized'}
    assert all(run[0]['failures'] == 0 for run in summary['methods'].values())
    assert f['run_plan']['n_cases'] == 180 and f['budget']['cap_usd'] == 12.0
