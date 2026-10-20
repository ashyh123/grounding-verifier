# Citation Grounding & Faithfulness Verifier

`POST /verify` takes source passages plus an LLM-generated answer, splits the answer into atomic
claims, and decides for each claim whether the passages **support** it, **contradict** it, or say
nothing about it (**UNSUPPORTED**) — attaching citations whose quotes are re-derived from the source
text, never trusted from the model.

```
POST /verify ─► decompose ─► verify each claim ─► deterministic validation ─► report
                (1 call)      (1 call per claim,    (quotes rebuilt from the
                               parallel, retry on     source; invariants enforced
                               invalid citation)      or the claim is downgraded)
```

Three implementations are benchmarked on the v2.7 external checks (RAGTruth++ and LLM-AggreFact),
the v2.6 RAGTruth response-level set (180 held-out answers), and the historical synthetic set.

> **Documentation v2** (2026-10-17; updated 2026-10-20 for the v2.7 headline) — index, revision record
> and conventions in [docs/README.md](docs/README.md).

## Current headline: v2.7 two external checks (measured)

**The ranking depends on the annotation standard; the oracle lead of optimized is not robust to
minimal's claim-count failures.**

### 1) v2.6 end-to-end, RAGTruth original annotation

On 180 unseen RAGTruth responses, minimal's answer-level F1 was 0.720, optimized's 0.609, and the
baseline's 0.521. Under this loose annotation and the end-to-end setting, minimal was better
(paired difference minimal − optimized +0.110 [+0.060, +0.163]). The v2.6 details remain in the
prior section below.

### 2) Track B: RAGTruth++ strict vs loose sentence gold

Same 229 RAGTruth++ responses, same predictions, two human annotation standards:

| Gold standard | minimal sentence F1 | optimized sentence F1 | paired optimized − minimal | Conclusion |
|---|---:|---:|---|---|
| loose (RAGTruth original) | **0.371** [0.271, 0.463] | 0.218 [0.152, 0.284] | −0.153 [−0.226, −0.086] | minimal is better |
| strict (RAGTruth++) | 0.522 [0.461, 0.578] | **0.628** [0.578, 0.677] | +0.106 [+0.046, +0.168] | optimized is better |

**The ranking is decided by the annotation standard: minimal is better under the loose standard,
optimized under the strict standard; choose by use case.** Answer-level balanced accuracy points the
same way: 0.758 vs 0.620 under loose gold, 0.647 vs 0.751 under strict gold. This is one set of
answers and one set of predictions; only the gold changed.

### 3) Track A: LLM-AggreFact, claims given (oracle)

461 documents / 854 claims, 10 subsets, claims supplied; this isolates verification from
decomposition:

| Method | Main BAcc (failures wrong) | Failures | BAcc excluding failures |
|---|---:|---:|---:|
| baseline | 0.608 | 0 | 0.608 |
| minimal | 0.729 | 32 / 461 (6.94%) | 0.768 |
| optimized | **0.776** | 0 | **0.776** |

Main paired optimized − minimal: **+0.047 [+0.011, +0.079]**. But minimal has 32 claim-count
mismatches (6.94%), above the registered 5% stop line. When those 32 documents are truly excluded,
minimal is 0.768 and optimized 0.776; the paired difference is **+0.032 [−0.016, +0.072]** —
no evidence of a difference. optimized and minimal each win 5 of 10 subsets (**5/5**); the macro is
also concentrated: Lfqa has 3 documents, TofuEval-MediaS 2 and TofuEval-MeetB 2, so it is not a
uniform per-subset ranking. Track A is therefore conditional: optimized leads under the
failures-count-as-wrong convention, but the lead disappears when minimal's malformed claim lists are
removed. This is independent of track B; it is not combined into one score.

Test spend: $10.80 total (two dev runs $1.76 + track A test $4.03 + track B test $5.01), below the
$16 cap. Full tables and the first five failure examples per track:
[REPORT.md](docs/REPORT.md); raw reports:
[v2.7-test/aggrefact](results/v2.7-test/aggrefact/report/v27_aggrefact_report.json) and
[v2.7-test/ragtruthpp](results/v2.7-test/ragtruthpp/report/v27_report.json); protocol:
[EVALUATION.md](docs/EVALUATION.md).

