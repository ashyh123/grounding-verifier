"""Turn results into markdown.

python -m eval.report results/<dir>                 # comparison table (mean ± std over runs)
python -m eval.report results/<dir> --failures optimized   # list of wrong claims for analysis
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean, pstdev

from verifier.align import align_claims

from .dataset import load

ROWS = [
    ("Answer-level hallucination F1", lambda m: m["answer_level"]["f1"]),
    ("Claim accuracy (all gold claims)", lambda m: m["claim_accuracy_all_gold"]),
    ("Claim accuracy (matched only)", lambda m: m["claim_accuracy_matched"]),
    ("Macro-F1 (3 verdicts)", lambda m: m["macro_f1"]),
    ("F1 SUPPORTED", lambda m: m["per_label"]["SUPPORTED"]["f1"]),
    ("F1 CONTRADICTED", lambda m: m["per_label"]["CONTRADICTED"]["f1"]),
    ("F1 UNSUPPORTED", lambda m: m["per_label"]["UNSUPPORTED"]["f1"]),
    ("Decomposition recall", lambda m: m["decomposition"]["recall"]),
    ("Decomposition precision", lambda m: m["decomposition"]["precision"]),
    ("Answer sentence coverage", lambda m: m["sentence_coverage"]),
    ("Fused claims (claim spans >1 sentence)", lambda m: m["fused_claim_rate"]),
    ("Citation precision", lambda m: m["citation_precision"]),
    ("Citation recall", lambda m: m["citation_recall"]),
    ("Citation precision (right passage)", lambda m: m["citation_passage_precision"]),
    ("Citation recall (right passage)", lambda m: m["citation_passage_recall"]),
    ("Raw citation invalid rate (before repair)", lambda m: m["raw_citation_invalid_rate"]),
    ("Latency p50 (ms)", lambda m: m["latency_ms_p50"]),
    ("Latency p95 (ms)", lambda m: m["latency_ms_p95"]),
    ("LLM calls / case", lambda m: m["avg_llm_calls"]),
    ("Cost / case (USD)", lambda m: m["avg_cost_usd"]),
    ("Errored cases", lambda m: m["errors"]),
]


def _fmt(vals: list[float]) -> str:
    if len(vals) == 1:
        return f"{vals[0]:.3f}" if vals[0] < 100 else f"{vals[0]:.0f}"
    return f"{mean(vals):.3f} ± {pstdev(vals):.3f}"


def table(summary: dict) -> str:
    methods = list(summary["methods"])
    lines = [f"Split: `{summary['split']}`, cases: {summary['n_cases']}, oracle claims: {summary['oracle']}", "",
             "| Metric | " + " | ".join(methods) + " |",
             "|---|" + "---|" * len(methods)]
    for name, fn in ROWS:
        cells = [_fmt([fn(m) for m in summary["methods"][k]]) for k in methods]
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def failures(result_dir: Path, method: str, data: str) -> str:
    cases = {c.id: c for c in load(data)}
    path = sorted(result_dir.glob(f"{method}*_run0.jsonl"))[0]
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        case = cases[row["id"]]
        if "error" in row:
            out.append(f"### {case.id}: ERROR {row['error']}")
            continue
        pred = row["claims"]
        oracle = "_oracle" in path.name
        pairs = ([(i, i, 100.0) for i in range(min(len(pred), len(case.gold_claims)))] if oracle
                 else align_claims([c["claim_text"] for c in pred], [g.claim_text for g in case.gold_claims]))
        matched = {g for _, g, _ in pairs}
        for pi, gi, _ in pairs:
            g, p = case.gold_claims[gi], pred[pi]
            if g.verdict.value != p["verdict"]:
                out.append(f"### {case.id} [{', '.join(g.tags or case.tags)}]\n"
                           f"- gold: {g.verdict.value} — {g.claim_text}\n"
                           f"- pred: {p['verdict']} — {p['claim_text']}\n"
                           f"- reasoning: {p['reasoning']}\n")
        for gi, g in enumerate(case.gold_claims):
            if gi not in matched:
                out.append(f"### {case.id} MISSED gold claim ({g.verdict.value}): {g.claim_text}\n")
    return "\n".join(out) or "No failures."


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("result_dir")
    ap.add_argument("--failures", metavar="METHOD")
    ap.add_argument("--data", default="data/eval.jsonl")
    a = ap.parse_args()
    d = Path(a.result_dir)
    if a.failures:
        print(failures(d, a.failures, a.data))
    else:
        print(table(json.loads((d / "summary.json").read_text())))
