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

## Headline result (held-out test split, 20 cases / 61 claims, 3 runs)

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
selling point, and it costs ~4.7× the calls and ~3.5× the input tokens. Development-split tables, full
failure analysis and threats to validity: [docs/REPORT.md](docs/REPORT.md).

## Quickstart

```bash
uv sync                      # or: python -m venv .venv && pip install -e .
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

## How it is measured

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
optimized verifier is held-out-measured at 0.984 claim accuracy / 1.000 answer-level F1, oracle-perfect
at 1.000 (test split, 3 runs). Known open items: decomposition wording remains the binding constraint —
prompt v4 fixed half of it (coverage up, fusion halved) but broke the no-claims edge case and was
reverted, with its successor's keep-condition written down; one annotator; and cost reported as a
computed upper bound rather than a bill. Not implemented: streaming, request caching, a
batched cheaper mode, abstain/confidence output, non-English text.
