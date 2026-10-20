"""Run the v2.7 tracks. Track B is end-to-end on RAGTruth++; track A is oracle on AggreFact.

    uv run python -m eval.run_v27 --track ragtruthpp --methods baseline minimal optimized \
        --out results/v2.7-test/ragtruthpp
    uv run python -m eval.run_v27 --track aggrefact --methods baseline minimal optimized \
        --out results/v2.7-test/aggrefact

Track B reuses the v2.6 test predictions for response ids present in both sets. A reused row keeps
its claims but not its v2.6 token counts, so the v2.7 cost column is the new spend only.
No verifier or prompt is changed.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from verifier.llm import UpstreamError
from verifier.schemas import VerifyRequest

from . import v27
from .run import build

ROOT = Path(__file__).resolve().parents[1]
V26_RESULTS = ROOT / 'results' / 'v2.6-test'


async def run_one(verifier, row: dict, sem: asyncio.Semaphore) -> dict:
    async with sem:
        try:
            result = await verifier.verify(VerifyRequest(context_passages=row['context_passages'],
                                                         generated_answer=row['generated_answer']))
            return {'id': row['id']} | result.model_dump(mode='json')
        except UpstreamError as e:
            return {'id': row['id'], 'error': str(e)}


async def run_oracle(verifier, row: dict, sem: asyncio.Semaphore) -> dict:
    async with sem:
        try:
            result = await verifier.verify_claims(row['context_passages'], row['claims'])
            return {'id': row['id']} | result.model_dump(mode='json')
        except UpstreamError as e:
            return {'id': row['id'], 'error': str(e)}


def load_reuse(method: str) -> dict[str, dict]:
    path = V26_RESULTS / f'{method}_run0.jsonl'
    return {r['id']: r for r in (json.loads(line) for line in
                                 path.read_text(encoding='utf-8').splitlines() if line.strip())}


def reuse(row: dict, method: str, old_predictions: dict[str, dict]) -> dict | None:
    source_id = row['selection'].get('reuse_v26_prediction')
    if not source_id:
        return None
    if source_id not in old_predictions:
        raise SystemExit(f'STOP: reusable v2.6 prediction {source_id} missing from {method}')
    old = old_predictions[source_id]
    if 'error' in old:
        return {'id': row['id'], 'error': old['error'], 'reused_from_v26': True,
                'v26_id': source_id, 'meta': {'reused_from_v26': True, 'v26_id': source_id}}
    meta = old.get('meta') or {}
    return {'id': row['id'], 'claims': old['claims'], 'reused_from_v26': True, 'v26_id': source_id,
            'meta': {'method': method, 'model': meta.get('model'),
                     'prompt_version': meta.get('prompt_version'),
                     'reused_from_v26': True, 'v26_id': source_id, 'v26_latency_ms': meta.get('latency_ms')}}


async def track_ragtruthpp(rows: list[dict], methods: list[str], out: Path, concurrency: int,
                           prompt_version: str) -> dict:
    sel = v27.selected(rows)
    if len(sel) != 229:
        raise SystemExit(f'STOP: expected 229 selected answers, got {len(sel)}')
    out.mkdir(parents=True, exist_ok=True)
    summary = {'design_version': '2.7', 'track': 'ragtruthpp', 'n_cases': len(sel),
               'n_reused': sum(bool(r['selection']['reuse_v26_prediction']) for r in sel),
               'n_new': sum(not r['selection']['reuse_v26_prediction'] for r in sel),
               'prompt_version': prompt_version, 'methods': {}}
    for method in methods:
        verifier = build(method, prompt_version)
        sem = asyncio.Semaphore(concurrency)
        old_predictions = load_reuse(method)
        reused = {row['id']: reuse(row, method, old_predictions) for row in sel
                  if row['selection'].get('reuse_v26_prediction')}
        new_rows = [row for row in sel if not row['selection'].get('reuse_v26_prediction')]
        fresh = await asyncio.gather(*(run_one(verifier, row, sem) for row in new_rows))
        fresh_by_id = {r['id']: r for r in fresh}
        rows_out = [reused.get(row['id']) or fresh_by_id[row['id']] for row in sel]
        path = out / f'{method}_run0.jsonl'
        with path.open('w', encoding='utf-8') as stream:
            for row in rows_out:
                stream.write(json.dumps(row, ensure_ascii=False) + '\n')
        failures = sum('error' in r for r in rows_out)
        summary['methods'][method] = {'rows': len(rows_out), 'failures': failures,
                                      'failure_rate': failures / len(rows_out),
                                      'reused': sum(bool(r.get('reused_from_v26')) for r in rows_out),
                                      'new': sum(not r.get('reused_from_v26') for r in rows_out)}
        print(f'{method}: {len(rows_out)} rows, {failures} failures, '
              f'{summary["methods"][method]["reused"]} reused')
        if failures / len(rows_out) > 0.05:
            raise SystemExit(f'STOP: {method} failure rate {failures / len(rows_out):.2%} > 5%')
    (out / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False) + '\n',
                                      encoding='utf-8')
    return summary


async def track_aggrefact(rows: list[dict], methods: list[str], out: Path, concurrency: int,
                          prompt_version: str) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    summary = {'design_version': '2.7', 'track': 'aggrefact', 'n_docs': len(rows),
               'n_claims': sum(len(r['claims']) for r in rows),
               'prompt_version': prompt_version, 'methods': {}}
    for method in methods:
        verifier = build(method, prompt_version)
        sem = asyncio.Semaphore(concurrency)
        rows_out = await asyncio.gather(*(run_oracle(verifier, row, sem) for row in rows))
        path = out / f'{method}_run0.jsonl'
        with path.open('w', encoding='utf-8') as stream:
            for row in rows_out:
                stream.write(json.dumps(row, ensure_ascii=False) + '\n')
        failures = sum('error' in r for r in rows_out)
        summary['methods'][method] = {'docs': len(rows_out), 'failures': failures,
                                      'failure_rate': failures / len(rows_out)}
        print(f'{method}: {len(rows_out)} docs, {failures} failures')
        if failures / len(rows_out) > 0.05:
            raise SystemExit(f'STOP: {method} failure rate {failures / len(rows_out):.2%} > 5%')
    (out / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False) + '\n',
                                      encoding='utf-8')
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--track', choices=['ragtruthpp', 'aggrefact'], required=True)
    ap.add_argument('--data', type=Path, default=None)
    ap.add_argument('--split', choices=['dev', 'test'], default='test')
    ap.add_argument('--methods', nargs='+', default=['baseline', 'minimal', 'optimized'])
    ap.add_argument('--concurrency', type=int, default=4)
    ap.add_argument('--prompt-version', default='v3')
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    if args.track == 'aggrefact':
        data = args.data or ROOT / 'data' / f'eval_aggrefact.v2.7.{args.split}.jsonl'
        rows = v27.load_aggrefact(data)
        asyncio.run(track_aggrefact(rows, args.methods, args.out, args.concurrency,
                                    args.prompt_version))
        return
    data = args.data or ROOT / 'data' / 'eval_ragtruthpp.v2.7.jsonl'
    rows = v27.load_rows(data)
    asyncio.run(track_ragtruthpp(rows, args.methods, args.out, args.concurrency,
                                 args.prompt_version))


if __name__ == '__main__':
    main()
