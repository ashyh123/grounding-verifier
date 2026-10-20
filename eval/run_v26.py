"""Run verifiers on the response-level (v2.6) dataset and score them with eval.v26.

    python -m eval.run_v26 --methods baseline --split dev --out results/v2.6-dev/baseline
    python -m eval.run_v26 --methods minimal optimized --split test --runs 1 --out results/v2.6-test

`eval/run.py` cannot read this file (its loader and metrics need `gold_claims`, and it is pinned by
the v2.4/v2.5 freezes), so this entry point reuses its `build` and reports through `eval.v26`.
It sends the verifier only the context passages and the answer, exactly like `eval.run` does.
Writes <out>/<method>_run<k>.jsonl (same row format as eval.run) and <out>/summary.json.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

from verifier import config, prompts
from verifier.llm import UpstreamError
from verifier.schemas import VerifyRequest

from . import v26
from .run import PRICE_IN, PRICE_OUT, build


async def run_one(verifier, case: v26.Case, sem: asyncio.Semaphore) -> dict:
    async with sem:
        try:
            r = await verifier.verify(VerifyRequest(context_passages=case.passages,
                                                    generated_answer=case.answer))
            return {'id': case.id} | r.model_dump(mode='json')
        except UpstreamError as e:
            return {'id': case.id, 'error': str(e)}


def score(cases: list[v26.Case], rows: list[dict]) -> dict:
    report = v26.method_report(cases, {r['id']: r for r in rows}, v26.DEFAULT_SENT_THRESHOLD,
                               'token_set_ratio', PRICE_IN, PRICE_OUT)
    report['errors'] = report['failures']
    return report


def rescore(result_dir: Path, data: Path) -> None:
    """Recompute summary.json from the JSONL on disk; no provider calls."""
    summary = json.loads((result_dir / 'summary.json').read_text(encoding='utf-8'))
    cases = v26.load_cases(data, summary['split'])
    for method, runs in summary['methods'].items():
        scored = []
        for k in range(len(runs)):
            rows = [json.loads(line) for line in
                    (result_dir / f'{method}_run{k}.jsonl').read_text(encoding='utf-8').splitlines()
                    if line.strip()]
            if {r['id'] for r in rows} != {c.id for c in cases}:
                raise SystemExit(f'{method} run {k} does not match the {summary["split"]} split')
            scored.append(score(cases, rows))
        summary['methods'][method] = scored
    (result_dir / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(f'rescored {result_dir}')


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--data', type=Path, default=Path('data/eval_ragtruth_resp.v2.6.jsonl'))
    ap.add_argument('--methods', nargs='+', default=['baseline', 'minimal', 'optimized'])
    ap.add_argument('--split', choices=['dev', 'test', 'all'], default='dev')
    ap.add_argument('--runs', type=int, default=1)
    ap.add_argument('--concurrency', type=int, default=4)
    ap.add_argument('--prompt-version',
                    default=(config.optional_env('VERIFIER_PROMPT_VERSION')
                             or prompts.DEFAULT_PROMPT_VERSION))
    ap.add_argument('--rescore', type=Path, default=None, metavar='DIR')
    ap.add_argument('--out', type=Path, default=None)
    args = ap.parse_args()
    if args.rescore:
        rescore(args.rescore, args.data)
        return
    cases = v26.load_cases(args.data, args.split)
    out = args.out or Path(f"results/{time.strftime('%Y%m%d-%H%M%S')}")
    out.mkdir(parents=True, exist_ok=True)
    summary = {'dataset': str(args.data), 'split': args.split, 'n_cases': len(cases),
               'prompt_version': args.prompt_version, 'methods': {}}
    for method in args.methods:
        try:
            verifier = build(method, args.prompt_version)
        except KeyError as e:
            raise SystemExit(f'missing setting {e}: fill it in .env (see .env.example) or export it')
        runs = []
        for k in range(args.runs if method != 'baseline' else 1):  # baseline is deterministic
            sem = asyncio.Semaphore(args.concurrency)
            rows = await asyncio.gather(*(run_one(verifier, c, sem) for c in cases))
            with open(out / f'{method}_run{k}.jsonl', 'w', encoding='utf-8') as f:
                for row in rows:
                    f.write(json.dumps(row, ensure_ascii=False) + '\n')
            report = score(cases, rows)
            runs.append(report)
            f1 = report['answer_level']['main']['metrics']['f1']['value']
            print(f'{method}_run{k}: response_f1={f1} errors={report["errors"]}')
        summary['methods'][method] = runs
    (out / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(f'wrote {out}')


if __name__ == '__main__':
    asyncio.run(main())