## Prior headline: RAGTruth v2.6 response-level (measured)

**Under RAGTruth's original annotation, the optimized pipeline's extra cost did not produce a higher
answer-level F1.** 180 unseen
RAGTruth test responses (62 hallucinated), gold from RAGTruth's upstream human spans, no model in
labelling, one run per method:

| Method | Precision | Recall | F1 [95% CI] | Sentence F1 | Raw citation validity | Cost / response |
|---|---:|---:|---|---:|---:|---:|
| baseline | 0.352 | 1.000 | 0.521 [0.442, 0.594] | 0.164 | 1.000 | $0.0000 |
| minimal | **0.578** | 0.952 | **0.720** [0.638, 0.791] | **0.498** | 0.953 | **$0.0052** |
| optimized v3 | 0.444 | **0.968** | 0.609 [0.524, 0.685] | 0.338 | 0.962 | $0.0342 |

Paired F1 differences (same responses, 95% CI): minimal − optimized +0.110 [+0.060, +0.163];
minimal − baseline +0.199 [+0.144, +0.256]; optimized − baseline +0.088 [+0.051, +0.126]. All
exclude 0, so minimal is better than optimized, and both LLM methods are better than the baseline.
Under this annotation, optimized is 6.6× the cost and buys +1.6 pp recall, but produces 75 false positives against
minimal's 43; its sentence-level F1 is 0.338 vs 0.498. The full metric report is
[v26_report.json](results/v2.6-test/report/v26_report.json); the freeze is
[freeze.json](data/annotation/v2.6/freeze.json); the test write-up is
[P4 report](data/annotation/v2.6/p4-test-report.md).

**Why v2.6 changed the benchmark.** v2.5's claim-level gold was noisy: RAGTruth marks hallucination spans
on the answer, not atomic claims, and the claim splitter/overlap mapping introduced upstream misses
and mapping errors. Its detection F1 also did not penalise missed SUPPORTED gold, and the 45-case hard
test was enriched for contradictions (40/45 hallucinated), so an all-positive baseline reached F1
0.94. v2.6 draws new, unseen natural-distribution responses and takes the gold directly from the
upstream annotation. The v2.5 results are kept below as exploratory analysis. v2.7 then tested whether this ranking survives a stricter gold (track B) and how the methods compare when claims are given (track A); see the current headline above.

## Exploratory: RAGTruth v2.5 claim-level (superseded)

The v2.5 claim-level measurement covered 45 held-out examples / 537 claims. Detection F1 was 0.204
(baseline), 0.455 ± 0.010 (minimal) and 0.434 ± 0.005 (optimized); the paired minimal − optimized
difference was +0.021 with a 95% interval of [−0.040, +0.078], so no ranking is supported. The
claim-level gold has the two noise sources above and the metric does not penalise missed SUPPORTED
claims; the numbers are retained as a methodological finding, not a result about the verifiers.
Details: [docs/REPORT.md](docs/REPORT.md) and
[posthoc.json](results/v2.5-test/posthoc/posthoc.json).

## Historical headline: RAGTruth v2.4 (unmeasured)

The v2.4 benchmark was `data/eval_hard.v2.4.jsonl`: all 案例=50、主张=638 (S570/C30/U38);
natural 案例=30、主张=382 (S341/C7/U34). Its results remain in
[the v2.4 report](data/annotation/v2.4/final_report.md).

## Historical synthetic result (held-out test split, 20 cases / 61 claims, 3 runs)

`make eval-test`, frozen configuration, `deepseek-v4-pro` — the split the prompts were never tuned on:

| | baseline | minimal (1 call) | optimized v3 (4.7 calls) |
|---|---|---|---|
| Claim accuracy | 0.590 | 0.984 | 0.984 |
| Claim accuracy, oracle (gold claims fed in) | 0.705 | 0.978 | **1.000** |
| Macro-F1 (3 verdicts) | 0.528 | **0.983** | 0.970 |
| Answer-level hallucination F1 | 0.889 | 1.000 | 1.000 |
| Latency p50 | 0.15 ms | 3.5 s | 4.8 s |
| Cost per case (USD, peak rates 2026-10-17) | 0.0000 | **0.0022** | 0.0078 |

