# v2.5 test measurement plan

**Status: one-round e2e measurement complete (45 test cases, no oracle). The 3-round plan and
oracle runs were not executed because the ¥15 budget cannot cover them. The dataset and v2.5
freeze are unchanged.**

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

**Gate status:** the optimized JSON repair is applied and verified on the four captured failure
cases. The remaining network-level retry exposure has not been re-measured on all 18 dev cases;
the test run itself will quantify it.

**User choice:** fix optimized first, then run 3 rounds. Budget stated as **15 元**; the unit
must be confirmed before spending. The 3-round lower bound is **$8.53 (≈¥61)**, so ¥15
(≈$2.1) is not sufficient. If the intended cap is $15 (≈¥107), the plan below fits.

**3-round plan:** run 3 rounds e2e + 3 oracle for minimal and optimized, and 1 round for
baseline, on the frozen 45-case test split. Report mean ± std per run; do not pool runs as
independent cases. Estimated lower bound $8.53; cap $15 (≈¥107). If the cap is ¥15, stop
before the run or reduce to a single minimal-only diagnostic; do not silently overspend.

**Scoring:** run `eval/v25.py` on each saved prediction file with `--split test` and
`--doubts data/annotation/v2.5/doubt_classes.jsonl`; report `all`, `natural`,
`conflict_supplement`, `subtle_supplement`, the preregistered sensitivity analysis, and the
origin/generator groups. Keep raw predictions under `results/<v2.5-test>/`.

**Stop conditions:** any method error rate above 5%; any context-limit or truncation failure;
any cost above the cap; any request to change a prompt or the dataset. Stop and report rather
than changing a rule.

## 2026-10-20 one-round e2e measurement (authorized)

After the budget clarification (¥15, 3 rounds infeasible) the user selected **1 round e2e,
no oracle**. All three methods completed on the 45-case test split with **zero provider
errors**:

| method | errors | mean / max latency | cost (USD) |
|---|---:|---:|---:|
| baseline | 0/45 | 0.8 ms / 3.3 ms | 0.000 |
| minimal | 0/45 | 8.9 s / 14.9 s | 0.270 |
| optimized v3 | 0/45 | 12.5 s / 20.5 s | 1.843 |

Observed total **$2.11 (≈¥15.2)**, slightly above the ¥15 cap. No further calls were made.
Optimized used 602 calls and 0 retries; minimal used 45 calls and 0 retries. No context-limit
or truncation failure occurred. Minimal recorded 13 downgraded claims and 34 validator
warnings; optimized recorded none.

| method | all det F1 | all macro-F1 | natural det F1 | conflict det F1 | subtle det F1 | sensitivity all det F1 |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 0.204 | 0.127 | 0.182 | 0.220 | 0.226 | 0.192 |
| minimal | 0.444 | 0.505 | 0.429 | 0.456 | 0.452 | 0.484 |
| optimized v3 | 0.432 | 0.504 | 0.416 | 0.447 | 0.432 | 0.434 |

These are one-round e2e numbers only; no oracle run and no 3-round variance estimate. Raw
predictions and summaries are in `results/v2.5-test/e2e-r1/`; v2.5 metric reports are in
`results/v2.5-test/metrics/`. The dataset and v2.5 freeze were not changed by this run.

**Not authorized:** no oracle run, no further test rounds, no prompt change, and no claim of
3-run stability. A 3-round plan requires a new budget instruction.
