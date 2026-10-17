"""Benchmark runner.

python -m eval.run --methods baseline minimal optimized --split dev --runs 1
python -m eval.run --methods optimized --split test --runs 3 --oracle
Writes results/<timestamp>/<method>[_oracle]_run<k>.jsonl and summary.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

from verifier import config, prompts
from verifier.baseline import BaselineVerifier
from verifier.llm import UpstreamError, build_client
from verifier.llm_verifiers import MinimalVerifier, OptimizedVerifier
from verifier.schemas import VerifyRequest

from . import metrics
from .dataset import load

# USD per 1M tokens, from .env. Fill in from your provider's pricing page; the value
# only feeds the cost column of the report.
PRICE_IN = config.float_env("PRICE_IN_PER_MTOK", 0.0)
PRICE_OUT = config.float_env("PRICE_OUT_PER_MTOK", 0.0)


def build(method: str, prompt_version: str = "v1"):
    if method == "baseline":
        return BaselineVerifier()
    if method == "minimal":
        return MinimalVerifier(build_client())
    if method == "optimized":
        return OptimizedVerifier(build_client(), prompt_version=prompt_version)
    raise ValueError(method)


async def run_one(verifier, case, oracle: bool, sem: asyncio.Semaphore) -> dict:
    async with sem:
        try:
            if oracle:
                r = await verifier.verify_claims(case.context_passages,
                                                 [g.claim_text for g in case.gold_claims])
            else:
                r = await verifier.verify(VerifyRequest(context_passages=case.context_passages,
                                                        generated_answer=case.generated_answer))
            return {"id": case.id} | r.model_dump(mode="json")
        except UpstreamError as e:
            return {"id": case.id, "error": str(e)}


def rescore(result_dir: Path, data: str) -> None:
    """Recompute summary.json from the JSONL already on disk. No provider calls, no API key.

    Metric definitions change more often than predictions do, and re-running a paid evaluation
    to change a denominator is the wrong trade.
    """
    summary = json.loads((result_dir / "summary.json").read_text(encoding="utf-8"))
    cases = [c for c in load(data)
             if summary["split"] == "all" or c.split == summary["split"]]
    case_ids = {c.id for c in cases}
    for method in summary["methods"]:
        tag = f"{method}{'_oracle' if summary['oracle'] else ''}"
        runs = []
        for k in range(len(summary["methods"][method])):
            path = result_dir / f"{tag}_run{k}.jsonl"
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                    if line.strip()]
            predicted = {r["id"] for r in rows}
            if predicted != case_ids:
                raise SystemExit(
                    f"{path} does not match the current {summary['split']} split "
                    f"({len(predicted ^ case_ids)} case ids differ): this run predates a dataset "
                    f"change, rescoring it would produce numbers that were never measured")
            m = metrics.compute(cases, {r["id"]: r for r in rows}, oracle=summary["oracle"])
            m["avg_cost_usd"] = (m["avg_input_tokens"] * PRICE_IN
                                 + m["avg_output_tokens"] * PRICE_OUT) / 1e6
            runs.append(m)
        summary["methods"][method] = runs
    summary["n_cases"] = len(cases)
    (result_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"rescored {result_dir} ({summary['n_cases']} cases, split {summary['split']})")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/eval.jsonl")
    ap.add_argument("--methods", nargs="+", default=["baseline", "minimal", "optimized"])
    ap.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--oracle", action="store_true", help="feed gold claims, skip decomposition")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--prompt-version",
                    default=(config.optional_env("VERIFIER_PROMPT_VERSION")
                             or prompts.DEFAULT_PROMPT_VERSION),
                    help=f"prompt set used by the optimized verifier {sorted(prompts.PROMPT_SETS)}; "
                         f"defaults to VERIFIER_PROMPT_VERSION, else {prompts.DEFAULT_PROMPT_VERSION}")
    ap.add_argument("--rescore", metavar="DIR", default=None,
                    help="recompute DIR/summary.json from its JSONL, without calling the provider")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    if args.rescore:
        rescore(Path(args.rescore), args.data)
        return

    cases = [c for c in load(args.data) if args.split == "all" or c.split == args.split]
    out = Path(args.out or f"results/{time.strftime('%Y%m%d-%H%M%S')}")
    out.mkdir(parents=True, exist_ok=True)
    summary: dict = {"split": args.split, "oracle": args.oracle, "n_cases": len(cases),
                     "prompt_version": args.prompt_version, "methods": {}}

    for method in args.methods:
        try:
            verifier = build(method, args.prompt_version)
        except KeyError as e:  # missing VERIFIER_MODEL / API key: say so before spending time
            raise SystemExit(f"missing setting {e}: fill it in .env (see .env.example) or export it")
        runs = []
        for k in range(args.runs if method != "baseline" else 1):  # baseline is deterministic
            sem = asyncio.Semaphore(args.concurrency)
            rows = await asyncio.gather(*(run_one(verifier, c, args.oracle, sem) for c in cases))
            tag = f"{method}{'_oracle' if args.oracle else ''}_run{k}"
            with open(out / f"{tag}.jsonl", "w", encoding="utf-8") as f:
                for row in rows:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            m = metrics.compute(cases, {r["id"]: r for r in rows}, oracle=args.oracle)
            m["avg_cost_usd"] = (m["avg_input_tokens"] * PRICE_IN
                                 + m["avg_output_tokens"] * PRICE_OUT) / 1e6
            runs.append(m)
            print(f"{tag}: claim_acc={m['claim_accuracy_all_gold']:.3f} "
                  f"macro_f1={m['macro_f1']:.3f} answer_f1={m['answer_level']['f1']:.3f} "
                  f"errors={m['errors']}")
        summary["methods"][method] = runs

    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    asyncio.run(main())