**The honest reading:** end to end the two LLM methods tie on claim accuracy, and they fail in different
places — the single call loses on the verdict boundary, the pipeline loses on decomposition wording.
With gold claims fed in (oracle mode), both LLM methods score 1.000 on dev; on the held-out test split
the per-claim pipeline stays at 1.000 while the single call drops to 0.978. That is the pipeline's real
selling point, and it costs ~4.7× the calls and ~3.6× the cost per case. Development-split tables, full
failure analysis and threats to validity: [docs/REPORT.md](docs/REPORT.md).

## How it got here: eval-driven iteration

The v2.6 result is a protocol change, not a prompt change: the verifier and prompt v3 are identical
to v2.5, but the data and the unit of measurement are not. It is the round that made the cost/benefit
question answerable.

- **v2.6 — measured, prior headline.** New natural-distribution RAGTruth responses, upstream human
  spans as gold, response-level F1. minimal 0.720 > optimized 0.609; under RAGTruth's original end-to-end annotation, optimized
  costs 6.6× and is 11.1 F1 points behind. v2.7 shows the ranking reverses under strict gold, and the oracle result is
  conditional on how minimal's claim-count failures are counted. v2.5 is demoted to exploratory analysis. Log: [ITERATIONS.md](docs/ITERATIONS.md).

The prompt-version history below belongs to the historical synthetic benchmark: every change was
measured on its dev split (26 cases / 89 claims, 3 runs) before it was kept; its test split was run
once, with v3 frozen. Full log: docs/ITERATIONS.md.

- **minimal** (control, never edited): one call does decomposition and verification. Dev claim accuracy 0.989, macro-F1 0.983.
- **v1 — kept as the architecture.** Decompose, then verify each claim in its own call against numbered source sentences, with retry on invalid citations. Macro-F1 rose to 0.991 and answer-level F1 to 1.000, but claim accuracy dipped to 0.981: the decomposition step was rewording claims.
- **v2 — reverted.** Changed the decomposition *and* verification prompts at once; macro-F1 fell to 0.954 (UNSUPPORTED F1 0.900) and the regression could not be attributed to either change. Lesson: one change per iteration.
- **v3 — kept, frozen for the test run.** Decomposition only: copy every qualifier and trailing clause verbatim. It fixed `redis-cluster-long-31`, where a unit error had been trimmed away before verification. Dev 0.989 / macro-F1 0.997 with zero run-to-run variance.
- **v4 — reverted.** A sentence-coverage pass halved fused claims (0.043 → 0.022), but it made the model invent a claim on the no-claims case `no-claims-17` (answer-level F1 1.000 → 0.980) and raised cost from $0.0080 to $0.0087 per case and p50 latency from 4657 to 5749 ms. Its motivating example came from the test split, which is disclosed in the log.
- **A metric bug found on the way:** the fused-claim metric gave the sentence-splitting baseline, which cannot fuse, 0.113. It was rewritten to use distinctive content words (baseline now 0.000) before any decision relied on it.

## Key failure cases (v2.6 held-out test)

- **The baseline is an alarm that never sleeps.** It flags 176 of 180 responses (62 TP, 114 FP,
  4 TN), so its recall is 1.000 and its precision 0.352. It cannot be used as a detector on this
  distribution.
- **optimized over-flags clean answers.** `ragtruth-10458` (Data2txt, gpt-4) calls "Many customers
  enjoy the store's atmosphere" UNSUPPORTED although one review says "I just love everything,
  including the atmosphere". `ragtruth-11191` rejects a 4.0-star business rating because the claim
  says "according to customer reviews". There are 36 clean responses that optimized flags and
  minimal does not; this is the main cost of its strictness.
- **minimal misses real subtle conflicts.** `ragtruth-2374` (Summary, llama-2-13b) marks "friend of
  44 years" and "remains unconscious in the hospital" SUPPORTED; upstream marks both Subtle
  Conflict. `ragtruth-9840` marks "did not provide music" SUPPORTED from `"Music": null`; null means
  unknown, not false, and upstream marks the negative assertion as baseless.
