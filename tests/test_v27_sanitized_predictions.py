"""Committed track A predictions must contain no LLM-AggreFact claim or quote text."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FILES = sorted(p for p in ROOT.glob('results/**/*aggrefact*/*.jsonl') if p.is_file())


def test_committed_track_a_predictions_are_sanitized():
    if not FILES:
        pytest.skip('no committed track A prediction files')
    for path in FILES:
        for line in path.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            assert 'warnings' not in (row.get('meta') or {}), path
            for claim in row.get('claims') or []:
                assert 'claim_text' not in claim and 'reasoning' not in claim, path
                for citation in claim.get('citations') or []:
                    assert 'quote' not in citation, path
                    assert set(citation) <= {'index', 'start_char', 'end_char'}, path


def test_sanitizer_check_passes():
    if not FILES:
        pytest.skip('no committed track A prediction files')
    result = subprocess.run([sys.executable, '-m', 'annotation.v27.sanitize_results', '--check'],
                            cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
