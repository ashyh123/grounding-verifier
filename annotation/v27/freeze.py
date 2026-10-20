"""Write and verify the v2.7 freeze. No provider calls.

    uv run python -m annotation.v27.freeze
    uv run python -m annotation.v27.freeze --check
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from verifier import config

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'data' / 'annotation' / 'v2.7' / 'freeze.json'
RULES = ROOT / 'data' / 'annotation' / 'v2.7' / 'rules.json'

CODE = [
    'annotation/v27/fetch.py', 'annotation/v27/ragtruthpp.py', 'annotation/v27/aggrefact.py',
    'annotation/v27/freeze.py',
    'annotation/v26/sentences.py', 'eval/run.py', 'eval/v26.py', 'eval/v27.py', 'eval/run_v27.py',
    'tests/test_v27_ragtruthpp.py', 'tests/test_v27_aggrefact.py',
    'data/annotation/v2.7/sources.json', 'data/annotation/v2.7/selection.json',
    'data/annotation/v2.7/aggrefact-selection-test.json',
    'data/annotation/v2.7/aggrefact-selection-dev.json',
    'data/annotation/v2.7/stats.md', 'data/annotation/v2.7/s4-dev-report.md',
]
DATA = [
    'data/eval_ragtruthpp.v2.7.jsonl',
    'data/eval_aggrefact.v2.7.test.jsonl',
    'data/eval_aggrefact.v2.7.dev.jsonl',
    'data/sources/v2.7/raw/ragtruthpp-hallucination_spans.csv',
    'data/sources/v2.7/raw/ragtruthpp-messages.csv',
    'data/sources/v2.7/raw/aggrefact-data-test-00000-of-00001.parquet',
    'data/sources/v2.7/raw/aggrefact-data-dev-00000-of-00001.parquet',
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def info(path: Path) -> dict:
    return {'sha256': sha(path), 'bytes': path.stat().st_size} if path.is_file() else {
        'sha256': None, 'bytes': None, 'present': False}


def git(*args: str) -> str:
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def collect() -> dict:
    rules = json.loads(RULES.read_text(encoding='utf-8'))
    files = {rel: sha(ROOT / rel) for rel in CODE}
    verifier = {p.name: sha(p) for p in sorted((ROOT / 'verifier').glob('*.py'))}
    data = {rel: info(ROOT / rel) for rel in DATA}
    return {
        'design_version': '2.7',
        'frozen_at': datetime.now(timezone.utc).isoformat(),
        'source_commit': git('rev-parse', 'HEAD'),
        'base_commit': 'c8df7d0',
        'purpose': 'Two independent external checks: RAGTruth++ annotation-strictness sensitivity (track B) and LLM-AggreFact oracle verification (track A).',
        'rules': {'path': 'data/annotation/v2.7/rules.json', 'sha256': sha(RULES)},
        'conclusion_rules': rules['conclusion_rules'],
        'files': files,
        'verifier_files': verifier,
        'data': data,
        'model': {
            'provider': config.provider(),
            'model': config.model(),
            'prompt_version': config.optional_env('VERIFIER_PROMPT_VERSION') or 'v3',
            'base_url': config.openai_base_url(),
            'parameters': {'temperature': 0, 'extra_body': config.extra_body(),
                           'max_tokens': 4096, 'timeout_s': config.timeout_s(),
                           'max_retries': config.max_retries(), 'concurrency': 4},
            'prices_usd_per_mtok': {'in': config.float_env('PRICE_IN_PER_MTOK', 0.0),
                                    'out': config.float_env('PRICE_OUT_PER_MTOK', 0.0)},
        },
        'run_plan': {
            'track_a': {'data': 'data/eval_aggrefact.v2.7.test.jsonl', 'n_docs': 461,
                        'n_claims': 854, 'methods': ['baseline', 'minimal', 'optimized'],
                        'runs': 1, 'oracle': True, 'minimal_batch_size': 20,
                        'output': 'results/v2.7-test/aggrefact'},
            'track_b': {'data': 'data/eval_ragtruthpp.v2.7.jsonl', 'n_cases': 229,
                        'n_new': 200, 'n_reused': 29,
                        'methods': ['baseline', 'minimal', 'optimized'], 'runs': 1,
                        'oracle': False, 'sentence_threshold': 60,
                        'output': 'results/v2.7-test/ragtruthpp'},
            'order': ['aggrefact', 'ragtruthpp'],
            'test_runs_total': 6,
            'stop_conditions': [
                'any method failure rate > 5%',
                'any overlong or truncated output',
                'total cost > $16',
                'a prompt, verifier code, metric code or data change would be required',
            ],
            'on_stop': 'stop and report; do not rerun or substitute results',
            'no_retuning_after_test': True,
        },
        'budget': {'cap_usd': 16.0, 'dev_spent_usd': 1.7553,
                   'track_a_test_estimate_usd': 3.92, 'track_b_test_estimate_usd': 7.84,
                   'projected_total_usd': 13.52,
                   'note': 'two dev runs (unbatched $0.8554 + batched $0.8999) + projected tests remain below the cap; the S2 fallback to 80 claims per track A subset is applied'},
        'deviations': {
            'minimal_oracle_batching': {
                'approved': True,
                'claims_per_call': 20,
                'reason': 'a 61-claim TofuEval document produced a truncated 16k-character JSON at max_tokens=4096 in the unbatched S4 run',
                'scope': 'eval/run_v27.py only; prompt, model, verifier code and gold unchanged',
                'effect': 'minimal dev cost rose from $0.1812 to $0.2269; 0 failures after batching',
            },
            'v25_documentation_reseal': {
                'recorded_as_deviation': True,
                'commit': '8981478',
                'original_version_commit': '900e3ae',
                'log': 'data/annotation/v2.7/resign_log.json',
            },
        },
        's4': {
            'status': 'batched_rerun_complete_no_stop_condition',
            'dev_docs': 58, 'dev_claims': 196,
            'failures': {'baseline': 0, 'minimal': 0, 'optimized': 0},
            'macro_bacc': {'baseline': 0.5895, 'minimal': 0.7972, 'optimized': 0.8113},
            'paired_optimized_minus_minimal': {'value': 0.014, 'ci95': [-0.032, 0.053],
                                               'excludes_zero': False},
            'cost_usd': {'baseline': 0.0, 'minimal': 0.2269, 'optimized': 0.6730,
                         'total': 0.8999, 'first_unbatched_run': 0.8554,
                         'both_dev_runs': 1.7553},
        },
        'resign_policy': {
            'log': 'data/annotation/v2.7/resign_log.json',
            'allowed_resignations': 1,
            'used': 0,
            'scope': ['README.md', 'docs/DATASET.md', 'docs/EVALUATION.md'],
            'authorization': 'v2.7 section 10.1; S7 may re-seal these documentation hashes once',
        },
        'test_authorized': False,
        'test_authorization_note': 'S5 freeze is written; the test run requires explicit user approval at the S6 gate',
        'limitations': [
            'RAGTruth++ has no publisher-declared license; raw CSV and derived JSONL stay local and are not redistributed',
            'RAGTruth++ strict labels start from the publisher detector; no peer review',
            'track A excludes the RAGTruth subset and documents over 4000 words; whole-document sampling overshoots the nominal claim target',
            'LLM-AggreFact is a public benchmark; contamination cannot be ruled out',
            'sentence localisation is lexical and approximate; citation sufficiency is not assessed',
            'the protocol changed after v2.6; the verifier and prompt are unchanged, but v2.7 is a new evaluation',
        ],
        'note': 'All data hashes are local; raw and derived external data are git-ignored. The v2.5 documentation re-seal at 8981478 is recorded as a deviation and may be repeated once at S7.',
    }


def check() -> None:
    if not OUT.is_file():
        raise SystemExit('STOP: v2.7 freeze.json does not exist')
    f = json.loads(OUT.read_text(encoding='utf-8'))
    errors, data_checked, data_missing = [], 0, []
    for rel, digest in f['files'].items():
        path = ROOT / rel
        if not path.is_file():
            errors.append(f'missing file: {rel}')
        elif sha(path) != digest:
            errors.append(f'changed file: {rel}')
    for rel, digest in f['verifier_files'].items():
        path = ROOT / 'verifier' / rel
        if not path.is_file() or sha(path) != digest:
            errors.append(f'changed verifier file: {rel}')
    for rel, meta in f['data'].items():
        path = ROOT / rel
        if not path.is_file():
            data_missing.append(rel)
        elif sha(path) != meta.get('sha256'):
            errors.append(f'changed data file: {rel}')
        else:
            data_checked += 1
    rules_hash = sha(RULES)
    if rules_hash != f['rules']['sha256']:
        errors.append('rules.json changed')
    if errors:
        raise SystemExit('STOP: v2.7 freeze check failed:\n' + '\n'.join(errors))
    print(json.dumps({'files': len(f['files']), 'verifier_files': len(f['verifier_files']),
                      'data_checked': data_checked, 'data_missing': data_missing,
                      'errors': 0}, ensure_ascii=False))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--check', action='store_true')
    args = ap.parse_args()
    if args.check:
        check()
        return
    if OUT.exists():
        raise SystemExit('STOP: v2.7 freeze already exists')
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(collect(), indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'wrote {OUT}')


if __name__ == '__main__':
    main()
