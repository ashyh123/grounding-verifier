"""Freeze v2.4 annotation, data, prompts, preregistered scoring and source snapshots.

No model calls. Historical data/code stay immutable; required documentation updates are
identified explicitly. --check verifies every pinned file, including local raw snapshots.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from annotation import sources as S
from annotation.freeze import check, resolve
from annotation.merge import digest
from annotation.map_labels import read_jsonl
from .complete import OUT
from .merge import assemble

DOCUMENTATION_UPDATES = {'docs/DATASET.md', 'docs/EVALUATION.md'}


def create(root: Path, dataset: Path) -> dict:
    cases, replay = assemble(root)
    audit = json.loads((root/'audit.json').read_text())
    replay['dataset_sha256'] = digest(dataset)
    if replay != audit or read_jsonl(dataset) != cases:
        raise ValueError('freeze requires a replay-verified dataset/audit')
    old_path = S.ANNOTATION_DIR/'freeze.json'
    old = json.loads(old_path.read_text())
    for name, sha in old['files'].items():
        # Only these explicitly requested documentation additions supersede old text.
        if name not in DOCUMENTATION_UPDATES and digest(resolve(name)) != sha:
            raise ValueError(f'v2.3 frozen data/code changed: {name}')
        if name in DOCUMENTATION_UPDATES:
            blob = subprocess.check_output(['git','show',f'c78d411:{name}'],cwd=S.ROOT)
            if hashlib.sha256(blob).hexdigest() != sha:
                raise ValueError('historical documentation differs from its c78d411 freeze')
    manifest = json.loads((S.SOURCES_V2/'manifest.json').read_text())
    for name in ('source_info.jsonl','response.jsonl'):
        if digest(S.RAW/name) != manifest['files'][name]['sha256']:
            raise ValueError('raw upstream snapshot differs from registered hash')
    files = {**old['files'], **audit['input_files']}
    paths = [dataset, root/'audit.json', root/'final_report.md', old_path]
    paths += [p for directory in ('annotation','eval','verifier','tests')
              for p in (S.ROOT/directory).rglob('*.py') if '__pycache__' not in p.parts]
    paths += [S.ROOT/n for n in ('README.md','docs/DATASET.md','docs/EVALUATION.md','pyproject.toml','uv.lock','Makefile')]
    for path in paths:
        files[S.rel(path.resolve())] = digest(path)
    for name, sha in files.items():
        if digest(resolve(name)) != sha:
            raise ValueError(f'changed freeze input: {name}')
    models, hashes = {}, set()

    def collect(value):
        if isinstance(value, list):
            for item in value: collect(item)
        elif isinstance(value, dict):
            if 'prompt_sha256' in value:
                hashes.add(value['prompt_sha256'])
                model = value.get('model', value.get('annotation_model'))
                parameters = value.get('parameters', value.get('annotation_parameters'))
                if model and parameters:
                    if model != 'mimo-v2.6-pro':
                        raise ValueError('v2.4 authorization is limited to mimo-v2.6-pro')
                    item = {'model':model,'parameters':parameters}
                    models[json.dumps(item,sort_keys=True)] = item
            for item in value.values(): collect(item)

    collect(cases)
    # Includes successful initial calls, reruns, decompositions and archived failed attempts.
    for name in files:
        path = resolve(name)
        # Annotation requests/provenance use JSONL journals. Other artifacts include
        # human stdout with historical .json names: hash them, do not parse as journals.
        if (path.is_relative_to(root) or path.is_relative_to(S.ANNOTATION_DIR)) and path.suffix == '.jsonl':
            collect(read_jsonl(path))
    return {'design_version':'2.4', 'frozen_at':datetime.now(timezone.utc).isoformat(),
            'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=S.ROOT,text=True).strip(),
            'dataset':S.rel(dataset.resolve()), 'dataset_sha256':digest(dataset),
            'retained_cases':len(cases), 'retained_claims':audit['retained_claims'],
            'historical_freeze_commit':'c78d411', 'historical_data_code_unchanged':True,
            'documentation_updates':sorted(DOCUMENTATION_UPDATES),
            'label_source':'ragtruth_human', 'secondary_human_review':False,
            'annotation_models':[models[k] for k in sorted(models)],
            'request_prompt_sha256':sorted(hashes), 'files':dict(sorted(files.items())),
            'preregistered_metrics':{'entry':'eval/v24.py','positive_labels':['CONTRADICTED','UNSUPPORTED'],
                'primary':['precision','recall','f1'],'secondary':'S/C/U macro-F1',
                'bootstrap':{'unit':'case','replicates':10000,'seed':20261020,'confidence':.95},
                'reports':['all','natural','conflict_supplement']},
            'hard_test_verifier_run':False,
            'note':'source_commit precedes the freeze commit; file hashes pin exact working sources. '
                   'Full upstream snapshots are pinned locally and are not committed. '
                   'Historical docs remain available at c78d411; v2.4 additions are explicit. '
                   'Hard-test measurement awaits separate user instructions.'}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root',type=Path,default=OUT)
    ap.add_argument('--data',type=Path,default=S.ROOT/'data/eval_hard.v2.4.jsonl')
    ap.add_argument('--check',action='store_true')
    args = ap.parse_args()
    path = args.root/'freeze.json'
    if args.check:
        changed = check(path)
        if changed: raise SystemExit('STOP: frozen files changed: '+', '.join(changed))
        print('all v2.4 frozen hashes verified'); return
    if path.exists():
        raise SystemExit('STOP: freeze already exists; no overwrite')
    result = create(args.root,args.data)
    with path.open('x') as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2); stream.write('\n')
    print(f"frozen {result['retained_cases']} cases, {result['retained_claims']} claims; {len(result['files'])} files")


if __name__ == '__main__':
    main()
