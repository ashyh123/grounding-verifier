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

Three implementations are benchmarked on one 46-case / 150-claim dataset: a non-LLM lexical baseline,
a minimal single-call LLM verifier, and an optimized multi-step pipeline.

> **Documentation v2** (2026-10-17) — index, revision record and conventions in
> [docs/README.md](docs/README.md).

## Current headline: RAGTruth v2.5 (unmeasured)

The current benchmark is `data/eval_hard.v2.5.jsonl`, with `all` as the headline and
`natural` alongside it; `conflict_supplement` and `subtle_supplement` are reported separately.
All-data and natural hallucination-detection P/R/F1 and macro-F1 are **not yet measured**.
The scoring entry includes 95% case-bootstrap intervals (10000 draws, seed 20261020),
per-label n, a preregistered sensitivity analysis that removes claims whose `doubt_category`
is `suspected_wrong_label` or `c_vs_u_boundary`, and evident/subtle and generator-model groups.
Dataset counts: all 案例=63、主张=782 (S701/C37/U44); natural 案例=30、主张=382
(S341/C7/U34); conflict_supplement 20 例 / 256 主张; subtle_supplement 13 例 / 144 主张.
Within held-out test: all 案例=45、主张=537 (S483/C27/U27), natural 案例=20、主张=256
(S235/C4/U17). These are label counts, not verifier scores.
See [dataset statistics](data/annotation/v2.5/final_report.md) and
[preregistered scoring rules](docs/EVALUATION.md). No hard-test verifier ran in this revision.
The v2.5 target of at least 8 test CONTRADICTED claims from Subtle Conflict fragments was
**not met** (7 retained); no cases were added or rules relaxed.

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

Every change was measured on the dev split (26 cases / 89 claims, 3 runs) before it was kept; the test split was run once, with v3 frozen. Full log: docs/ITERATIONS.md.

- **minimal** (control, never edited): one call does decomposition and verification. Dev claim accuracy 0.989, macro-F1 0.983.
- **v1 — kept as the architecture.** Decompose, then verify each claim in its own call against numbered source sentences, with retry on invalid citations. Macro-F1 rose to 0.991 and answer-level F1 to 1.000, but claim accuracy dipped to 0.981: the decomposition step was rewording claims.
- **v2 — reverted.** Changed the decomposition *and* verification prompts at once; macro-F1 fell to 0.954 (UNSUPPORTED F1 0.900) and the regression could not be attributed to either change. Lesson: one change per iteration.
- **v3 — kept, frozen for the test run.** Decomposition only: copy every qualifier and trailing clause verbatim. It fixed `redis-cluster-long-31`, where a unit error had been trimmed away before verification. Dev 0.989 / macro-F1 0.997 with zero run-to-run variance.
- **v4 — reverted.** A sentence-coverage pass halved fused claims (0.043 → 0.022), but it made the model invent a claim on the no-claims case `no-claims-17` (answer-level F1 1.000 → 0.980) and raised cost from $0.0080 to $0.0087 per case and p50 latency from 4657 to 5749 ms. Its motivating example came from the test split, which is disclosed in the log.
- **A metric bug found on the way:** the fused-claim metric gave the sentence-splitting baseline, which cannot fuse, 0.113. It was rewritten to use distinctive content words (baseline now 0.000) before any decision relied on it.

## Key failure cases (held-out test split)

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
| audit the 46 cases and their labels | [docs/DATASET.md](docs/DATASET.md) |
| see what was tried, kept and reverted (prompt v1→v4, models) | [docs/ITERATIONS.md](docs/ITERATIONS.md) |
| know what changed in this documentation revision | [docs/README.md](docs/README.md) |

## Status

Working and verified end to end against a live provider on both client transports; the suite is green
(`make test`, no key required — it includes the eval-harness and documentation-consistency checks); the
optimized verifier on the historical synthetic dataset is held-out-measured at 0.984 claim accuracy / 1.000 answer-level F1, oracle-perfect
at 1.000 (test split, 3 runs). Known open items: decomposition wording remains the binding constraint —
prompt v4 fixed half of it (coverage up, fusion halved) but broke the no-claims edge case and was
reverted, with its successor's keep-condition written down; one annotator; and cost reported as a
computed upper bound rather than a bill. Not implemented: streaming, request caching, a
batched cheaper mode, abstain/confidence output, non-English text.
