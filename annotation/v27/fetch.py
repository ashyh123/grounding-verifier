"""Download the v2.7 external evaluation sources and record their hashes.

    uv run python -m annotation.v27.fetch --dataset ragtruthpp
    uv run python -m annotation.v27.fetch --dataset aggrefact   # needs an accepted gated dataset

Raw files stay in data/sources/v2.7/raw/ (git-ignored). Only data/annotation/v2.7/sources.json is
committed. No model calls. A gated dataset without a token is a hard stop, not a reason to relax.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / 'data' / 'sources' / 'v2.7' / 'raw'
OUT = ROOT / 'data' / 'annotation' / 'v2.7' / 'sources.json'

DATASETS = {
    'aggrefact': {
        'repo': 'lytang/LLM-AggreFact',
        'revision': '981dfd0bd8e58e7238a9ab92b2e6ea44bce918e4',
        'license': 'CC-BY-ND-4.0',
        'gated': 'auto',
        'files': ['README.md', 'data/dev-00000-of-00001.parquet',
                  'data/test-00000-of-00001.parquet'],
        'gated_prompt': 'accept the dataset terms at https://huggingface.co/datasets/lytang/LLM-AggreFact',
    },
    'ragtruthpp': {
        'repo': 'blue-guardrails/ragtruth-plus-plus',
        'revision': 'afaec19e64122b4a58718dc31bcd555c97460233',
        'license': 'not stated by the publisher',
        'gated': False,
        'files': ['README.md', 'hallucination_spans.csv', 'messages.csv'],
        'gated_prompt': None,
    },
}


def token() -> str | None:
    value = os.environ.get('HF_TOKEN') or os.environ.get('HUGGING_FACE_HUB_TOKEN')
    if value:
        return value.strip()
    path = Path.home() / '.cache' / 'huggingface' / 'token'
    return path.read_text(encoding='utf-8').strip() if path.is_file() else None


def target(name: str, filename: str) -> Path:
    return RAW / f'{name}-{filename.replace("/", "-")}'


def download(name: str, filename: str, tok: str | None) -> dict:
    spec = DATASETS[name]
    url = f"https://huggingface.co/datasets/{spec['repo']}/resolve/{spec['revision']}/{filename}"
    dst = target(name, filename)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.is_file():
        data = dst.read_bytes()
        return {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data), 'url': url,
                'cached': True}
    headers = {'Authorization': f'Bearer {tok}'} if tok else {}
    with httpx.stream('GET', url, headers=headers, follow_redirects=True, timeout=120) as resp:
        if resp.status_code in (401, 403):
            raise PermissionError(
                f'{name}: HTTP {resp.status_code}; {spec["gated_prompt"]}. '
                'Then run `uv run --with huggingface_hub huggingface-cli login` or set HF_TOKEN.')
        if resp.status_code != 200:
            raise RuntimeError(f'{name}: HTTP {resp.status_code} for {url}')
        tmp = dst.with_suffix(dst.suffix + '.part')
        digest = hashlib.sha256()
        size = 0
        with tmp.open('wb') as out:
            for chunk in resp.iter_bytes():
                out.write(chunk)
                digest.update(chunk)
                size += len(chunk)
        tmp.replace(dst)
    return {'sha256': digest.hexdigest(), 'bytes': size, 'url': url, 'cached': False}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dataset', choices=['aggrefact', 'ragtruthpp', 'all'], default='all')
    args = ap.parse_args()
    names = list(DATASETS) if args.dataset == 'all' else [args.dataset]
    manifest = json.loads(OUT.read_text(encoding='utf-8')) if OUT.exists() else {
        'version': '2.7', 'datasets': {}}
    manifest['fetched_at'] = datetime.now(timezone.utc).isoformat()
    for name in names:
        spec = DATASETS[name]
        entry = {k: spec[k] for k in ('repo', 'revision', 'license', 'gated')}
        entry['files'] = {}
        try:
            tok = token()
            for filename in spec['files']:
                entry['files'][filename] = download(name, filename, tok)
            entry['status'] = 'downloaded'
        except PermissionError as e:
            entry['status'] = 'blocked_gated'
            entry['error'] = str(e)
        except Exception as e:
            entry['status'] = 'failed'
            entry['error'] = f'{type(e).__name__}: {e}'
        manifest['datasets'][name] = entry
        print(f'{name}: {entry["status"]}')
        for filename, meta in entry['files'].items():
            print(f'  {filename}: {meta["sha256"]} ({meta["bytes"]} bytes)')
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    if any(v['status'] != 'downloaded' for v in manifest['datasets'].values()):
        raise SystemExit('STOP: one or more sources are not downloaded; see sources.json')


if __name__ == '__main__':
    main()
