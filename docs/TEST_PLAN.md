# v2.5 test measurement plan

> **Superseded.** This is the historical v2.5 plan. The current v2.6 plan, freeze and measured
> test report are [freeze.json](../data/annotation/v2.6/freeze.json) and
> [p4-test-report.md](../data/annotation/v2.6/p4-test-report.md); the v2.5 results are exploratory.

**Status: test measurement complete (3 e2e rounds for minimal/optimized, 1 deterministic
baseline run, 1 oracle round). Total $8.32 (≈¥59.8), within the ¥65 cap. The dataset and
v2.5 freeze are unchanged.**

## Configuration used in the dev dry run

- Dataset: `data/eval_hard.v2.5.jsonl`, split `dev`（18 例 / 245 条主张）。
- Evaluated verifier: `deepseek-v4-pro`, `DEEPSEEK_API_KEY`, base URL
  `https://api.deepseek.com/v1`; provider parameters from `.env`; prompt version `v3`;
  concurrency 4; no prompt change.
- Annotation roles remain `mimo-v2.6-pro`; annotation and evaluation keys are separate.
- Command shape:
  `uv run python -m eval.run --data data/eval_hard.v2.5.jsonl --methods baseline minimal optimized --split dev --runs 1 [--oracle] --out results/<v2.5-dev-dryrun>/...`

## Dev dry-run results (1 round each, pre-fix diagnostics; not headline scores)

| method | e2e errors | oracle errors | e2e mean latency | e2e cost (USD) | oracle mean latency | oracle cost (USD) |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 0/18 | 0/18 | 1 ms | 0.000 | 1 ms | 0.000 |
| minimal | 0/18 | 0/18 | 7.9 s | 0.111 | 9.6 s | 0.132 |
| optimized v3 | 5/18 (27.8%) | 5/18 (27.8%) | 9.7 s | 0.449 | 7.2 s | 0.446 |

- The 5 optimized e2e failures were `unparseable response: Expecting ',' delimiter` after
  retries; the 5 oracle failures were `[Errno 8] nodename nor servname provided` after retries.
  Both are provider/response-reliability failures, not context-length failures. Minimal had
  zero failures in both modes.
- Cost totals only successful calls; failed attempts may have consumed tokens that are not in
  the run meta. The pre-fix dev total is **$1.137**; the internal cap of $5 was not reached.
- No context-limit rejection or output truncation was observed; the longest dev context is
  1626 words. All v2.5 metrics (all/natural/conflict_supplement/subtle_supplement,
  sensitivity, origin and generator groups) were produced for all six runs.

**Post-freeze repair (user-authorized):** `verifier/openai_client.py` now repairs unescaped
quotes, JSON fragments copied into quote strings, missing/trailing commas and missing closing
quotes deterministically before a provider retry. Unit tests cover every captured malformed
response. The four remaining previously failing cases (`ragtruth-5851`, `-6973`, `-8395`,
`-9775`) passed end-to-end with **0 retries**; this cost $0.313. The change touches verifier
code, so the v2.5 freeze was reissued; the old freeze is archived as
`freeze.pre-optimized-fix.json`. A full post-fix 18-case dev run was not repeated before the
budget decision.

## Cost extrapolation to the 45-case test split

Dev has 18 cases; test has 45 (2.5×). Using the observed per-case cost:

| plan | minimal | optimized | total lower bound | proposed cap |
|---|---:|---:|---:|---:|
| 1 round e2e + 1 oracle | $0.61 | $2.24 | **$2.85** | **$5** |
| 3 rounds e2e + 3 oracle | $1.82 | $6.71 | **$8.53** | **$15** |

The lower bound omits failed-call usage; a 20–30% allowance gives roughly $3.3–3.7 for the
one-round plan. Baseline costs $0.

## Measurement plan (user chose fix-first + 3 rounds)

**Gate status:** the optimized JSON repair is applied and verified; the test measurement below
completed with zero provider errors.

**Budget:** user raised the cap to **¥65**. A full 3 e2e + 3 oracle plan exceeds it, so the
executed plan reuses e2e round 1, adds e2e rounds 2–3, and runs **one** oracle round.

**Scoring:** `eval/v25.py` with `--split test` and
`--doubts data/annotation/v2.5/doubt_classes.jsonl`; reports `all`, `natural`,
`conflict_supplement`, `subtle_supplement`, the preregistered sensitivity analysis, and the
origin/generator groups.

**Stop conditions:** any method error rate above 5%; any context-limit or truncation failure;
any cost above the cap; any request to change a prompt or the dataset.

## 2026-10-20 test measurement (3 e2e rounds + 1 oracle round)

All runs completed with **zero provider errors**. Total **$8.32 (≈¥59.8)**, within the ¥65
cap. Baseline is deterministic, so it has one e2e run; minimal and optimized have three.
Values are mean ± sample std across runs.

| method | e2e runs | errors | all det F1 | all macro-F1 | natural | conflict | subtle | sensitivity | cost/run | latency mean / max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline | 1 | 0 | 0.204 | 0.127 | 0.182 | 0.220 | 0.226 | 0.192 | $0.000 | 0.8 ms / 3.3 ms |
| minimal | 3 | 0 | 0.455±0.010 | 0.516±0.015 | 0.443±0.025 | 0.476±0.018 | 0.439±0.035 | 0.492±0.014 | $0.269±0.002 | 9.0 s / 15.2 s |
| optimized v3 | 3 | 0 | 0.434±0.005 | 0.505±0.004 | 0.417±0.003 | 0.437±0.018 | 0.465±0.034 | 0.431±0.004 | $1.842±0.026 | 12.3 s / 22.4 s |

One oracle round (not three, because three oracle rounds exceed ¥65):

| method | all det F1 | all macro-F1 | natural | conflict | subtle | cost | latency mean / max |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline | 0.234 | 0.237 | 0.221 | 0.266 | 0.207 | $0.000 | 1.1 ms / 4.0 ms |
| minimal | 0.541 | 0.584 | 0.508 | 0.593 | 0.516 | $0.300 | 10.5 s / 17.6 s |
| optimized v3 | 0.505 | 0.572 | 0.474 | 0.507 | 0.571 | $1.692 | 8.7 s / 17.2 s |

- No context-limit or truncation failure. Minimal recorded 7–13 downgraded claims and 21–34
  validator warnings per run; optimized recorded none. Optimized had 1 retry in e2e rounds 2–3
  and the oracle round, with 0 errors.
- The sensitivity analysis removes 21 test claims. `subtle_supplement` is 10 例 / 110 条主张；
  its per-subset numbers are diagnostic.
- Raw predictions and summaries: `results/v2.5-test/e2e-r1/`, `e2e-r2-3/`, `oracle-r1/`;
  aggregated metrics: `results/v2.5-test/aggregate-3r.json`; per-run v2.5 reports:
  `results/v2.5-test/metrics/`.
- The dataset and v2.5 freeze were not changed by these runs. Oracle coverage is one round only;
  no 3-run oracle variance is claimed.
