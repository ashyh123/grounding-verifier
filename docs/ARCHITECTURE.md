# Architecture

How `POST /verify` turns an untrusted answer into a validated report, and where the trust boundary
sits. Companion documents: [EVALUATION.md](EVALUATION.md) (harness and metrics), [REPORT.md](REPORT.md)
(measured results), [ITERATIONS.md](ITERATIONS.md) (the development log), [DATASET.md](DATASET.md).

## Request flow

```
POST /verify?method=baseline|minimal|optimized&include_meta=true|false
  │
  ├─ schemas.VerifyRequest          Pydantic: rejects unknown fields, caps sizes
  │
  ├─ api.get_verifier(method)       built once per process and cached
  │
  ├─ verifier.verify(req)           ── three interchangeable implementations ─────────────┐
  │     baseline   : sentence split → BM25 best sentence → lexical heuristics (no LLM)   │
  │     minimal    : ONE call with answer + all passages (MINIMAL_SYSTEM_V1)             │
  │     optimized  : decompose → verify each claim in parallel → repair → retry if bad   │
  │                                                                                       │
  ├─ validate.check_response_invariants(passages, claims)   ← last net before returning   │
  │     violations are impossible by construction; if one appears the request fails 500    │
  │                                                                                       │
  └─ response (meta stripped unless include_meta=true)                                   │
                                                                                          │
Every citation in the response was REBUILT from the passage text ────────────────────────┘
```

## Components

| Module | Responsibility |
|---|---|
| `verifier/api.py` | HTTP layer only: routing, query params, error→status mapping. Holds no verification logic. |
| `verifier/schemas.py` | Request/response contract and limits: ≤50 passages, ≤20 000 chars each, answer ≤10 000 chars, `Meta` accounting fields. |
| `verifier/baseline.py` | Non-LLM baseline: BM25 ranking + 60 % content-word overlap, negation-mismatch and number-mismatch heuristics. |
| `verifier/llm_verifiers.py` | `MinimalVerifier` (one call) and `OptimizedVerifier` (decompose → per-claim verify, 5 in parallel, ≤2 repair retries). |
| `verifier/prompts.py` | Every prompt, versioned and frozen. `PROMPT_SETS` maps `v1…v4` → (decompose prompt, verify prompt, decomposition schema). |
| `verifier/llm.py` | `LLMClient` protocol, `AnthropicClient`, usage accounting, retry policy, `build_client()` provider switch. |
| `verifier/openai_client.py` | `OpenAIChatClient`: any OpenAI-compatible `/chat/completions` endpoint, same forced-tool-call contract. |
| `verifier/validate.py` | The trust boundary: quote resolution (exact → normalised → fuzzy), citation repair, verdict invariants, the final net. |
| `verifier/segment.py` | Sentence splitting that preserves exact character offsets; `P{passage}.S{index}` IDs; the numbered rendering handed to the model. |
| `verifier/config.py` | Settings: loads `.env` once at import, resolves provider/model/key/base-URL precedence, extra request body. |

## The trust boundary

The model is treated as an unreliable narrator about its own citations. Concretely:

1. **Nothing the model says about a citation is trusted.** `validate.resolve_citation` looks the quote up
   in the passage:
   * exact substring → `exact`
   * after NFKC + lowercase + quote/dash unification + whitespace collapse → `normalized`
   * fuzzy `partial_ratio ≥ 95` with word-boundary snapping → `fuzzy` (quotes shorter than 8 chars are
     never fuzzy-matched — too ambiguous)
   Sentence-ID citations resolve to that sentence's exact span, or to the quoted sub-span inside it.
   A wrong or missing passage index triggers a search across all passages (`relocated`).
2. **The response always contains `passages[index][start:end]`, never a model-authored string.**
   `_make()` re-slices the passage, so `quote`, `start_char` and `end_char` agree by construction.
3. **Invariants are enforced, not assumed** (`finalize_claim`): `UNSUPPORTED` carries no citations;
   a `SUPPORTED`/`CONTRADICTED` verdict without a single resolvable citation is **downgraded to
   UNSUPPORTED** with a warning; an unknown verdict string becomes UNSUPPORTED.
   `check_response_invariants` re-checks the finished claims in the HTTP layer — a violation there is a
   500, never a silently invalid report.
4. **The model's sloppiness is measured, not hidden.** `meta.raw_citations_total` and
   `meta.raw_citations_invalid` count citations *before* repair, so the eval can report how often the
   model got it wrong while the client still returned a valid report.

The design bias is **fail closed**: an unbacked claim is reported as UNSUPPORTED rather than asserted.

## Error handling and retries

