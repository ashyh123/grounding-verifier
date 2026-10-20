"""The v2.7 freeze must pass its own offline check and pin the run plan."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FREEZE = ROOT / 'data' / 'annotation' / 'v2.7' / 'freeze.json'


def freeze() -> dict:
    return json.loads(FREEZE.read_text(encoding='utf-8'))


def test_v27_freeze_check_passes():
    if not FREEZE.exists():
        pytest.skip('v2.7 freeze not written yet')
    result = subprocess.run([sys.executable, '-m', 'annotation.v27.freeze', '--check'],
                            cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr


def test_v27_freeze_pins_the_plan_and_budget():
    if not FREEZE.exists():
        pytest.skip('v2.7 freeze not written yet')
    f = freeze()
    assert f['design_version'] == '2.7'
    assert f['model']['model'] == 'deepseek-v4-pro'
    assert f['model']['prompt_version'] == 'v3'
    assert f['run_plan']['track_a']['oracle'] is True
    assert f['run_plan']['track_a']['minimal_batch_size'] == 20
    assert f['run_plan']['track_a']['n_claims'] == 854
    assert f['run_plan']['track_b']['n_cases'] == 229
    assert f['run_plan']['track_b']['n_reused'] == 29
    assert f['budget']['cap_usd'] == 16.0
    assert f['budget']['projected_total_usd'] < 16.0
    assert f['test_authorized'] is False
    assert f['deviations']['minimal_oracle_batching']['claims_per_call'] == 20
    assert f['resign_policy']['used'] == 0 and f['resign_policy']['allowed_resignations'] == 1
