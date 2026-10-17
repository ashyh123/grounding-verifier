# Evaluation method

How the three verifiers are measured, what every number means, and which of them can be trusted for
what. Dataset contents and labelling rules live in [DATASET.md](DATASET.md); the measured results are in
[REPORT.md](REPORT.md); the version-by-version history in [ITERATIONS.md](ITERATIONS.md).

## Dataset and splits

46 hand-authored cases / 150 gold claims, every line validated on load
(`uv run python -m eval.dataset data/eval.jsonl`):

| | dev | test | total |
|---|---|---|---|
| Cases | 26 | 20 | 46 |
| Gold claims | 89 | 61 | 150 |
| SUPPORTED / CONTRADICTED / UNSUPPORTED | 49 / 30 / 10 | 42 / 13 / 6 | 91 / 43 / 16 |

**Split policy:** `dev` is read as often as needed while iterating (prompts, models, thresholds).
`test` is read once, at the end, by `make eval-test`, with the configuration chosen on dev. Model choice,
prompt version and any threshold were all decided on dev; the label audit and the two held-out label
corrections are documented as exceptions in
[ITERATIONS.md](ITERATIONS.md#dataset-calibration-also-eval-driven).

## Harness

```bash
make eval-dev     # baseline + minimal + optimized on dev, 1 run
make eval-test    # held-out split, 3 runs end-to-end + 3 runs oracle → results/final_e2e, results/final_oracle

uv run python -m eval.run --methods minimal optimized --split dev --runs 3 --prompt-version v3 --out results/dev-v3-x3
uv run python -m eval.report results/dev-v3-x3                  # comparison table
uv run python -m eval.report results/dev-v3-x3 --failures optimized   # per-case error listing
uv run python -m eval.run --rescore results/dev-v3-x3           # recompute metrics from saved predictions
```

`eval/run.py` writes one JSONL per run (one line per case: `id`, `claims`, `meta`, or `error`) plus
`summary.json` with every metric. `eval/metrics.py` contains pure functions over those files — no LLM
calls anywhere in the reporting path. `eval/report.py` renders the markdown table and the failure list.

**Rescore mode** recomputes `summary.json` from the JSONL already on disk. Metric definitions change far
more often than predictions do, and re-running a paid evaluation to change a denominator is the wrong
trade. Rescoring **refuses** a run whose case ids do not match the current dataset: such a run predates a
dataset change, and scoring it would produce numbers that were never measured.

## Alignment: how a predicted claim meets a gold claim

Predicted claims are matched to gold claims with `rapidfuzz.token_set_ratio` in a Hungarian assignment
(`scipy.optimize.linear_sum_assignment`, threshold 60, `verifier/align.py`). Consequences:

* a verifier is not punished for splitting one gold claim into two, or for rewording one — the sibling
  claim aligns as long as it is recognisably the same fact;
* gold claims nobody matched are counted as **`MISSED`** in the confusion matrix; they lower recall
  rather than being silently dropped;
* `oracle=True` mode skips alignment entirely: gold claims are fed in order, so pair *i* is compared with
  pair *i*.

## Metrics

| Metric | Definition | Read it as |
|---|---|---|
| Answer-level hallucination P/R/F1 | positive class = "this answer contains at least one non-SUPPORTED claim" | does the service flag a bad answer at all — coarse but the user-facing question |
| Claim accuracy (all gold claims) | correct verdicts ÷ gold claims, missed claims counted wrong | the headline number |
| Claim accuracy (matched only) | correct verdicts ÷ matched pairs | verdict quality without decomposition loss |
| Macro-F1 (3 verdicts) | unweighted mean of per-label F1 | the number that exposes a method collapsing on one class |
| F1 SUPPORTED / CONTRADICTED / UNSUPPORTED | per-label P/R/F1 over the confusion matrix | which boundary the method gets wrong |
| Decomposition recall / precision | matched pairs ÷ gold claims, and ÷ predicted claims | recall = claims missed; precision < 1 ≈ over-splitting |
| **Answer sentence coverage** | share of the answer's sentences matched by some predicted claim (≥60 token-set) | did every sentence of the answer reach the verifier — measured against the answer, no labels needed |
| **Fused claim rate** | share of predicted claims that carry ≥2 distinctive content words from each of two different answer sentences | did a claim swallow two sentences into one, hiding the one it swallowed. A claim that *is* an answer sentence scores zero by construction; the earlier similarity-based version had an ~11 % false-positive floor (the baseline scored 0.113 while being unable to fuse) |
| Citation precision / recall | predicted spans overlapping any gold evidence span; recall additionally needs ≥50 % coverage of the gold span | whether the citation points at the evidence — **annotator-strict**: a different sentence of the right passage counts as a miss |
| Citation precision / recall (right passage) | same question, credit if the cited passage is one of the annotated evidence passages | the annotation-taste-free version of the previous row |
| Raw citation invalid rate | invalid citations ÷ raw citations **before** repair | how sloppy the model is on its own — the repair must not hide this |
| Latency p50 / p95 | per-case wall clock at `--concurrency 4` | not a throughput measurement |
| Input / output tokens per case, calls per case, cost per case | from `meta`, summed over retries separately | cost proxy; cost = tokens × the `.env` prices |

## Oracle mode: separating "judged wrongly" from "checked the wrong text"

`--oracle` feeds the gold claims in and skips decomposition. This is the single most informative switch in
the harness, because it splits the error budget in two:

| | dev | test |
|---|---|---|
| baseline, end-to-end → oracle | 0.382 → 0.494 | 0.590 → 0.705 |
| minimal, end-to-end → oracle | 0.989 → **1.000** | 0.984 → 0.978 |
| optimized v3, end-to-end → oracle | 0.989 → **1.000** | 0.984 → **1.000** |

Reading: for both LLM verifiers on dev, **verification is solved** once the claims are given, so the
end-to-end error is decomposition; for the baseline the bottleneck is the opposite (lexical matching
cannot decide entailment, and its sentence splitter already recovers 0.775 of the gold claims). That
attribution is what directed the whole v3/v4 iteration cycle, and it is only visible because the oracle
run exists.

## Adding a metric

1. add the counter to `eval/metrics.compute` (pure function, no I/O);
2. add a row to `eval/report.ROWS`;
3. `uv run python -m eval.run --rescore <dir>` for every historical run — no provider calls.

That is how answer sentence coverage and the fused-claim rate were added when prompt v4 needed them
measured, and how the cost column was filled in after real prices replaced the placeholder zeros.

## Measurement caveats

* **150 claims, one annotator.** Differences below ~5 points on one split are noise; the final test
  report therefore shows mean ± std over 3 runs, and the dev hill-climb repeats runs before deciding.
  A model-based read-back audit agrees with 149/150 labels (147/150 for the single call) — a second
  reader, not a second human annotator.
* **Multiple comparisons.** Five prompt versions and two models were compared on the same dev split.
  The pinned configuration (v3, `deepseek-v4-pro`) is the one that won on 3-run means; the losers are
  kept in the log, including the ones whose single-run advantage did not reproduce.
* **Cost is computed, not billed**, from prices snapshot-dated in `docs/ITERATIONS.md` and configured in
  `.env`; every input token is billed at the cache-miss rate, so the column is an upper bound. It is
  comparable within one client transport, because the two transports report usage differently (fixed
  in `_input_volume`, still worth knowing when reading historical artifacts).
* **The dataset is easier than intended** for a strong model: after the hardening pass, methods sit at
  0.97–0.99 claim accuracy on dev. The report therefore leans on verdict-boundary F1, citation rows,
  sentence coverage, calls and cost — not on claim accuracy alone.
* **The empty-context cases are solved by construction** (no passages ⇒ UNSUPPORTED), so they inflate
  UNSUPPORTED recall for every method and test robustness, not discrimination.
