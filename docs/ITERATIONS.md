# Hill-climbing log (dev split only)

This is the **chronological record**: what was changed, what it measured at the moment of the decision,
and whether it was kept. Each entry keeps the numbers it saw at the time, including reverted ones. For
the current summaries — one table per split, regenerated from `results/*/summary.json` — read
[REPORT.md](REPORT.md); for what each metric means, [EVALUATION.md](EVALUATION.md).

Protocol: change **one** thing per iteration, measure on `dev` (26 cases / 89 gold claims), read the
failure list, decide keep/revert. `test` (20 cases / 61 claims) is read once at the end by
`make eval-test`. Every row is reproducible with the commands in [Runbook](#runbook).

Provider for all LLM rows: `deepseek-v4-pro` with `VERIFIER_EXTRA_BODY={"thinking":{"type":"disabled"}}`
(thinking mode rejects the forced tool call the client contract requires). 3 runs each unless noted.

## Summary

| Version | Change (one thing) | Failure it targets | dev claim acc | dev macro-F1 | dev answer F1 | dev cit. precision | calls/case | Kept? |
|---|---|---|---|---|---|---|---|---|
| baseline | non-LLM: BM25 + lexical overlap + negation/number heuristics | — | 0.382 | 0.411 | 0.980 | 0.885 | 0.00 | reference floor |
| minimal | single call, `MINIMAL_SYSTEM_V1`, no repair, no retry | — | **0.989 ± 0.009** | 0.983 ± 0.013 | 0.987 ± 0.009 | 0.976 ± 0.010 | 1.00 | comparison point |
| v1 | `OptimizedVerifier`: decompose → per-claim verify in parallel → deterministic repair → retry with feedback | — | 0.981 ± 0.005 | 0.991 ± 0.004 | **1.000 ± 0.000** | 0.882 ± 0.016 | 4.68 | superseded by v3 |
| v2 | prompt set V2: verification checklist + aggressive split rules | UNSUPPORTED/CONTRADICTED boundary; number/unit, condition, quantifier traps | 0.966 | 0.954 | 1.000 | 0.898 | 4.58 | **reverted** |
| v3 | decomposition only: keep every qualifier and trailing clause verbatim | `redis-cluster-long-31` (clause trimmed), `jwt-claims-14` (clause lost) | **0.989 ± 0.000** | **0.997 ± 0.000** | **1.000 ± 0.000** | 0.870 ± 0.008 | 4.53 | **kept — default** |
| v4 | v3 + a sentence-coverage pass and an explicit no-fusion rule (`DECOMPOSE_SCHEMA_V2`) | `pg-checkpoint-20` (test — see protocol note), `jwt-claims-14` (clause lost) | 0.989 ± 0.000 | 0.997 ± 0.000 | 0.980 ± 0.000 | 0.867 ± 0.009 | 4.50 | **reverted** |

Full dev table, all metrics, every version: [dev comparison](#full-dev-comparison).

## baseline (non-LLM floor) — measured

Command: `uv run python -m eval.run --methods baseline --split dev --out results/dev-baseline`

Observed failure mode (`--failures baseline`): the baseline **under-commits**. BM25 plus a 60 %
content-word overlap threshold labels a paraphrased but well-supported claim UNSUPPORTED
("covers only 27 % of the claim's content words"), so the distortions it is supposed to catch
(`sqlite-wal-01` NFS negation, `redis-aof-02` 2 s vs 1 s, `py-asyncio-04` completion order,
`k8s-probes-06` probe swap) are returned as UNSUPPORTED instead of CONTRADICTED. Its number and
negation heuristics only fire when the claim is nearly verbatim already
(`docker-exit-05`, `systemd-restart-11`).

Two metric readings are worth reading together with that: its `citation_precision` (0.885) and
`citation_precision_passage` (1.000) are *high* precisely because it cites rarely — a low-recall,
high-precision citer. And its answer-level F1 (0.980) is an artifact of a case mix in which almost
every answer contains at least one distorted claim: "flag everything" scores well at answer level
while being wrong claim by claim. That is why the report leads with claim accuracy and macro-F1.

## minimal — measured

- **Hypothesis:** one call with `MINIMAL_SYSTEM_V1` fixes the baseline's under-commitment (the model
  can read that "does not work over NFS" contradicts "works over NFS"), but loses on decomposition
  detail and citation validity because the whole answer and all passages share one response.
- **Change:** none, by definition — the untuned single call.
- **Result:** 0.989 ± 0.009 claim accuracy, macro-F1 0.983, answer F1 0.987, 1.00 calls/case,
  p50 3.6 s, ~681 input / 372 output tokens per case. Decomposition recall **1.000 ± 0.000**,
  citation precision 0.976 (best of all methods).
- **Failures:** one `MISSED` gold claim on `kafka-partitions-10` (it merged "partition count can be
  increased" into a neighbouring claim).
- **Decision:** kept as the comparison point. It is the number to beat, and it is not beaten on
  claim accuracy by anything else in this log.

## v1 — measured

- **Hypothesis:** atomic decomposition + one claim per call + sentence-ID citations with deterministic
  repair + retry-with-feedback should beat the single call on claim accuracy and citation validity,
  at ~1 extra call per claim.
- **Change:** `OptimizedVerifier` with `DECOMPOSE_SYSTEM_V1` / `VERIFY_SYSTEM_V1`, `MAX_REPAIR_RETRIES=2`.
- **Command:** `uv run python -m eval.run --methods optimized --split dev --runs 3 --prompt-version v1 --out results/dev-v1-x3`
- **Result:** 0.981 ± 0.005 claim accuracy, **macro-F1 0.991 ± 0.004**, answer F1 **1.000 ± 0.000**,
  4.68 calls/case, p50 4.8 s, ~4034 input / 690 output tokens per case.
- **Failures fixed vs minimal:** answer-level detection is perfect (1.000 vs 0.987) and every
  UNSUPPORTED claim is labelled correctly (F1 1.000 vs 0.968); the UNSUPPORTED/CONTRADICTED boundary
  error that `minimal` makes on `pg-autovacuum-tuning-23` (a wrong default labelled UNSUPPORTED
  instead of CONTRADICTED) does not happen per-claim.
- **New failures:** two `MISSED` gold claims caused by the decomposition step itself —
  `jwt-claims-14` (the clock-skew clause was dropped) and, in an earlier revision,
  `redis-cluster-long-31`, where the decomposed claim was trimmed to
  "The latency monitor records events slower than latency-monitor-threshold." — dropping the
  "which is given in seconds" that carried the unit error. **The verifier then correctly supported a
  claim whose distortion had been deleted before verification.**
- **Decision:** keep as the architecture, but the measured gap to `minimal` is negative on claim
  accuracy, so the next iteration targets the actual observed defect (decomposition) instead of the
  architecture.

## v2 — measured, reverted

- **Hypothesis:** the remaining errors are judgement errors inside one verification call, so an
  explicit checklist (numbers and units, conditions, quantifiers, entity, "never UNSUPPORTED when a
  source contradicts") plus a reworked decomposition prompt should fix them.
- **Change:** prompts only — `VERIFY_SYSTEM_V2` + `DECOMPOSE_SYSTEM_V2`, same model, same code.
- **Command:** `uv run python -m eval.run --methods optimized --split dev --runs 1 --prompt-version v2 --out results/dev-v2`
- **Result:** 0.966 claim accuracy, macro-F1 0.954, answer F1 1.000, 4.58 calls/case — **worse than v1
  on both headline metrics** (−1.5 pt claim accuracy, −3.7 pt macro-F1).
- **Failures fixed / new failures:** nothing fixed that v1 was getting wrong; the UNSUPPORTED F1
  dropped to 0.900 (v1: 1.000), i.e. the extra instruction weight pushed borderline cases toward
  CONTRADICTED. Two things changed at once (verification prompt *and* decomposition prompt), so the
  regression cannot be attributed to one of them — which is itself the lesson.
- **Decision:** **reverted.** v2 stays in the repository for reproducibility but is not the default.
  The next iteration changes only the decomposition prompt.

## v3 — measured, kept as default

- **Hypothesis (from v1's failures):** the pipeline's residual error is *decomposition*, not
  verification — specifically, the decompose step trims trailing and subordinate clauses, and a
  trimmed clause can carry the very distortion that should be caught.
- **Change:** decomposition prompt only, `DECOMPOSE_SYSTEM_V3`; `VERIFY_SYSTEM_V1` unchanged. Rule:
  every qualifier and trailing/subordinate clause is copied character for character, with examples
  (", which is given in seconds", "even after the partition count changes", "regardless of whether it
  has an expiry set"), and "a clause you drop is a fact the checker can no longer see".
- **Command:** `uv run python -m eval.run --methods optimized --split dev --runs 3 --prompt-version v3 --out results/dev-v3-x3`
- **Result:** **0.989 ± 0.000 claim accuracy, 0.997 ± 0.000 macro-F1, 1.000 ± 0.000 answer F1**,
  4.53 calls/case. Identical across all three runs.
- **Failures fixed:** the `redis-cluster-long-31` unit-clause loss is gone; claim accuracy +0.8 pt and
  macro-F1 +0.6 pt over v1, with zero run-to-run variance.
- **New failures:** `jwt-claims-14` still loses the clock-skew clause (a subordinate clause about
  clock skew is still merged into the exp claim). UNSUPPORTED F1 1.000, CONTRADICTED F1 1.000.
- **Decision:** **kept.** `DEFAULT_PROMPT_VERSION = "v3"` and `.env` sets `VERIFIER_PROMPT_VERSION=v3`.
- **Honest reading:** v3 ties `minimal` on claim accuracy (0.989 both) and wins on macro-F1
  (0.997 vs 0.983) and answer F1 (1.000 vs 0.987) for 4.5× the calls. On this benchmark and this
  model, the architecture's advantage is the verdict boundary and answer-level detection, not the
  average claim.

## Full dev comparison

26 cases / 89 claims, `deepseek-v4-pro` (thinking disabled), mean ± std over 3 runs where applicable.

| Metric | baseline | minimal | opt v1 | opt v2 | opt v3 | opt v4 |
|---|---|---|---|---|---|---|
| Answer-level hallucination F1 | 0.980 | 0.987 ± 0.009 | 1.000 ± 0.000 | 1.000 | 1.000 ± 0.000 | 0.980 ± 0.000 |
| Claim accuracy (all gold claims) | 0.382 | **0.989 ± 0.009** | 0.981 ± 0.005 | 0.966 | **0.989 ± 0.000** | **0.989 ± 0.000** |
| Claim accuracy (matched only) | 0.493 | 0.989 ± 0.009 | 0.992 ± 0.005 | 0.977 | 1.000 ± 0.000 | 1.000 ± 0.000 |
| Macro-F1 (3 verdicts) | 0.411 | 0.983 ± 0.013 | 0.991 ± 0.004 | 0.954 | **0.997 ± 0.000** | **0.997 ± 0.000** |
| F1 SUPPORTED | 0.551 | 0.997 ± 0.005 | 0.983 ± 0.005 | 0.979 | 0.990 ± 0.000 | 0.990 ± 0.000 |
| F1 CONTRADICTED | 0.368 | 0.983 ± 0.014 | 0.989 ± 0.008 | 0.984 | 1.000 ± 0.000 | 1.000 ± 0.000 |
| F1 UNSUPPORTED | 0.314 | 0.968 ± 0.022 | 1.000 ± 0.000 | 0.900 | 1.000 ± 0.000 | 1.000 ± 0.000 |
| Decomposition recall | 0.775 | 1.000 ± 0.000 | 0.989 ± 0.000 | 0.989 | 0.989 ± 0.000 | 0.989 ± 0.000 |
| Decomposition precision | 0.972 | 0.934 ± 0.009 | 0.901 ± 0.019 | 0.926 | 0.940 ± 0.005 | 0.946 ± 0.000 |
| Answer sentence coverage | 1.000 | 0.981 ± 0.007 | 0.972 ± 0.000 | 0.972 | 0.972 ± 0.000 | 0.986 ± 0.000 |
| Fused claims (claim carries distinctive words from ≥2 sentences) | 0.000 | 0.000 ± 0.000 | 0.041 ± 0.001 | 0.042 | 0.043 ± 0.000 | 0.022 ± 0.000 |
| Citation precision | 0.885 | 0.976 ± 0.010 | 0.882 ± 0.016 | 0.898 | 0.870 ± 0.008 | 0.867 ± 0.009 |
| Citation recall | 0.885 | 0.996 ± 0.006 | 0.966 ± 0.006 | 0.962 | 0.963 ± 0.000 | 0.963 ± 0.000 |
| Citation precision (right passage) | 1.000 | 0.988 ± 0.000 | 0.956 ± 0.008 | 0.966 | 0.957 ± 0.008 | 0.957 ± 0.008 |
| Citation recall (right passage) | 1.000 | 1.000 ± 0.000 | 1.000 ± 0.000 | 1.000 | 1.000 ± 0.000 | 1.000 ± 0.000 |
| Raw citation invalid rate (before repair) | 0.000 | 0.008 ± 0.005 | 0.003 ± 0.005 | 0.000 | 0.000 ± 0.000 | 0.010 ± 0.000 |
| Latency p50 / p95 (ms) | 0.14 / 0.30 | 3645 / 5353 | 4814 / 5858 | 5154 / 7295 | 4657 / 6003 | 5749 / 7541 |
| Input / output tokens per case | 0 / 0 | 681 / 372 | 4034 / 690 | 4794 / 671 | 4022 / 669 | 4095 / 823 |
| LLM calls / case | 0.00 | 1.00 ± 0.00 | 4.68 ± 0.08 | 4.58 | 4.53 ± 0.02 | 4.50 ± 0.00 |
| Cost / case (USD) | 0.0000 | 0.0024 ± 0.0000 | 0.0081 ± 0.0002 | 0.0090 | 0.0080 ± 0.0000 | 0.0087 ± 0.0000 |
| Errored cases | 0 | 0 ± 0 | 0 ± 0 | 0 | 0 ± 0 | 0 ± 0 |

Reading notes, because two of these metrics are easy to misread:

* **Citation precision is annotator-strict.** It credits a citation only when it overlaps the
  annotated gold span. A per-sentence verifier cites *the sentence it reasoned from*, which for a
  multi-sentence fact is often a different sentence of the same passage — hence 0.87 for the
  optimized path against 0.98 for the single call, which quotes the salient phrase. The
  **right-passage** row is the same question with the annotation taste removed (0.957 vs 0.988), and
  the residual gap is real but small: 4 % of the optimized path's citations point at a passage the
  annotation did not choose.
* **Decomposition precision below 1 is not an error.** Both LLM methods emit slightly more claims
  than the reference (splitting "A and B" into two claims, as the contract instructs); alignment
  matches one, the sibling counts as a precision loss. `minimal` scores higher here only because it
  tends to keep a sentence together.

## Oracle runs: where the error actually is

`--oracle` feeds the gold claims in and skips decomposition, isolating verification from
decomposition. dev, 1 run, same model:

| Method | claim accuracy | macro-F1 | citation precision | citation precision (right passage) | calls/case |
|---|---|---|---|---|---|
| baseline | 0.494 | 0.454 | 0.943 | 1.000 | 0.00 |
| minimal | **1.000** | **1.000** | 0.953 | 0.965 | 1.00 |
| optimized v3 | **1.000** | **1.000** | 0.871 | 0.946 | 3.35 |

This is the log's most useful result:

* For LLM verifiers **verification is solved** on this dataset (1.000 with gold claims, both
  architectures). The entire end-to-end error budget (0.989) comes from **decomposition** — which
  claims the system chooses to check and how it words them.
* For the **baseline** it is the other way round: its bottleneck is verification (0.494 oracle, i.e.
  lexical matching cannot decide entailment), while its sentence splitter already recovers 0.775 of
  the gold claims. More decomposition work would not have helped it; more NLI would.
* Practical consequence: the cheapest way to raise this system's accuracy is to make decomposition
  more faithful (v3 did exactly that, +0.8 pt), not to make verification smarter.

## Model selection (dev A/B, before the final test run)

Same prompt set, two models on the same dev split (26 cases / 89 claims). `deepseek-v4-pro` requires
`{"thinking":{"type":"disabled"}}`; without it the endpoint answers
`400 Thinking mode does not support this tool_choice`, which is why the client exposes
`VERIFIER_EXTRA_BODY` at all.

| Run | Model | Method | dev claim acc | macro-F1 | calls/case | errors |
|---|---|---|---|---|---|---|
| `results/dev-flashcheck` | `deepseek-chat` (flash) | minimal | 0.978 | 0.975 | 1.00 | 0 |
| `results/dev-flashcheck` | `deepseek-chat` (flash) | optimized v1 | 0.978 | 0.988 | 4.77 | 0 |
| earlier single run | `deepseek-chat` (flash) | minimal | 0.989 | 0.978 | 1.00 | 0 |
| earlier single run | `deepseek-chat` (flash) | optimized v1 | 0.921 | 0.953 | 4.46 | 1 |
| `results/dev-minimal-x3` | `deepseek-v4-pro` | minimal | 0.989 ± 0.009 | 0.983 | 1.00 | 0 |
| `results/dev-v1-x3` | `deepseek-v4-pro` | optimized v1 | 0.981 ± 0.005 | 0.991 | 4.68 | 0 |

**The A/B did not reproduce, and that is the finding.** The first flash run put the pipeline 6.8 pt
below the single call; the repeat put it level with it. On 89 claims, one run per cell cannot separate
models whose difference is a handful of claims — which is exactly why the headline comparisons in this
log use 3 runs and report std. The honest reading is that the cheap model is **within run-to-run noise
of the expensive one on dev for both methods**, and `deepseek-v4-pro` was pinned for the final run on
the strength of the repeated v1/v3 measurements (0.981 ± 0.005 and 0.989 ± 0.000), not on the A/B.

The one real artifact from the first flash run survives as a robustness fix. A case failed with
`LLM unavailable after retries: unparseable response: Expecting value: line 1 column 85`, i.e. the
model returned function arguments that were not valid JSON; the client retried twice and reported the
case as an upstream error, which is the correct behaviour (fail loudly rather than return a partial
report). `_parse_arguments` now falls back to `json.loads(strict=False)` for that defect class (raw
control characters inside strings), with a regression test carrying such a payload. It has not
recurred in the runs since, so it is hardening, not a measured improvement.

## Dataset calibration (also eval-driven)

The first revision of the dataset was **saturated**: all three methods scored 0.96–0.98 and could not
be told apart. Three corrections came out of the eval rather than from review:

1. **Bundled gold claims.** 8 gold claims joined two facts ("X can be increased and can also be
   decreased") with one verdict. That punished the optimized path for splitting claims exactly as its
   prompt instructs, and it made a mixed claim (one half true, one half false) a coin flip. The
   reference is now atomic.
2. **A wrong label.** `kafka-partitions-10` had "Records with the same key stay ordered within their
   partition even after the partition count changes" as SUPPORTED. Both verifiers rejected it and both
   were right — the sources say the key-to-partition assignment changes with the partition count.
   Relabelled CONTRADICTED.
3. **A harder half.** 17 cases with distractor sentences, parameter soup, clauses that invert scope,
   and one long-context case (9 passages, 11 claims) were added, then 8 more test cases to keep the
   held-out split as large as dev. This is what moved `minimal` from 0.96 to 0.989 and made the
   differences above measurable at all.

The final run then surfaced two more contested labels, both fixed and both recorded in the case
notes: `kafka-retention-11` (the answer said segments are "deleted" where the source says "eligible
for deletion" — the verifiers were right, the answer was reworded) and `http-retry-21` (a universal
claim that the sources arguably implied false; replaced with a claim they are simply silent about).
`prometheus-counter-17` was **not** changed: `minimal` labels a dropped "except when the process
restarts" exception as SUPPORTED, which is the case's whole point.

## v4 — measured, reverted

- **Hypothesis (written down before the run, in the v3 section of the previous revision):** the
  pipeline's residual defect is decomposition *wording* — specifically fusion, where one claim is
  built from clauses of two sentences (`pg-checkpoint-20`, a test case: "writes a checkpoint record" +
  "Checkpoints shorten crash recovery" → "A checkpoint **record** shortens crash recovery"). Fix: make
  the decomposition account for every answer sentence, so a dropped or fused sentence becomes visible
  instead of silent.
- **Protocol note:** the fusion example that motivated v4 (`pg-checkpoint-20`) is a *test* case, seen in
  the final run's failure list; `jwt-claims-14` is the dev case of the same defect class. Choosing a
  target from the test split breaks the dev-only rule. Mitigations: v4 was measured on dev only, it was
  reverted, and the test split was not re-run, so no reported test number depends on it.
- **Change:** `DECOMPOSE_SYSTEM_V4` + `DECOMPOSE_SCHEMA_V2` (a `sentences[] → claims[]` mapping that
  v1–v3 do not have), `VERIFY_SYSTEM_V1` unchanged. Two new metrics test the hypothesis directly:
  **answer sentence coverage** (share of answer sentences matched by some claim) and **fused claim
  rate** (share of claims matching two or more answer sentences).
- **Command:** `uv run python -m eval.run --methods optimized --split dev --runs 3 --prompt-version v4 --out results/dev-v4-x3`
- **Result:** claim accuracy 0.989 ± 0.000 and macro-F1 0.997 ± 0.000 — level with v3 — but
  answer-level F1 **0.980 ± 0.000 against v3's 1.000 ± 0.000**, latency p50 5749 ms against v3's
  4657 ms, cost $0.0087 against $0.0080 per case, raw citation invalid rate 0.010 against 0.000.
- **Did the hypothesis hold?** Yes on both instruments it was aimed at: sentence coverage rose as
  intended (0.972 → 0.986), and the fused-claim rate **halved** (0.043 → 0.022) once the metric was
  corrected. The original reading of this run ("fusion got worse, 0.096 → 0.108") was an artifact of a
  metric with a ~11 % false-positive floor — see the fusion-metric note below.
- **The regression, located:** `no-claims-17` — the conversational answer with no factual claims whose
  correct output is an empty list. v4's rule "do not skip a sentence; keep non-factual sentences with
  an empty claims array" made the model emit one UNSUPPORTED claim for the greeting, turning a true
  negative into a false positive and costing the run its perfect answer-level F1. The coverage
  instrument primed the exact behaviour that case exists to catch.
- **Failures fixed:** none; `jwt-claims-14` still loses the clock-skew clause.
- **Decision: reverted**, on evidence that does not depend on the corrected metric: `no-claims-17`
  went from the correct empty output to one fabricated UNSUPPORTED claim (answer-level F1 1.000 → 0.980),
  latency p50 4657 → 5749 ms and cost $0.0080 → $0.0087 per case, and the fusion improvement did not
  offset that regression. v4 stays in the
  repository (prompt set and schema) for reproducibility, and `DEFAULT_PROMPT_VERSION` remains `v3`, so
  the held-out final run did not need repeating. Its motivating example came from the test split; see the
  protocol note above.
- **Next candidate (v5):** v4's coverage instrument worked (coverage up, fusion halved) and only its
  priming of the no-claims case failed, so the successor is v4 plus one explicit exception — *a sentence
  with no factual content maps to an empty claim list and must not produce a claim*. Keep condition,
  measured on dev before anything else: `no-claims-17` must return an empty list again **and** the
  corrected fused-claim rate must stay at or below v4's 0.022.

## Fusion-metric correction (found by review, fixed without model calls)

The fused-claim metric originally asked "does this claim resemble two or more answer sentences?"
(`token_set_ratio >= 60`). The baseline, which splits the answer into sentences **verbatim** and
therefore cannot fuse anything, scored 0.113 on it — an ~11 % false-positive floor, because neighbouring
sentences share vocabulary. The v3 → v4 difference (0.096 → 0.108) sat inside that floor, so "v4 made
fusion worse" was never supportable.

The metric now decides on **distinctive** content words: a claim has fused two sentences when it carries
at least two words that belong to exactly one sentence each, for two different sentences. Measured on
the same saved predictions, no model calls:

| Result directory | fused claims, old metric | fused claims, corrected metric |
|---|---|---|
| `dev-baseline` (cannot fuse by construction) | 0.113 | **0.000** |
| `dev-minimal-x3` | 0.115 | **0.000** |
| `dev-v1-x3` | 0.096 | 0.041 |
| `dev-v3-x3` | 0.096 | 0.043 |
| `dev-v4-x3` | 0.108 | **0.022** |

Consequences, all recorded above in the v4 section: v4's coverage instrument measurably **worked**
(fusion halved), the revert rests only on the `no-claims-17` regression and the latency/cost increase,
and the v5 keep-condition is now stated against the corrected metric. A regression test
(`test_fusion_metric_has_no_false_positive_floor`) pins the baseline case at zero.

## Label audit (whole dataset, 150 claims)

The dataset has one annotator, which is its weakest property. As a partial check, every gold claim was
fed back through both verifiers in oracle mode and the verdicts compared with the reference labels:

| Reader | Agreement with the reference labels |
|---|---|
| optimized v3 | **149/150 = 0.993** |
| minimal | 147/150 = 0.980 |

Command: `uv run python -m eval.run --methods minimal optimized --split all --oracle --runs 1 --out results/label-audit`

* The single disagreement for the per-claim pipeline is `prometheus-counter-17`, the label deliberately
  kept against the model (a dropped "except when the process restarts" exception).
* Both readers agree with the three corrections made earlier (`kafka-partitions-10`,
  `kafka-retention-11`, `http-retry-21`), which is how those were surfaced in the first place.
* This is a **model-based read-back, not a second human annotator**: it can only find labels that a
  model sharing this training data also finds contestable, and it shares a family with the system under
  test. It raises confidence in the labels; it does not establish inter-annotator agreement.

## Findings from pointing the clients at a live provider

Three defects that no fake-based unit test could have caught, each found by aiming the code at a real
endpoint rather than at a scripted stub:

1. **The Anthropic client was broken against the installed SDK.** `anthropic` 1.15 no longer accepts
   `temperature` on `messages.create` (`TypeError: AsyncMessages.create() got an unexpected keyword
   argument 'temperature'`), so that entire path died on its first real call while its unit tests
   passed — they replace the SDK client wholesale. Fixed by detecting the typed parameter and
   otherwise passing `temperature: 0` through `extra_body`; `VERIFIER_EXTRA_BODY` is merged on this
   path too, because DeepSeek's Anthropic-compatible endpoint enforces the same
   "thinking mode does not support this tool_choice" rule. Verified with a real run:
   `VERIFIER_PROVIDER=anthropic ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic` scored
   0.989 / 0.997 / 1.000 on dev (`results/dev-anthropic-path`) — identical to the OpenAI-compatible
   path, which is what a transport swap should produce.
2. **Prompt-cache traffic was missing from the cost column on that path.** Anthropic-style usage keeps
   the cached prefix outside `input_tokens`: the run first reported 331 tokens/case for work that the
   other transport billed at 4033, i.e. it looked 12× cheaper. `_input_volume()` now sums
   `input_tokens`, `cache_read_input_tokens` and `cache_creation_input_tokens`, and the re-run
   reconciles the two transports exactly — 4033 / 669 tokens and $0.0080 per case on the Anthropic
   path against 4033 / 671 and $0.0080 on the OpenAI-compatible one, same 0.989 / 0.997 / 1.000.
   Cost comparisons are therefore valid within one transport, and the cache-miss price keeps the
   column an upper bound.
3. **A stale generic base URL could hijack a switched provider.** `VERIFIER_BASE_URL` (the OpenAI
   value) used to outrank `ANTHROPIC_BASE_URL`, so switching `VERIFIER_PROVIDER=anthropic` while
   leaving the openai block in `.env` silently sent Anthropic-format requests to the OpenAI endpoint.
   Precedence is now provider-specific first, generic second.

## Final held-out results

Run once with the frozen configuration (`VERIFIER_PROMPT_VERSION=v3`, `deepseek-v4-pro`, thinking
disabled), test split, 3 runs, `make eval-test`.

Before the label audit (first run of this evaluation):

| Method | claim acc | macro-F1 | answer F1 |
|---|---|---|---|
| baseline | 0.557 | 0.489 | 0.889 |
| minimal | 0.956 ± 0.008 | 0.922 ± 0.016 | 0.988 ± 0.017 |
| optimized v3 | 0.951 ± 0.000 | 0.913 ± 0.000 | 0.963 ± 0.000 |
| baseline (oracle) | 0.672 | 0.531 | 0.741 |
| minimal (oracle) | 0.951 ± 0.000 | 0.925 ± 0.000 | 0.963 |
| optimized v3 (oracle) | 0.967 ± 0.000 | 0.942 ± 0.000 | 0.963 |

After the two label corrections (`kafka-retention-11`, `http-retry-21`) and the re-run:

| Metric | baseline | minimal | optimized v3 |
|---|---|---|---|
| Answer-level hallucination F1 | 0.889 | 1.000 ± 0.000 | 1.000 ± 0.000 |
| Claim accuracy (all gold claims) | 0.590 | 0.984 ± 0.000 | 0.984 ± 0.000 |
| Macro-F1 (3 verdicts) | 0.528 | **0.983 ± 0.000** | 0.970 ± 0.000 |
| F1 SUPPORTED / CONTRADICTED / UNSUPPORTED | 0.778 / 0.353 / 0.455 | 0.988 / 0.960 / 1.000 | 0.988 / 1.000 / 0.923 |
| Decomposition recall / precision | 0.820 / 0.980 | 1.000 / 0.884 | 1.000 / 0.803 |
| Citation precision / recall (right passage) | 0.968 / 0.968 | 1.000 / 0.982 | 0.983 / 0.982 |
| Latency p50 / p95 (ms) | 0.15 / 0.19 | 3521 / 4649 | 4791 / 7956 |
| Input / output tokens per case | 0 / 0 | 647 / 332 | 3894 / 661 |
| Cost / case (USD, prices below) | 0.000000 | 0.002168 | 0.007745 |
| LLM calls / case | 0.00 | 1.00 ± 0.00 | 4.70 ± 0.00 |
| Errored cases | 0 | 0 ± 0 | 0 ± 0 |

Oracle, after the corrections:

| Metric | baseline | minimal | optimized v3 |
|---|---|---|---|
| Claim accuracy (all gold claims) | 0.705 | 0.978 ± 0.008 | **1.000 ± 0.000** |
| Macro-F1 (3 verdicts) | 0.569 | 0.969 ± 0.020 | **1.000 ± 0.000** |
| Citation precision (right passage) | 1.000 | 0.994 ± 0.009 | **1.000 ± 0.000** |
| Latency p50 (ms) | 0.1 | 3541 | **3001** |
| Input tokens per case | 0 | 666 | 2555 |
| LLM calls / case | 0.00 | 1.00 ± 0.00 | 2.95 ± 0.00 |

Decisions recorded from the final run:

* **The architecture's advantage is in verification, and it is real but narrow.** With gold claims
  fed in, the pipeline is perfect (1.000 / 1.000, 3 runs) while the single call errs twice
  (`prometheus-counter-17`: reads "except when the process restarts" and still calls an absolute
  "never decrease" entailed; `http-retry-21`: calls an over-claim CONTRADICTED while its own reasoning
  says the passage is silent). End-to-end the two tie at 0.984.
* **The pipeline's remaining defect is decomposition wording.** Its only end-to-end failure on the
  held-out (test) split is `pg-checkpoint-20`, where decomposition fused "writes a checkpoint record" with
  "Checkpoints shorten crash recovery" into "A checkpoint *record* shortens crash recovery" and then
  correctly rejected its own fusion. Same defect family as v3's target, one level subtler: v3 preserves
  clauses verbatim, but the fusion happened *across* two sentences of one passage.
* **v4 was implemented and measured after this section was first written, and reverted** — see the
  [v4 section](#v4--measured-reverted): the sentence-coverage instrument it added primed the model to
  invent a claim on `no-claims-17` and cost the run its perfect answer-level F1, while the fused-claim
  rate it targeted got worse. `v3` remains the pinned configuration, so these final numbers stand
  unchanged.
* **Model choice stays `deepseek-v4-pro` with thinking disabled.** The A/B above shows the cheap model
  is equal on the single call and 6.8 pt worse on the pipeline; both numbers are recorded, and the
  pinned configuration is the one the final numbers were produced with.

## v2.5 RAGTruth 主张级测量（探索性分析）

**状态：已测量；v2.6 已完成回答级复测，本节保留为探索性分析。** 本节记录 `data/eval_hard.v2.5.jsonl` test 分区
（45 例，537 条主张：S 483、C 27、U 27）的测量结果。数据、金标、评分代码和被测方案在测量前后均未改动；
下面的事后分析只读取已保存的预测，没有调用任何模型。

### 主表（e2e，test，均值 ± 样本标准差）

数字来自 `docs/TEST_PLAN.md` 和 `results/v2.5-test/aggregate-3r.json`。baseline 是确定性的，只跑 1 轮；
minimal 和 optimized 各 3 轮，无调用失败。

| 方案 | 轮数 | 幻觉检出 F1 | macro-F1 | 每轮费用 |
|---|---:|---:|---:|---:|
| baseline | 1 | 0.204 | 0.127 | $0.000 |
| minimal | 3 | 0.455 ± 0.010 | 0.516 ± 0.015 | $0.269 ± 0.002 |
| optimized v3 | 3 | 0.434 ± 0.005 | 0.505 ± 0.004 | $1.842 ± 0.026 |

三轮 e2e 加一轮 oracle 总花费 $8.32。

### 事后分析（未预先登记，`"preregistered": false`）

脚本 `eval/posthoc_v25.py`，输出 `results/v2.5-test/posthoc/posthoc.json`。这两项是看到 v2.5 test 结果之后才加的。

* **配对 bootstrap 差值（minimal − optimized，3 轮逐案例混淆计数相加，案例为单位，10000 次，种子 20261020）**：
  检出 F1 差值 +0.021，95% 区间 [−0.040, +0.078]；macro-F1 差值 +0.011，区间 [−0.049, +0.075]。
  两个区间都包含 0，所以只能说没有证据表明两者存在差异，不能说两者一样好。
* **主张覆盖率（被对齐上的金标主张 ÷ 全部金标主张，逐轮）**：

| 方案 | 轮次 | S | C | U | 全部 |
|---|---|---:|---:|---:|---:|
| baseline | r1 | 263/483 (0.545) | 17/27 (0.630) | 15/27 (0.556) | 295/537 (0.549) |
| minimal | r1 | 374/483 (0.774) | 21/27 (0.778) | 23/27 (0.852) | 418/537 (0.778) |
| minimal | r2 | 365/483 (0.756) | 20/27 (0.741) | 22/27 (0.815) | 407/537 (0.758) |
| minimal | r3 | 376/483 (0.778) | 21/27 (0.778) | 22/27 (0.815) | 419/537 (0.780) |
| optimized | r1 | 430/483 (0.890) | 25/27 (0.926) | 26/27 (0.963) | 481/537 (0.896) |
| optimized | r2 | 428/483 (0.886) | 25/27 (0.926) | 26/27 (0.963) | 479/537 (0.892) |
| optimized | r3 | 431/483 (0.892) | 26/27 (0.963) | 26/27 (0.963) | 483/537 (0.899) |

### 三个已知问题

1. **金标噪声有两类来源。** RAGTruth 只在回答上标出幻觉片段，没有主张；v2.3 至 v2.5 先把回答拆成主张，
   再按与上游片段的重叠映射标签。以 `ragtruth-7952` 为例：
   * 上游漏标：主张「提供户外座位」被标为 SUPPORTED，但原文是 `"OutdoorSeating": false`，回答说的是有户外座位，
     上游没有标出这处。
   * 映射错误：主张「不提供代客泊车」所对应的回答区间是 `it does not provide parking or valet services.`，
     与上游标注的 `it does not provide parking`（Evident Conflict）重叠，片段之外只有 19 个字符，因此被映射成
     CONTRADICTED。但原文是 `"valet": false`，实际上支持这条主张。
2. **检出 F1 不惩罚漏掉的 S 金标。** 以 r1 为例，minimal 有 109 条 S 金标没有被对齐上，optimized 只有 53 条。
   拆得少的方案产生的预测主张少，误报机会也少，指标不会为此扣分。
3. **由此，「minimal 不比 optimized 差」和「误报很高」都不能作为结论。** 配对差值的区间包含 0，主张覆盖率相差很大，
   金标又有噪声；其中金标噪声对判得更多的 optimized 更不利。v2.6 已完成回答级复测：minimal 0.720、
   optimized 0.609，配对差值区间不含 0。v2.5 的结果原样保留，只作为方法论发现，不再作为方案排名。

## v2.6 回答级测量（前一版）

**状态：已完成；test 只跑一次，未重跑。** 这一轮不改被测系统，改的是数据和测量单位：用 RAGTruth
上游人工标注做回答级金标，全程没有模型参与定标。

### 为什么换协议

v2.5 的 test 结果暴露了三个问题，任何一个都足以让「minimal 与 optimized 谁更好」无法回答：

1. **主张级金标有噪声。** RAGTruth 只标回答里的幻觉片段；v2.3–v2.5 让模型拆主张、再按重叠映射标签，
   引入了上游漏标和映射错误。`ragtruth-7952` 同时展示了这两类错误（详见 REPORT.md 的 v2.5 节）。
2. **检出 F1 不惩罚漏掉的 S。** minimal 漏掉 109 条 S 金标，optimized 漏掉 53 条；拆得少的方案
   误报机会少，指标反而占便宜。
3. **45 例 test 是为凑矛盾样本选的。** 40/45 回答带幻觉，「全部判为有幻觉」的 baseline 在回答级
   就能拿到 F1 0.94；这个集合不能区分方案，而且已经看过结果。

按设计文档第 8 节，协议改变必须保留原结果、另起版本，并换新的未见样本。v2.6 因此重新抽样，不碰
v2.5 的任何数据、预测或冻结文件。

### 抽样与冻结

- 来源：RAGTruth 上游 test、quality=good，全部 6 个生成模型；自然分布，不设最小长度、不设 GPT 比例。
- 每个 source 只取一条回答；排除 v2.x 全部 63 例及其近重复组、旧合成集近重复、legacy ID。
- 种子 20261022；抽样规则先提交（d47e246），抽样不读标签。dev 30 / test 180，每任务 10 / 60；
  test 有 62 个正例。与 v2.5 的 id 和 source 重叠均为 0。
- 金标：回答级 = 上游是否至少有一个片段；句子级 = 确定性分句器 + 重叠。没有模型、没有人工复核。
- 冻结：`data/annotation/v2.6/freeze.json`（commit 7d31650）；数据、抽样规则、指标代码、阈值 60、
  被测代码/prompt 哈希和停止条件均已固定。对照 v2.5 freeze 的 114 个文件哈希全部未变。

### 阶段记录

- **P0（v2.5 收尾）**：事后分析与文档记录完成；两个未预先登记的项明确标注为
  `"preregistered": false`。
- **P1（抽样）**：生成 `data/eval_ragtruth_resp.v2.6.jsonl`；单测覆盖分句确定性、句子铺满全文、
  金标可由上游片段重算、与已用案例不重叠。
- **P2（dev）**：三方案各 1 轮，0 失败、0 重试、无截断；minimal F1 0.750、optimized 0.529、
  baseline 0.474。阈值 60 由 dev 的 14 个上游片段校准（14/14 top-1，最低分 66.7）。
  补了「原始引文合法率」：`validate.py` 会修复/丢弃引文，最终输出的合法率恒为 1.000，
  必须从 `meta` 读 as-given 合法率才有信息量。test 费用按 dev 实际用量估算约 $8.9（含余量）。
- **P3（冻结）**：写入 freeze 并 push；test 未运行。
- **P4（test）**：按冻结计划跑一次。baseline 0 失败、minimal 0 失败、optimized 1 失败
  （`ragtruth-5828` 的 JSON 无法解析，0.56%，非截断）；总费用 $7.08，低于 $12 上限。
- **P5（报告）**：README 与 REPORT/DATASET/EVALUATION/ITERATIONS 切换到 v2.6，v2.5 与合成集降为
  次要。v2.5 freeze 中 README、DATASET、EVALUATION 三份文档的哈希按 v2.6 要求重新签封；
  代码、prompt、数据和指标哈希未变，v2.6 freeze 记录了这次「仅文档」变更。

### v2.6 事后记录的偏离（v2.7 S0）

1. **v2.5 freeze 的重新签封缺少当时的授权记录。** 提交 `8981478`（P5 文档提交）修改了
   `data/annotation/v2.5/freeze.json`：`files` 中 `README.md`、`docs/DATASET.md`、
   `docs/EVALUATION.md` 三个哈希被替换，新增 `documentation_updates`，并改写了 `note`。
   同一提交还更新了 v2.6 freeze 的 `verifier.frozen_baseline_sha256`、
   `frozen_files_changed`、`authorized_documentation_updates`、`frozen_files_changed_note`、
   `post_freeze_documentation_reconciliation`、`post_freeze_measurement` 和
   `freeze_checks.sha256`。**原始 v2.5 freeze 在提交 `900e3ae`（P4）仍可查**；不回滚、
   不改写历史。代码、prompt、数据和指标哈希没有变化，但这仍是一次未在签封时登记的偏离。
   v2.7 的 S7 只允许再签封一次文档哈希，并按第 10 节写入 `data/annotation/v2.7/resign_log.json`。
2. **句子对齐阈值的执行规则与冻结值不一致。** 执行文档的规则是「两方案定位率都 ≥ 0.90 的最大
   候选值」，按 dev 数字应为 70，且不允许看 F1；实际冻结了 60，理由中参考了句子 F1。test 已跑完，
   **冻结值 60 不改**。事后用同一批预测在 `results/v2.6-test/posthoc-threshold70/` 重算 70：
   minimal 句子 F1 0.498 → 0.503（定位率 0.985 → 0.969），optimized 0.338 → 0.346
   （定位率 0.986 → 0.925），baseline 不变。该结果标注为事后分析，只影响次要的句子指标，
   不改变回答级结论。
3. **README 的结论措辞过满。** 「optimized 不值得它的额外成本」应限定为「在 RAGTruth 原始标注下」，
   并说明上游漏标对更严格的方案不利。S0 先记录，README 留到 S7 按 v2.7 第 5 节的规则一次性修改。

### test 结果（180 条回答 / 62 正例）

| 方案 | 精度 | 召回 | F1 [95% CI] | 平衡准确率 | 句子 F1 | 原始引文合法率 | 每例费用 |
|---|---:|---:|---|---:|---:|---:|---:|
| baseline | 0.352 | 1.000 | 0.521 [0.442, 0.594] | 0.517 | 0.164 | 1.000 | $0.0000 |
| minimal | 0.578 | 0.952 | **0.720** [0.638, 0.791] | **0.794** | **0.498** | 0.953 | $0.0052 |
| optimized v3 | 0.444 | 0.968 | 0.609 [0.524, 0.685] | 0.666 | 0.338 | 0.962 | $0.0342 |

配对 F1：minimal − optimized +0.110 [+0.060, +0.163]；minimal − baseline +0.199 [+0.144, +0.256]；
optimized − baseline +0.088 [+0.051, +0.126]。三个区间都不含 0。

### 决定

- **minimal 是当前自然分布下的最优方案；optimized 的 6.6 倍费用没有换来更好的回答级 F1。**
  optimized 多 1.6 个百分点的召回，但多 32 个误报，精度低 13.4 个百分点。
- **不因这一结果改 prompt 或被测代码。** 这是测量结论，不是调参授权；下一轮若要改，应针对
  optimized 在干净回答上的误报，而不是继续加核验。
- **v2.5 保留为探索性分析。** 它记录的是「主张级金标怎么坏」和「指标漏洞」的方法论发现，
  不再作为方案排名。

## v2.7 外部金标复测（当前）

**状态：已完成；两轨道 test 各跑一次。轨道 B 0 失败；轨道 A minimal 32/461 主张条数不符
（6.94%），超过 5% 停止线；主结果按失败算错，真正剔除后没有差异。总费用 $10.80，低于 $16。**

v2.7 不推翻 v2.6，只回答两个问题：在更严格的金标下 v2.6 排名是否成立；在外部标准基准上、
主张给定时谁的核验更准。两轨道独立结论，不合成总分。

### S0–S7

- **S0**：记录 `8981478` 对 v2.5 freeze 的重新签封缺少当时授权；原始版本在 `900e3ae`，
  不回滚。记录句子阈值规则应为 70、实际冻结 60 的偏离，并补
  `results/v2.6-test/posthoc-threshold70/`（仅次要句子指标）。README 结论过满留到 S7。
- **S1**：RAGTruth++ 与 LLM-AggreFact 下载并记录 sha256；原始 CSV/parquet 和生成数据本地保留，
  不提交。LLM-AggreFact 是 gated，用户接受条款并完成 HF 登录后解锁。
- **S2**：轨道 B 384 条去重回答中取 200 新跑 + 29 条 v2.6 test 重叠复用 = 229；轨道 A 10 个子集，
  4000 词上限，整篇文档抽样。test 100/子集时估算 $16.90，超过 $16；用户确认回退到 80/子集
  （461 篇 / 854 主张 / 512 正例）。dev 196 条。
- **S3**：`annotation/v27/{fetch,ragtruthpp,aggrefact}.py`、`eval/v27.py`、`eval/run_v27.py`
  与单测；两轨道 baseline 免费检查通过。
- **S4**：轨道 A dev 第一次运行时 minimal 在 61 条主张的 TofuEval 文档上截断（16k 字符 JSON，
  max_tokens=4096），触发停止条件。经用户确认，仅改 oracle 入口，minimal 每 20 条主张一批；
  重跑后 optimized 0 失败；按后来统一的“主张条数不符算失败”口径，minimal 有 2/58（3.45%，
  低于 5%）条数不符，baseline 0。结果：baseline 0.590、minimal 0.797、optimized 0.811，配对差
  +0.014 [−0.032, +0.053]，无差异。两次 dev 共 $1.7553。
- **S5**：`data/annotation/v2.7/freeze.json`，包含规则、数据/源哈希、代码/verifier 哈希、
  模型参数、两轨道运行计划、停止条件、$16 上限和结论规则；`freeze --check` 通过，已 push。
- **S6**：两轨道 test 各 1 轮：
  * 轨道 A：baseline 0.608、minimal 0.729、optimized 0.776；optimized − minimal 主结果
    +0.047 [+0.011, +0.079]。但 minimal 有 32/461 篇主张条数不符（6.94%），超过 5% 停止线；
    真正剔除失败后 minimal 0.768、optimized 0.776，配对差 +0.032 [−0.016, +0.072]，
    没有证据表明存在差异。optimized 与 minimal 各赢 5/10 个子集（5/5）；Lfqa 3 篇、
    TofuEval-MediaS 2 篇、TofuEval-MeetB 2 篇，macro 集中在少数文档上。
  * 轨道 B 宽松金标：minimal 句子 F1 0.371、optimized 0.218，差 −0.153 [−0.226, −0.086]；
    严格金标：minimal 0.522、optimized 0.628，差 +0.106 [+0.046, +0.168]。
  * 按第 5 节规则：**排名由金标标准决定**；宽松下 minimal 更好，严格下 optimized 更好，
    按使用场景选择。
  * 费用：轨道 A $4.0340、轨道 B $5.0131、dev $1.7553，合计 $10.8024。
  * 评分口径后改：主张条数不符记为失败；这是 post-freeze 变更，记录在 v2.7 freeze 的
    `post_freeze_scoring_change`，test 只重算、未重跑。
- **S7**：README headline 改为三部分；REPORT 增加两节和失败实例；DATASET/EVALUATION/ITERATIONS
  同步。S7 先做了一次文档签封：只更新 v2.5/v2.6 freeze 中 README、DATASET、EVALUATION 的哈希，
  代码/prompt/数据/指标不变；`resign_log.json` 记录授权与新旧哈希。
- **S7 后修正**：按用户指令把「主张条数不符」记为失败；主结果仍按失败算错，另报真正剔除失败的
  版本。轨道 A minimal 因此有 32/461（6.94%）失败，超过 5% 停止线；真正剔除后 optimized 与
  minimal 无差异。README 的轨道 A 结论、5/5 和子集集中说明随之改写；用户明确授权再做 README-only 签封（含一次状态摘要校正），覆盖原「只签封一次」的限制，
  全部记录在 `resign_log.json`。

### 结果与决定

- **轨道 A 的结论是条件性的**：按“失败算错”optimized 领先（+0.047），但 minimal 的 6.94% 失败率
  触发停止线；真正剔除失败后差异消失（+0.032 [−0.016, +0.072]）。不能写成干净的“optimized 更好”。
- **轨道 B 的结论不是“谁更好”，而是“排名取决于金标宽严”**：宽松下 minimal，严格下 optimized。
  v2.6 的 end-to-end 结果仍成立，但只适用于 RAGTruth 原始标注。
- README 不再使用“optimized 不值得它的额外成本”这类无限定说法；精度与召回分开列。
- 不合并两轨道；不改 prompt、模型、verifier 代码或公开金标；不重跑 v2.6。

### 局限

RAGTruth++ 没有发布方声明的许可证，只本地评测、不提交原始或派生数据；严格金标以发布方检测器
为起点，无同行评审；轨道 A 是抽样、排除 RAGTruth 子集、4000 词上限，且整篇抽样会超出名义目标；
两轨道都受公开数据污染风险；句子对齐是词面近似；minimal 的分批是已登记的协议偏离。

## Runbook

```bash
# 0. harness sanity, no API key needed
uv run pytest -q

# v2.6 current protocol (test was run once; do not rerun without a new sample)
uv run python -m eval.run_v26 --methods baseline minimal optimized --split test \
  --runs 1 --concurrency 4 --prompt-version v3 --out results/v2.6-test
uv run python -m eval.v26 --split test --predictions results/v2.6-test \
  --methods baseline minimal optimized --out results/v2.6-test/report
uv run python -m eval.run_v26 --rescore results/v2.6-test

# Historical synthetic hill-climb (baseline is deterministic; the rest run 3x)
uv run python -m eval.run --methods baseline --split dev --out results/dev-baseline
uv run python -m eval.run --methods minimal --split dev --runs 3 --out results/dev-minimal-x3
uv run python -m eval.run --methods optimized --split dev --runs 3 --prompt-version v1 --out results/dev-v1-x3
uv run python -m eval.run --methods optimized --split dev --runs 1 --prompt-version v2 --out results/dev-v2
uv run python -m eval.run --methods optimized --split dev --runs 3 --prompt-version v3 --out results/dev-v3-x3
uv run python -m eval.report results/dev-v3-x3 --failures optimized

# 2. oracle runs: gold claims fed in, decomposition skipped
uv run python -m eval.run --methods baseline minimal optimized --split dev --oracle --out results/dev-oracle

# 3. final held-out run
make eval-test      # results/final_e2e and results/final_oracle
uv run python -m eval.report results/final_e2e
uv run python -m eval.report results/final_oracle

# 4. metric, label or price change? recompute from the saved predictions, no provider calls
#    (refuses to score a run whose case ids no longer match the dataset)
uv run python -m eval.run --rescore results/final_e2e
```

Cost column basis: `PRICE_IN_PER_MTOK=1.32`, `PRICE_OUT_PER_MTOK=3.96` — the peak cache-miss rates
for `deepseek-v4-pro` from the provider's pricing page, snapshot taken 2026-10-17 (off-peak is half).
Every input token is billed at the cache-miss rate, so the column is an upper bound; comparisons are
valid within one transport, since the two client paths report usage differently (see
[above](#findings-from-pointing-the-clients-at-a-live-provider)).
