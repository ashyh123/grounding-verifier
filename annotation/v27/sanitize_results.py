"""Strip restricted LLM-AggreFact text from committed track A predictions.

    uv run python -m annotation.v27.sanitize_results --check
    uv run python -m annotation.v27.sanitize_results --write

Only IDs, verdicts and citation positions are kept. Claim text, reasoning, citation quotes and
meta warnings are removed; the numeric meta and cost fields remain. The local raw data and the
derived full predictions stay outside the repository.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN = {'claim_text', 'reasoning', 'quote', 'warnings'}


def files() -> list[Path]:
    return sorted({p for p in ROOT.glob('results/**/*aggrefact*/*.jsonl') if p.is_file()})


def sanitize(row: dict) -> dict:
    if 'error' in row:
        return {'id': row['id'], 'error': row['error']}
    claims = []
    for claim in row.get('claims') or []:
        citations = []
        for citation in claim.get('citations') or []:
            citations.append({k: citation[k] for k in ('index', 'start_char', 'end_char')
                              if k in citation})
        claims.append({'verdict': claim.get('verdict'), 'citations': citations})
    meta = {k: v for k, v in (row.get('meta') or {}).items() if k != 'warnings'}
    return {'id': row['id'], 'claims': claims, 'meta': meta}


def violations(row: dict) -> list[str]:
    out = []
    if 'claim_text' in row or 'reasoning' in row or 'warnings' in row:
        out.append('top-level text field')
    if 'warnings' in (row.get('meta') or {}):
        out.append('meta.warnings')
    for claim in row.get('claims') or []:
        if 'claim_text' in claim or 'reasoning' in claim:
            out.append('claim text/reasoning')
        for citation in claim.get('citations') or []:
            if 'quote' in citation:
                out.append('citation quote')
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--write', action='store_true')
    args = ap.parse_args()
    paths = files()
    if not paths:
        raise SystemExit('STOP: no track A prediction files found')
    bad = 0
    for path in paths:
        rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
        problems = [v for row in rows for v in violations(row)]
        if args.check:
            if problems:
                bad += len(problems)
                print(f'{path}: {len(problems)} restricted fields')
            continue
        if args.write:
            cleaned = [sanitize(row) for row in rows]
            path.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in cleaned),
                            encoding='utf-8')
            print(f'{path}: sanitized {len(cleaned)} rows')
    if args.check:
        if bad:
            raise SystemExit(f'STOP: {bad} restricted fields remain')
        print(f'clean: {len(paths)} track A prediction files')


if __name__ == '__main__':
    main()
