# v2.5 test measurement plan — DRAFT

**Status: draft only. No hard-test verifier has been run. Awaiting user confirmation before any
test measurement or prompt/code change.**

## Configuration used in the dev dry run

- Dataset: `data/eval_hard.v2.5.jsonl`, split `dev`（18 例 / 245 条主张）。
- Evaluated verifier: `deepseek-v4-pro`, `DEEPSEEK_API_KEY`, base URL
  `https://api.deepseek.com/v1`; provider parameters from `.env`; prompt version `v3`;
  concurrency 4; no prompt change.
- Annotation roles remain `mimo-v2.6-pro`; annotation and evaluation keys are separate.
- Command shape:
  `uv run python -m eval.run --data data/eval_hard.v2.5.jsonl --methods baseline minimal optimized --split dev --runs 1 [--oracle] --out results/<v2.5-dev-dryrun>/...`

## Dev dry-run results (1 round each; diagnostics only, not headline scores)

| method | e2e errors | oracle errors | e2e mean latency | e2e cost (USD) | oracle mean latency | oracle cost (USD) |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 0/18 | 0/18 | 1 ms | 0.000 | 1 ms | 0.000 |
| minimal | 0/18 | 0/18 | 7.9 s | 0.111 | 9.6 s | 0.132 |
| optimized v3 | 5/18 (27.8%) | 5/18 (27.8%) | 9.7 s | 0.449 | 7.2 s | 0.446 |

- The 5 optimized e2e failures are `unparseable response: Expecting ',' delimiter` after
  retries; the 5 oracle failures are `[Errno 8] nodename nor servname provided` after retries.
  Both are provider/response-reliability failures, not context-length failures. Minimal had
  zero failures in both modes.
- Cost totals only successful calls; failed attempts may have consumed tokens that are not in
  the run meta. The observed dev total is **$1.137**; the internal cap of $5 was not reached.
- No context-limit rejection or output truncation was observed; the longest dev context is
  1626 words. All v2.5 metrics (all/natural/conflict_supplement/subtle_supplement,
  sensitivity, origin and generator groups) were produced for all six runs.

## Cost extrapolation to the 45-case test split

Dev has 18 cases; test has 45 (2.5×). Using the observed per-case cost:

| plan | minimal | optimized | total lower bound | proposed cap |
|---|---:|---:|---:|---:|
| 1 round e2e + 1 oracle | $0.61 | $2.24 | **$2.85** | **$5** |
| 3 rounds e2e + 3 oracle | $1.82 | $6.71 | **$8.53** | **$15** |

The lower bound omits failed-call usage; a 20–30% allowance gives roughly $3.3–3.7 for the
one-round plan. Baseline costs $0.

## Proposed measurement (not final)

**Gate first:** the optimized method failed on 27.8% of dev cases in both modes. A test run
with the same configuration would mix model capability with response-parsing/network
reliability. User decision required:

1. **Fix/re-authorize optimized robustness first** (e.g. JSON repair or a larger retry budget),
   then run the stable plan; or
2. **Measure as-is** and report the optimized error rate as part of the result, counting errors
   as empty output.

**If option 1 is chosen:** run 3 rounds e2e + 3 oracle for minimal and optimized, and 1 round
for baseline, on the frozen test split. Report mean ± std per run; do not pool runs as
independent cases. Estimated lower bound $8.53; cap $15.

**If option 2 is chosen:** run 1 round e2e + 1 oracle for all three methods first to quantify
test failure rate; estimated lower bound $2.85, cap $5. Then decide whether a 3-round
measurement is meaningful.

**Scoring:** run `eval/v25.py` on each saved prediction file with `--split test` and
`--doubts data/annotation/v2.5/doubt_classes.jsonl`; report `all`, `natural`,
`conflict_supplement`, `subtle_supplement`, the preregistered sensitivity analysis, and the
origin/generator groups. Keep raw predictions under `results/<v2.5-test>/`.

**Stop conditions:** any method error rate above 5%; any context-limit or truncation failure;
any cost above the cap; any request to change a prompt or the dataset. Stop and report rather
than changing a rule.

**Not authorized yet:** no test-split verifier call, no prompt change, no retry/code change,
and no final measurement claim.