- **One provider failure.** `ragtruth-5828` (optimized) exhausted retries on a malformed JSON
  response; it is a gold-positive case and counts as a missed detection. Failure rate 0.56%, below
  the 5% stop line, and not a truncation. No rerun was made.

### Historical synthetic failures

- **Baseline under-commits.** Lexical overlap cannot tell a paraphrase from a distortion, so distortions come back UNSUPPORTED instead of CONTRADICTED (CONTRADICTED F1 0.353).
- **Minimal loses on the verdict boundary.** `prometheus-counter-17`: the source says a counter only goes up *except when the process restarts*; minimal still calls "can only increase, never decrease" SUPPORTED. `http-retry-21`: it labels an over-claim CONTRADICTED while its own reasoning says the source is silent. The pipeline gets both right (CONTRADICTED F1 1.000 vs 0.960; oracle claim accuracy 1.000 vs 0.978).
- **The pipeline loses on decomposition.** `pg-checkpoint-20`: it fused two answer sentences into a claim the answer never made, then correctly rejected its own conflation. It also emits more claims than the reference (decomposition precision 0.803 vs 0.884), which costs it UNSUPPORTED F1 (0.923 vs 1.000).
- **Still open:** `jwt-claims-14` (dev) loses a subordinate clock-skew clause in every version. Decomposition, not verification, is the binding constraint.

## Quickstart

```bash
uv sync                      # or, without uv: python -m venv .venv && . .venv/bin/activate &&
                             #   pip install fastapi "uvicorn[standard]" pydantic anthropic httpx python-dotenv rapidfuzz rank-bm25 numpy scipy pytest
cp .env.example .env         # fill in your key; the service loads this file itself
make test                    # whole suite (unit, eval harness, doc checks); no key needed
make serve                   # uvicorn verifier.api:app on :8000
```

```console
$ curl -s localhost:8000/health
{"status":"ok","provider":"openai","model":"deepseek-v4-pro","prompt_version":"v3",
 "api_key_set":true,"base_url_set":true,"env_file":"/.../grounding-verifier/.env"}

$ curl -s -X POST 'localhost:8000/verify?method=optimized&include_meta=true' \
    -H 'content-type: application/json' -d '{
      "context_passages": ["Automatic checkpointing occurs by default when the WAL passes approximately 1000 pages."],
      "generated_answer": "WAL mode checkpoints automatically at roughly 500 pages."}'
# CONTRADICTED, citing passages[0] with exact start_char/end_char offsets
```

`.env` keys that matter: `VERIFIER_MODEL` and a key (`ANTHROPIC_API_KEY`, or `DEEPSEEK_API_KEY` with
`VERIFIER_PROVIDER=openai`), optional `VERIFIER_BASE_URL`, `VERIFIER_PROMPT_VERSION` (default `v3`),
`PRICE_IN_PER_MTOK` / `PRICE_OUT_PER_MTOK` for the cost column, and `VERIFIER_EXTRA_BODY` for endpoints
that need extra request fields (DeepSeek's thinking models need
`{"thinking":{"type":"disabled"}}` before they accept a forced tool call). Full table:
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#configuration-resolution).

## API in brief

`POST /verify?method=baseline|minimal|optimized&include_meta=true|false` — request
`{context_passages: [...], generated_answer: "..."}` (≤50 passages, ≤20 000 chars each, answer ≤10 000),
response `{claims: [{claim_text, verdict, reasoning, citations: [{index, quote, start_char, end_char}]}], meta?}`.

Guarantees enforced in code before returning: `SUPPORTED`/`CONTRADICTED` carry at least one citation,
`UNSUPPORTED` carries none, every `index` is in range, and `passages[index][start_char:end_char]` is
byte-identical to `quote` and a verbatim substring of the passage — or the claim is downgraded to
UNSUPPORTED. Errors: `422 invalid_request`, `502`/`504 upstream_error`, `500 misconfigured`,
`500 internal_invariant_violation`. Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## How the v2.6 benchmark is measured

