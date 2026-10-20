"""Freeze v2.5 data, audit, preregistered metrics, prompts, models and source snapshots.

    uv run python -m annotation.v25.freeze
    uv run python -m annotation.v25.freeze --check

No model calls. The freeze pins every file used to build and score the dataset; `--check`
recomputes those hashes offline.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from annotation import sources as S
from annotation.freeze import resolve
from annotation.map_labels import read_jsonl
from annotation.merge import digest

OUT = S.ANNOTATION_DIR / 'v2.5'
DATASET = S.ROOT / 'data' / 'eval_hard.v2.5.jsonl'
AUDIT = OUT / 'audit.json'
REPORT = OUT / 'final_report.md'


def code_paths() -> list[Path]:
    paths = [path for directory in ('annotation', 'eval', 'verifier', 'tests')
             for path in (S.ROOT / directory).rglob('*.py') if '__pycache__' not in path.parts]
    paths += [S.ROOT / name for name in (
        'README.md', 'docs/DATASET.md', 'docs/EVALUATION.md', 'annotation/README.md',
        'pyproject.toml', 'uv.lock', 'Makefile')]
    return sorted(set(paths))


def collect(cases: list[dict], doubt_rows: list[dict], journals: list[list[dict]]) -> tuple[list[dict], list[str]]:
    models, prompts = {}, set()

    def add(role: str, provenance: dict) -> None:
        model = provenance.get('model') or provenance.get('annotation_model')
        response = provenance.get('response_model')
        parameters = provenance.get('parameters') or provenance.get('annotation_parameters')
        if model and parameters:
            if 'deepseek' in model.lower():
                raise ValueError(f'annotation role {role} used a DeepSeek model')
            key = json.dumps({'role': role, 'model': model, 'response_model': response,
                              'parameters': parameters}, sort_keys=True)
            models[key] = json.loads(key)
        if provenance.get('prompt_sha256'):
            prompts.add(provenance['prompt_sha256'])

    for case in cases:
        add('draft', case.get('provenance') or {})
        for claim in case['gold_claims']:
            add('evidence', claim.get('evidence_provenance') or {})
            add('recovery_split', claim.get('split_provenance') or {})
    for row in doubt_rows:
        add('doubt_classification', row.get('provenance') or {})
    for rows in journals:
        for row in rows:
            add('journal', row.get('provenance') or {})
    return [models[key] for key in sorted(models)], sorted(prompts)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, default=OUT)
    ap.add_argument('--data', type=Path, default=DATASET)
    ap.add_argument('--check', action='store_true')
    args = ap.parse_args()
    freeze_path = args.root / 'freeze.json'
    if args.check:
        if not freeze_path.exists():
            raise SystemExit('STOP: v2.5 freeze.json does not exist')
        freeze = json.loads(freeze_path.read_text(encoding='utf-8'))
        changed = [name for name, sha in freeze['files'].items()
                   if not resolve(name).is_file() or digest(resolve(name)) != sha]
        if changed:
            raise SystemExit('STOP: frozen files changed: ' + ', '.join(changed))
        if digest(args.data) != freeze['dataset_sha256']:
            raise SystemExit('STOP: dataset hash differs from freeze')
        manifest = json.loads((S.SOURCES_V2 / 'manifest.json').read_text(encoding='utf-8'))
        if digest(S.SOURCES_V2 / 'manifest.json') != freeze['source_snapshot']['manifest_sha256']:
            raise SystemExit('STOP: source manifest changed')
        for name, sha in freeze['source_snapshot']['raw_sha256'].items():
            path = S.RAW / name
            if path.exists() and digest(path) != sha:
                raise SystemExit(f'STOP: raw snapshot changed: {name}')
        print(json.dumps({'cases': freeze['retained_cases'],
                          'claims': freeze['retained_claims'],
                          'files': len(freeze['files']), 'errors': 0}, ensure_ascii=False))
        return
    if freeze_path.exists():
        raise SystemExit('STOP: v2.5 freeze already exists; archive before rerunning')
    cases = read_jsonl(args.data)
    audit = json.loads(args.root.joinpath('audit.json').read_text(encoding='utf-8'))
    if audit['retained_cases'] != len(cases) or audit['retained_claims'] != sum(
            len(case['gold_claims']) for case in cases):
        raise ValueError('dataset does not match the audited merge')
    doubt_rows = read_jsonl(args.root / 'doubt_classes.jsonl') if (
        args.root / 'doubt_classes.jsonl').exists() else []
    journals = []
    for path in sorted(args.root.rglob('*.jsonl')):
        if path.name not in ('doubt_classes.jsonl',):
            journals.append(read_jsonl(path))
    models, prompts = collect(cases, doubt_rows, journals)
    files = {S.rel(path.resolve()): digest(path) for path in
             [args.data, args.root / 'audit.json', args.root / 'final_report.md',
              S.ANNOTATION_DIR / 'freeze.json', S.ANNOTATION_DIR / 'v2.4' / 'freeze.json',
              S.ANNOTATION_DIR / 'v2.4' / 'audit.json',
              S.ROOT / 'data' / 'eval_hard.jsonl', S.ROOT / 'data' / 'eval_hard.v2.4.jsonl',
              S.ROOT / 'data' / 'eval.jsonl', S.SOURCES_V2 / 'manifest.json']}
    files.update({S.rel(path.resolve()): digest(path) for path in
                  sorted(p for p in args.root.rglob('*') if p.is_file()
                         and p.name not in ('freeze.json',))})
    files.update({S.rel(path.resolve()): digest(path) for path in code_paths()})
    manifest = json.loads((S.SOURCES_V2 / 'manifest.json').read_text(encoding='utf-8'))
    result = {
        'design_version': '2.5', 'frozen_at': datetime.now(timezone.utc).isoformat(),
        'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=S.ROOT,
                                                  text=True).strip(),
        'base_freeze_commit': 'cbccac9', 'historical_freeze_commit': 'c78d411',
        'dataset': S.rel(args.data.resolve()), 'dataset_sha256': digest(args.data),
        'retained_cases': len(cases), 'retained_claims': sum(len(case['gold_claims']) for case in cases),
        'label_source': 'ragtruth_human', 'secondary_human_review': False,
        'annotation_models': models, 'request_prompt_sha256': prompts,
        'scoring_code': {name: digest(S.ROOT / name) for name in
                         ('eval/v25.py', 'eval/v24.py', 'eval/scoring.py', 'eval/dataset.py')},
        'preregistered_metrics': {
            'entry': 'eval/v25.py', 'subsets': ['all', 'natural', 'conflict_supplement',
                                                'subtle_supplement'],
            'primary': 'all gold claims; v2.4 metric definitions',
            'sensitivity': 'remove claims whose doubt_category is suspected_wrong_label or c_vs_u_boundary',
            'groups': ['by_origin (subtle > evident > clean)', 'by_generator_model'],
            'bootstrap': {'unit': 'case', 'replicates': 10000, 'seed': 20261020, 'confidence': .95}},
        'source_snapshot': {
            'manifest_sha256': digest(S.SOURCES_V2 / 'manifest.json'),
            'raw_sha256': {name: manifest['files'][name]['sha256']
                           for name in ('source_info.jsonl', 'response.jsonl')}},
        'v24_freeze_adaptation': {
            'authorized': True,
            'reason': 'v2.5 explicitly requires updating annotation/README.md with the current status',
            'files': ['annotation/README.md', 'annotation/v24/freeze.py'],
            'historical_check': 'the v2.4 freeze remains valid at cbccac9; the working-tree '
                                'recreation pins the authorized README text'},
        'hard_test_verifier_run': False,
        'files': dict(sorted(files.items())),
        'note': 'No evaluated verifier ran on the hard test. All labels are RAGTruth human spans; '
                'exact evidence presence does not prove semantic sufficiency. '
                'Hard-test measurement requires separate user instructions.'}
    with freeze_path.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(f"frozen {result['retained_cases']} cases / {result['retained_claims']} claims; "
          f"dataset sha256={result['dataset_sha256']}; {len(result['files'])} files")


if __name__ == '__main__':
    main()