| Condition | Behaviour |
|---|---|
| Schema violation, unknown field, bad `method` | `422 invalid_request` |
| Provider 4xx other than 429 | `UpstreamError` → `502 upstream_error` (no retry: retrying a rejected request wastes budget) |
| Provider 429 / 5xx / connection / timeout | retried with backoff `min(2^attempt, 20)`s, up to `VERIFIER_MAX_RETRIES` (default 3); still failing → `502`, timeouts → `504 upstream_error` |
| Model returns no tool call (truncated, off-schema) | treated as a retryable malformed response, not a crash |
| Function arguments are not valid JSON | retried; `json.loads(strict=False)` fallback absorbs stray control characters |
| Missing `VERIFIER_MODEL` or API key | `500 misconfigured` naming the setting (API); a clear exit message in the eval CLI |
| Invariant violation at the edge | `500 internal_invariant_violation` (should be unreachable) |

`usage.calls` counts **billed** responses; `usage.retries` counts every rate-limit, transport or
malformed-output retry separately, and the report prints calls per case — an architecture that looks
cheap is not allowed to hide retry traffic. In the optimized verifier the two are distinct too: one
decompose call plus one per claim, plus any repair retry (measured: 4.5 calls/case on dev).

## Edge cases, by design

| Input | Behaviour |
|---|---|
| No passages | every claim is UNSUPPORTED without any LLM call (nothing can be grounded) |
| Answer with no factual claims | `claims: []`; the decomposition prompt is told to return an empty list rather than invent one |
| Empty answer | `claims: []` immediately |
| Very long input | rejected at 422 by the schema limits before any spend |
| Duplicate citations | de-duplicated by `(index, start, end)` before returning |
| Claim with several supporting sentences | supported: every accepted citation is returned, order preserved |

## Prompt versioning

`PROMPT_SETS` in `verifier/prompts.py` holds immutable prompt versions; **an old version is never
edited** — a change is a new entry. `VERIFIER_PROMPT_VERSION` selects the set used by the optimized
verifier (default `v3`, the version that won on dev), and every response records it in
`meta.prompt_version`, so any artifact in `results/` can be traced back to the exact prompts that
produced it. v4 also carries its own decomposition schema (a `sentences[] → claims[]` coverage mapping),
which is why `PromptSet` includes the schema and not just the text. The minimal verifier is deliberately
frozen at `MINIMAL_SYSTEM_V1`: it is the control condition for the comparison.

## Configuration resolution

`verifier/config.py` loads `./.env` once at import (`VERIFIER_ENV_FILE` can point elsewhere) with
`override=False`, so **real environment variables always win**. Precedence for the endpoint is
provider-specific first, generic second:

| Setting | anthropic path | openai path |
|---|---|---|
| key | `VERIFIER_API_KEY` → `ANTHROPIC_API_KEY` (or `ANTHROPIC_AUTH_TOKEN`) | `VERIFIER_API_KEY` → `DEEPSEEK_API_KEY` → `OPENAI_API_KEY` |
| base URL | `ANTHROPIC_BASE_URL` → `VERIFIER_BASE_URL` | `OPENAI_BASE_URL` → `VERIFIER_BASE_URL` → guessed from the key present |
| model | `VERIFIER_MODEL` (required, shared by both paths) | same |
| extra request fields | `VERIFIER_EXTRA_BODY` merged as `extra_body` | `VERIFIER_EXTRA_BODY` merged into the JSON body, last |

Two compatibility rules worth knowing, both learned from live traffic (see
[ITERATIONS.md](ITERATIONS.md#findings-from-pointing-the-clients-at-a-live-provider)):

* Sampling is pinned to `temperature=0` for reproducibility. Recent `anthropic` SDKs removed the typed
  parameter, so it is sent through `extra_body` when the signature no longer accepts it.
* Input token accounting sums `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`,
  because Anthropic-style usage keeps cached prefix tokens out of `input_tokens` (a 12× undercount in
  the cost column otherwise).

`GET /health` reports provider, model, prompt version, whether a key and base URL were found, and which
env file was loaded — no secrets.

## Extending it

| To add | Touch |
|---|---|
| a verifier method | a class with `verify()`/`verify_claims()` in a new module, one branch in `api.get_verifier` and `eval.run.build`, add to the `method` enum |
| a prompt iteration | new `*_SYSTEM_V5` constant + a `PromptSet` entry; nobody's old run changes meaning |
| a metric | counter in `eval/metrics.compute`, one row in `eval/report.ROWS`, then `--rescore` existing runs instead of re-paying for them |
| a provider | implement the `LLMClient` protocol (one method: `call_tool`), add a branch to `build_client()` and a key/env row in `.env.example` |
