"""Turn results into markdown.

python -m eval.report results/<dir>                 # comparison table (mean ± std over runs)
python -m eval.report results/<dir> --failures optimized   # list of wrong claims for analysis
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean, pstdev

from .dataset import load
from .scoring import align_case, parent_verdict

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
    ("Guard-rejected candidate pairs", lambda m: m["guard_rejected_pairs"]),
    ("Missed gold claims", lambda m: m["decomposition"]["missed_gold"]),
    ("Used predicted claims", lambda m: m["decomposition"]["used_predictions"]),
    ("Extra predicted claims", lambda m: m["decomposition"]["extra_predictions"]),
    ("Duplicate predicted claims", lambda m: m["decomposition"]["duplicate_predictions"]),
    ("Added predicted claims", lambda m: m["decomposition"]["added_predictions"]),
    ("Answer sentence coverage", lambda m: m["sentence_coverage"]),
    ("Fused claims (claim spans >1 sentence)", lambda m: m["fused_claim_rate"]),
    ("Citation precision", lambda m: m["citation_precision"]),
    ("Citation recall", lambda m: m["citation_recall"]),
    ("Scored citations", lambda m: m["citation_counts"]["predicted"]),
    ("Gold evidence spans", lambda m: m["citation_counts"]["gold"]),
    ("Invalid scored citations", lambda m: m["citation_counts"]["invalid"]),
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
    registries = sorted({m["scoring_units_registry_sha256"] for runs in summary["methods"].values()
                         for m in runs if m.get("scoring_units_registry_sha256")})
    if registries:
        lines[1:1] = ["Approved scoring-unit registry SHA256: " + ", ".join(f"`{h}`" for h in registries), ""]
    for name, fn in ROWS:
        cells = []
        for method in methods:
            try:
                cells.append(_fmt([fn(m) for m in summary["methods"][method]]))
            except KeyError:  # preserved historical summaries have no new counters
                cells.append("N/A")
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    dimensions = sorted({d for runs in summary["methods"].values() for m in runs
                         for d in m.get("groups", {})})
    for dimension in dimensions:
        lines += ["", f"Grouped claim metrics: `{dimension}`", "",
                  "| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |",
                  "|---|---|---:|---:|---:|---:|---:|---:|"]
        for method, runs in summary["methods"].items():
            names = sorted({name for m in runs for name in m.get("groups", {}).get(dimension, {})})
            for name in names:
                values = [m["groups"][dimension][name] for m in runs]
                first = values[0]
                cells = [_fmt([v[key] for v in values]) for key in
                         ("matched_pairs", "claim_accuracy_all_gold", "macro_f1", "decomposition_recall")]
                lines.append(f"| {name} | {method} | {first['n_cases']} | {first['gold_claims']} | "
                             + " | ".join(cells) + " |")
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
        alignment = align_case(case, pred, oracle)
        matched = set(alignment.matches)
        for gi, indices in alignment.matches.items():
            g = case.gold_claims[gi]
            verdict = parent_verdict(pred, indices)
            if g.verdict.value != verdict:
                texts = " + ".join(pred[i]["claim_text"] for i in indices)
                reasons = " | ".join(pred[i].get("reasoning", "") for i in indices)
                out.append(f"### {case.id} [{', '.join(g.tags or case.tags)}]\n"
                           f"- gold: {g.verdict.value} — {g.claim_text}\n"
                           f"- pred: {verdict} — {texts}\n"
                           f"- reasoning: {reasons}\n")
        for gi, g in enumerate(case.gold_claims):
            if gi not in matched:
                out.append(f"### {case.id} MISSED gold claim ({g.verdict.value}): {g.claim_text}\n")
        for pi, p in enumerate(pred):
            if pi not in alignment.used_predictions:
                out.append(f"### {case.id} EXTRA predicted claim ({p['verdict']}): {p['claim_text']}\n")
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
