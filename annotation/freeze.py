"""Freeze the v2.3 dataset, source snapshots, code, prompts and nonsecret model parameters.

    python -m annotation.freeze
    python -m annotation.freeze --check

Failure modes: dataset/audit mismatch, changed merge inputs, missing snapshots, snapshot digest
mismatch, changed frozen file, existing freeze overwrite. Source files stay locally hash-pinned;
full upstream snapshots and credentials must never be staged in Git.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from eval.dataset import load
from . import sources as S
from .merge import digest
from .map_labels import read_jsonl


def resolve(name: str) -> Path:
    p = Path(name)
    return p if p.is_absolute() else S.ROOT / p


def create(dataset: Path, audit_path: Path) -> dict:
    cases = load(dataset)
    audit = json.loads(audit_path.read_text())
    if (digest(dataset) != audit['dataset_sha256'] or len(cases) != audit['retained_cases']
            or sum(len(c.gold_claims) for c in cases) != audit['retained_claims']):
        raise ValueError('dataset does not match the audited merge')
    files = {S.rel(dataset.resolve()): digest(dataset),
             S.rel(audit_path.resolve()): digest(audit_path), **audit['input_files']}
    for name, expected in files.items():
        if digest(resolve(name)) != expected:
            raise ValueError(f'merge input changed: {name}')
    manifest_path = S.SOURCES_V2 / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    files[S.rel(manifest_path)] = digest(manifest_path)
    for name in ('source_info.jsonl', 'response.jsonl'):
        path = S.RAW / name
        observed = digest(path)
        if observed != manifest['files'][name]['sha256']:
            raise ValueError(f'upstream snapshot changed: {name}')
        files[S.rel(path)] = observed
    code = [*sorted((S.ROOT / 'eval').glob('*.py')), *sorted((S.ROOT / 'verifier').glob('*.py')),
            *(S.ROOT / 'annotation' / name for name in (
                '__init__.py', 'sources.py', 'select_cases.py', 'prompts.py', 'draft_claims.py',
                'map_labels.py', 'find_evidence.py', 'merge.py', 'freeze.py')),
            *(S.ROOT / name for name in ('docs/DATASET.md', 'docs/EVALUATION.md', 'annotation/README.md',
                                       'data/annotation/selection.json', 'pyproject.toml', 'uv.lock'))]
    for path in code:
        files[S.rel(path)] = digest(path)
    models, prompt_hashes = {}, set()
    raw_cases = read_jsonl(dataset)
    for case in raw_cases:
        provenance = case['provenance']
        item = {'role': 'draft', 'model': provenance['annotation_model'],
                'parameters': provenance['annotation_parameters']}
        models[json.dumps(item, sort_keys=True)] = item
        prompt_hashes.add(provenance['prompt_sha256'])
        for claim in case['gold_claims']:
            ev = claim['evidence_provenance']
            if ev['calls']:
                item = {'role': 'evidence', 'model': ev['model'],
                        'response_model': ev['response_model'], 'parameters': ev['parameters']}
                models[json.dumps(item, sort_keys=True)] = item
                prompt_hashes.add(ev['prompt_sha256'])
    return {'design_version': '2.3', 'frozen_at': datetime.now(timezone.utc).isoformat(),
            'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=S.ROOT, text=True).strip(),
            'dataset': S.rel(dataset.resolve()), 'dataset_sha256': digest(dataset),
            'retained_cases': audit['retained_cases'], 'retained_claims': audit['retained_claims'],
            'label_source': 'ragtruth_human', 'secondary_human_review': False,
            'annotation_models': [models[k] for k in sorted(models)],
            'request_prompt_sha256': sorted(prompt_hashes), 'files': dict(sorted(files.items())),
            'hard_test_verifier_run': False,
            'note': 'source_commit is the commit before the freeze commit; files hash the exact working sources. '
                    'Raw upstream files are recorded by hash and are not committed. '
                    'Hard-test measurement requires separate user authorization.'}


def check(path: Path) -> list[str]:
    freeze = json.loads(path.read_text())
    return [name for name, expected in freeze['files'].items()
            if not resolve(name).is_file() or digest(resolve(name)) != expected]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--data', type=Path, default=S.ROOT / 'data/eval_hard.jsonl')
    ap.add_argument('--audit', type=Path, default=S.ANNOTATION_DIR / 'audit.json')
    ap.add_argument('--out', type=Path, default=S.ANNOTATION_DIR / 'freeze.json')
    ap.add_argument('--check', action='store_true')
    args = ap.parse_args()
    if args.check:
        changed = check(args.out)
        if changed:
            raise SystemExit('STOP: frozen files changed: ' + ', '.join(changed))
        print('all frozen hashes verified')
        return
    if args.out.exists():
        raise SystemExit('STOP: archive the old freeze before making a new freeze')
    record = create(args.data, args.audit)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x', encoding='utf-8') as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2); stream.write('\n')
    print(f"frozen {record['retained_cases']} cases / {record['retained_claims']} claims; "
          f"dataset sha256={record['dataset_sha256']}; {len(record['files'])} files")


if __name__ == '__main__':
    main()