The test split is run once with the frozen configuration; a rerun needs a new, unseen sample and a
new freeze. There is no oracle mode, because the response-level gold has no gold claims. The
prediction rule is registered: any `CONTRADICTED` or `UNSUPPORTED` claim makes the response positive.
Failed calls stay in the denominator as wrong; `excluding_failures` is reported next to the main
result. Sentence alignment uses the threshold 60 fixed on dev.

```bash
# Run the frozen protocol (3 methods, one run each; writes one JSONL per method)
uv run python -m eval.run_v26 --methods baseline minimal optimized --split test \
  --runs 1 --concurrency 4 --prompt-version v3 --out results/v2.6-test

# Score saved predictions (no provider calls; writes report/v26_report.{json,md})
uv run python -m eval.v26 --split test --predictions results/v2.6-test \
  --methods baseline minimal optimized --out results/v2.6-test/report

# Recompute summary.json from the saved JSONL after a metric-only change
uv run python -m eval.run_v26 --rescore results/v2.6-test
```

The freeze, sampling rules and dev threshold calibration are in
[data/annotation/v2.6/](../data/annotation/v2.6); the full method is in
[EVALUATION.md](docs/EVALUATION.md#v26-preregistration-prior-headline).

## How the historical synthetic benchmark is measured

These commands target the historical synthetic benchmark. v2.4 hard-test measurement is pending
separate instructions; score its eventual saved predictions with `python -m eval.v24` as described
in [EVALUATION.md](docs/EVALUATION.md). Its detection F1 and bootstrap report come from that entry.

```bash
uv run python -m eval.dataset data/eval.jsonl     # validate the dataset
make eval-dev                                     # baseline + minimal + optimized on dev
make eval-test                                    # held-out split, 3 runs, end-to-end + oracle
uv run python -m eval.report results/final_e2e    # comparison table
uv run python -m eval.report results/final_e2e --failures optimized   # per-case failures
PRICE_IN_PER_MTOK=1.32 PRICE_OUT_PER_MTOK=3.96 \
  uv run python -m eval.run --rescore results/final_e2e   # recompute metrics, no API calls
```

Oracle mode (`--oracle`) feeds gold claims in and skips decomposition, which is what separates "the
verifier judged wrongly" from "the verifier checked the wrong text". Rescore mode recomputes metrics from
saved predictions, so a metric change costs nothing; it refuses runs whose cases no longer match the
dataset. Definitions and caveats: [docs/EVALUATION.md](docs/EVALUATION.md).

## Where to read what

| I want to… | Read |
|---|---|
| run it, understand the shape of the project | this file |
| know how `POST /verify` works internally and where the trust boundary is | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| see the results, the failures and what they do *not* prove | [docs/REPORT.md](docs/REPORT.md) |
| judge or reuse the benchmark (metrics, splits, reproduction) | [docs/EVALUATION.md](docs/EVALUATION.md) |
| audit the current v2.6 responses and the historical 46-case synthetic set | [docs/DATASET.md](docs/DATASET.md) |
| see what was tried, kept and reverted (v2.6 protocol change, prompt v1→v4) | [docs/ITERATIONS.md](docs/ITERATIONS.md) |
| know what changed in this documentation revision | [docs/README.md](docs/README.md) |

## Status

Working and verified end to end against a live provider on both client transports; the suite is green
(`make test`, no key required — it includes the eval-harness and documentation-consistency checks).
The current headline is v2.7: under RAGTruth's original annotation minimal leads end-to-end
(0.720 vs 0.609), under RAGTruth++ strict gold optimized leads (sentence F1 0.628 vs 0.522), and with
the LLM-AggreFact oracle, optimized leads only when minimal's 32 claim-count failures are counted
wrong; truly excluding them, there is no evidence of a difference.
The optimized pipeline is held-out-measured at 0.984 claim accuracy / 1.000 answer-level F1 on the historical synthetic set,
oracle-perfect at 1.000 (test split, 3 runs), but that benchmark is not the current target. Known
open items: optimized's false positives on clean natural answers; minimal's misses on subtle
conflicts and null-valued attributes; one annotator in the historical set and no human review in
v2.6/v2.7; RAGTruth++ has no declared license and stays local-only; and cost is a computed upper
bound rather than a bill. Not implemented: streaming,
request caching, a batched cheaper mode, abstain/confidence output, non-English text.
