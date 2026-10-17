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
| Fused claims (claim spans >1 sentence) | 0.113 | 0.115 ± 0.001 | 0.096 ± 0.003 | 0.095 | 0.096 ± 0.000 | 0.108 ± 0.000 |
| Citation precision | 0.885 | 0.976 ± 0.010 | 0.882 ± 0.016 | 0.898 | 0.870 ± 0.008 | 0.867 ± 0.009 |
| Citation recall | 0.885 | 0.996 ± 0.006 | 0.966 ± 0.006 | 0.962 | 0.963 ± 0.000 | 0.963 ± 0.000 |
| Citation precision (right passage) | 1.000 | 0.988 ± 0.000 | 0.956 ± 0.008 | 0.966 | 0.957 ± 0.008 | 0.957 ± 0.008 |
| Citation recall (right passage) | 1.000 | 1.000 ± 0.000 | 1.000 ± 0.000 | 1.000 | 1.000 ± 0.000 | 1.000 ± 0.000 |
| Raw citation invalid rate (before repair) | 0.000 | 0.008 ± 0.005 | 0.003 ± 0.005 | 0.000 | 0.000 ± 0.000 | 0.010 ± 0.000 |
| Latency p50 / p95 (ms) | 0 / 0 | 3645 / 5353 | 4814 / 5858 | 5154 / 7295 | 4657 / 6003 | 5749 / 7541 |
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
  answer-level F1 **0.980 ± 0.000 against v3's 1.000 ± 0.000**, latency p50 5749 ms against 4657 ms
  (+23 %), cost $0.0090 against $0.0080 per case (+12 %), raw citation invalid rate 0.010 against 0.000.
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
  latency +23 %, cost +12 %, and the fusion improvement did not offset that regression. v4 stays in the
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
| Latency p50 / p95 (ms) | 0.2 / 0.2 | 3521 / 4649 | 4791 / 7956 |
| Input / output tokens per case | 0 / 0 | 647 / 332 | 3895 / 658 |
| Cost / case (USD, prices below) | 0.000000 | 0.002168 | 0.007745 |
| LLM calls / case | 0.00 | 1.00 | 4.70 |
| Errored cases | 0 | 0 | 0 |

Oracle, after the corrections:

| Metric | baseline | minimal | optimized v3 |
|---|---|---|---|
| Claim accuracy (all gold claims) | 0.705 | 0.978 ± 0.008 | **1.000 ± 0.000** |
| Macro-F1 (3 verdicts) | 0.569 | 0.969 ± 0.020 | **1.000 ± 0.000** |
| Citation precision (right passage) | 1.000 | 0.994 | **1.000** |
| Latency p50 (ms) | 0.1 | 3541 | **3001** |
| Input tokens per case | 0 | 666 | 2555 |
| LLM calls / case | 0.00 | 1.00 | 2.95 |

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

## Runbook

```bash
# 0. harness sanity, no API key needed
uv run pytest -q

# 1. dev hill-climb (baseline is deterministic; the rest run 3x)
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
