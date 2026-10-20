# Results report

Measured results for the three verifiers, the failures behind them, and what may not be concluded from
them. Every table below was regenerated from the raw artifacts in `results/` (one JSONL per run plus
`summary.json`), never transcribed by hand — those files, not this document, remain the ground truth. The decisions that produced this configuration are in [ITERATIONS.md](ITERATIONS.md); the metric
definitions in [EVALUATION.md](EVALUATION.md).

Configuration for all numbers: provider `DeepSeek`, model `deepseek-v4-pro` with
`VERIFIER_EXTRA_BODY={"thinking":{"type":"disabled"}}`, prompt set `v3`, `temperature=0`. In the
historical synthetic benchmark every LLM row is the mean of 3 runs; the baseline is deterministic and
ran once. The v2.6 measurement is one run per method, as preregistered.

## v2.6 response-level measurement (current headline)

**Status: measured once on 180 unseen RAGTruth test responses (62 hallucinated); no rerun.** The
gold is RAGTruth's upstream human span annotation; no model participated in labelling. The response
is predicted hallucinated iff the verifier emits at least one `CONTRADICTED` or `UNSUPPORTED` claim.
A failed case counts as wrong on the opposite side of its gold; the `excluding_failures` variant is
reported alongside. Intervals resample complete responses (10000 draws, seed 20261022). The sentence
alignment threshold is 60, fixed on dev before test. Freeze record:
[freeze.json](../data/annotation/v2.6/freeze.json); raw runs:
[results/v2.6-test](../results/v2.6-test); full metric report:
[results/v2.6-test/report/v26_report.json](../results/v2.6-test/report/v26_report.json).

| Method | Failures | Precision | Recall | F1 [95% CI] | Balanced acc. | Sentence F1 | Raw citation validity | Cost / response |
|---|---:|---:|---:|---|---:|---:|---:|---:|
| baseline | 0 | 0.352 | 1.000 | 0.521 [0.442, 0.594] | 0.517 | 0.164 | 1.000 | $0.0000 |
| minimal | 0 | 0.578 | 0.952 | **0.720** [0.638, 0.791] | **0.794** | **0.498** | 0.953 | $0.0052 |
| optimized v3 | 1 | 0.444 | 0.968 | 0.609 [0.524, 0.685] | 0.666 | 0.338 | 0.962 | $0.0342 |

Paired bootstrap on the same responses (F1 difference, 95% CI):

| Comparison | Main result | Excluding the failed case |
|---|---|---|
| optimized − minimal | −0.110 [−0.163, −0.060] | −0.104 [−0.156, −0.054] |
| minimal − baseline | +0.199 [+0.144, +0.256] | +0.199 [+0.144, +0.256] |
| optimized − baseline | +0.088 [+0.051, +0.126] | +0.095 [+0.061, +0.132] |

All three intervals exclude 0. Under the registered wording rule: **minimal is better than
optimized; both LLM methods are better than the baseline.** The v2.5 point estimate pointed the same
way (minimal 0.455 vs optimized 0.434) but its interval crossed 0; v2.6 makes the difference
measurable. It is the reverse of the pre-test expectation that optimized's extra verification would
pay off, and it is the main result of this round.

**What the extra cost buys.** optimized costs 6.6× minimal ($0.0342 vs $0.0052 per response) and
raises recall by 1.6 points (0.968 vs 0.952), but it produces 75 false positives against minimal's
43, costing 13.4 points of precision and 11.1 points of F1. On Data2txt the lexical baseline is
nearly level with optimized (F1 0.800 vs 0.796); minimal wins on every task. The extra verification
is not paying for itself on natural-distribution answers.

**Why the benchmark changed.** The v2.5 claim-level gold was noisy in two ways: RAGTruth marks
hallucination spans on the answer, not atomic claims, so the claim splitter and overlap mapping
introduced upstream misses and mapping errors (the `ragtruth-7952` examples are in the v2.5 section
below). The claim-level detection F1 also did not penalise missing `SUPPORTED` gold, so a method that
emitted fewer claims had fewer chances to be wrong. Finally, the 45-case hard test had been enriched
for contradictions (40/45 answers hallucinated), so an all-positive baseline reached F1 0.94 — the
set could not separate methods. v2.6 instead draws new, never-used natural-distribution responses
and takes the gold directly from the upstream annotation; no model labels anything. v2.5 is retained
below as exploratory analysis, not as a ranking.

### Secondary indicators

**Sentence localisation.** Every `CONTRADICTED`/`UNSUPPORTED` claim is matched lexically
(`rapidfuzz.token_set_ratio`, threshold 60) to the most similar answer sentence; claims below the
threshold are counted as unlocalised and enter no sentence. The match is approximate. minimal has
sentence-level P/R/F1 0.351 / 0.857 / **0.498**; optimized 0.209 / 0.879 / 0.338; baseline
0.090 / 0.912 / 0.164. minimal localises 258 C/U claims at 0.985, optimized 511 at 0.987. The
optimized pipeline emits more C/U claims, so it finds more bad sentences (recall 0.879 vs 0.857) but
lands on many more clean sentences (precision 0.209 vs 0.351).

**Citations.** The final-output citation validity is 1.000 for every method by construction:
`validate.py` repairs, relocates or drops a citation before returning, and downgrades a claim with
no valid citation to `UNSUPPORTED`. The informative number is the **as-given** validity, read from
`meta.raw_citations_*`: minimal 0.953 (95 of 2023 raw citations invalid; 31 claims downgraded across
16 responses), optimized 0.962 (100 of 2622 invalid; 0 downgrades), baseline 1.000. optimized has
the cleaner citation discipline, but not enough to offset its false positives. Whether a citation
is *sufficient* to prove a claim is not assessed.

**Groups** (minimal / optimized F1; n<20 is for reference only):

| Dimension | Group | n | Positives | minimal | optimized |
|---|---|---:|---:|---:|---:|
| Task | Data2txt | 60 | 40 | 0.857 | 0.796 |
| Task | Summary | 60 | 14 | 0.585 | 0.491 |
| Task | QA | 60 | 8 | 0.500 | 0.348 |
| Generator | llama-2-13b-chat | 31 | 18 | 0.919 | 0.818 |
| Generator | llama-2-70b-chat | 28 | 12 | 0.889 | 0.727 |
| Generator | llama-2-7b-chat | 28 | 13 | 0.750 | 0.632 |
| Generator | mistral-7B-instruct | 35 | 16 | 0.711 | 0.667 |
| Generator | gpt-3.5-turbo-0613 | 32 | 2 | 0.286 | 0.211 |
| Generator | gpt-4-0613 | 26 | 1 | 0.000 | 0.111 |
| Context | 0–399 words | 132 | 43 | 0.726 | 0.609 |
| Context | 400–799 words | 39 | 15 | 0.683 | 0.596 |
| Context | 800+ words | 9 | 4 | 0.800 | 0.667 |

QA and Summary are the hardest tasks; GPT-generated answers are the hardest generator group, but
QA has 8 positives and GPT-4 has 1, so those rows are diagnostic only. On upstream label type
(positives only), minimal recalls 0.980 of Evident cases and 0.846 of cases containing Subtle;
optimized reaches 0.980 / 0.923, but the Subtle group has only 13 positives.

### Failure analysis

* **optimized over-flags clean answers.** `ragtruth-10458` (Data2txt, gpt-4) calls "Many customers
  enjoy the store's atmosphere" UNSUPPORTED although one review says "I just love everything,
  including the atmosphere"; `ragtruth-11191` treats a 4.0-star business rating as unsupported
  because the wording says "according to customer reviews". These are reasonable summaries that a
  strict verifier rejects. The pattern accounts for most of the 36 clean responses that optimized
  flags and minimal does not.
* **minimal misses real subtle conflicts.** `ragtruth-2374` (Summary, llama-2-13b) marks "friend of
  44 years" and "remains unconscious in the hospital" SUPPORTED; upstream marks both `Subtle
  Conflict` (the source says "more than 44 years", and the petition's "unconscious" is disputed by
  the website's "alert"). `ragtruth-9840` marks "did not provide music" SUPPORTED from
  `"Music": null`; upstream marks that negative assertion `Evident Baseless Info`. Null-valued
  attributes are a systematic trap: null means unknown, not false.
* **One provider failure.** `ragtruth-5828` (optimized) exhausted retries with `unparseable
  response: Expecting ',' delimiter ...`; it is a gold-positive Data2txt case and counts as a
  missed detection. Failure rate 1/180 = 0.56%, below the 5% stop line; the failure is a malformed
  JSON response, not a max_tokens truncation or an overlong input. No rerun was made.

### v2.6 protocol deviations (recorded in v2.7 S0)

* **The v2.5 freeze was re-sealed without a recorded authorization.** Commit `8981478` replaced the
  `files` hashes for `README.md`, `docs/DATASET.md` and `docs/EVALUATION.md`, added a
  `documentation_updates` block and rewrote the `note` in `data/annotation/v2.5/freeze.json`; it also
  updated the v2.6 freeze's baseline hash and reconciliation fields. The original v2.5 freeze remains
  available at commit `900e3ae`. Nothing was rolled back or rewritten. Code, prompt, data and metric
  hashes did not change, but the re-seal was not authorized at the time. v2.7 S7 permits exactly one
  further documentation-only re-seal, recorded in `data/annotation/v2.7/resign_log.json`.
* **The sentence threshold did not follow the execution rule.** The rule was the largest candidate
  with localisation rate ≥ 0.90 for both methods (70 on dev), without looking at F1; 60 was frozen
  instead with F1 in the rationale. The frozen value is not changed after test. A post-hoc rerun at
  70 (`results/v2.6-test/posthoc-threshold70/`) gives minimal sentence F1 0.503 vs 0.498 at 60
  (localisation 0.969 vs 0.985) and optimized 0.346 vs 0.338 (0.925 vs 0.986); baseline is unchanged.
  This affects the secondary sentence metric only, not the answer-level ranking.
* **The README conclusion is over-broad.** “optimized is not worth its extra cost” should be limited
  to “under RAGTruth's original annotation”, with the note that upstream misses penalise stricter
  methods. The wording is left for S7 and the v2.7 registered conclusion rule.

### v2.6 threats to validity

* The upstream annotation can miss hallucinations; no human review was added. An answer with no
  upstream span is called **“upstream-unannotated”**, not “clean”.
* 180 responses, 62 positives; QA has 8 positives and GPT-4 has 1, so task/generator groups are
  diagnostic. Only `deepseek-v4-pro` and prompt v3 were measured.
* RAGTruth has been public since 2024; training-data contamination cannot be ruled out.
* Sentence alignment is lexical and approximate; citation sufficiency is not measured.
* The protocol changed after the v2.5 test was seen. The verifier code and prompt did not change,
  and v2.6 uses new responses with no id or source overlap with v2.5, but the change was not
  preregistered before v2.5.
* No human semantic spot check and no human-confirmed clean answers; this was a deliberate user
  decision and is a limitation, not a claim of correctness.
* Strict verifiers can be penalised when upstream annotators accepted a mild inference. This is
  visible in the optimized false positives and is part of why the natural-distribution ranking
  differs from the adversarial v2.5 set.

The rest of this report documents the historical synthetic benchmark and the exploratory v2.5
claim-level measurement.

## Development split (26 cases / 89 gold claims)

| Metric | baseline | minimal | opt v1 | opt v2 | opt v3 | opt v4 |
|---|---|---|---|---|---|---|
| Answer-level hallucination F1 | 0.980 | 0.987 ± 0.009 | 1.000 ± 0.000 | 1.000 | 1.000 ± 0.000 | 0.980 ± 0.000 |
| Claim accuracy (all gold claims) | 0.382 | 0.989 ± 0.009 | 0.981 ± 0.005 | 0.966 | 0.989 ± 0.000 | 0.989 ± 0.000 |
| Claim accuracy (matched only) | 0.493 | 0.989 ± 0.009 | 0.992 ± 0.005 | 0.977 | 1.000 ± 0.000 | 1.000 ± 0.000 |
| Macro-F1 (3 verdicts) | 0.411 | 0.983 ± 0.013 | 0.991 ± 0.004 | 0.954 | 0.997 ± 0.000 | 0.997 ± 0.000 |
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
| Raw citation invalid rate | 0.000 | 0.008 ± 0.005 | 0.003 ± 0.005 | 0.000 | 0.000 ± 0.000 | 0.010 ± 0.000 |
| Latency p50 / p95 (ms) | 0.14 / 0.30 | 3645 / 5353 | 4814 / 5858 | 5154 / 7295 | 4657 / 6003 | 5749 / 7541 |
| Input / output tokens per case | 0 / 0 | 681 / 372 | 4034 / 690 | 4794 / 671 | 4022 / 669 | 4095 / 823 |
| LLM calls / case | 0.00 | 1.00 ± 0.00 | 4.68 ± 0.08 | 4.58 | 4.53 ± 0.02 | 4.50 ± 0.00 |
| Cost / case (USD) | 0.0000 | 0.0024 ± 0.0000 | 0.0081 ± 0.0002 | 0.0090 | 0.0080 ± 0.0000 | 0.0087 ± 0.0000 |
| Errored cases | 0 | 0 ± 0 | 0 ± 0 | 0 | 0 ± 0 | 0 ± 0 |

Two rows are easy to misread:

* **Citation precision is annotator-strict.** It credits a citation only when it overlaps the annotated
  gold span. A per-sentence verifier cites the sentence it reasoned from, which for a multi-sentence
  fact is often a different sentence of the same passage — hence 0.87 for the pipeline against 0.98 for
  the single call, which quotes the salient phrase. The *right passage* row is the same question without
  the annotation taste (0.957 vs 0.988), and the residual gap is small but real.
* **Decomposition precision below 1 is not an error.** Both LLM methods emit slightly more claims than
  the reference (splitting "A and B" as the contract instructs); alignment matches one and the sibling
  counts as a precision loss. The single call scores higher here only because it keeps sentences whole.

## Oracle runs: where the error budget actually is

`--oracle` feeds the gold claims in and skips decomposition.

### dev (1 run)

| Metric | baseline | minimal | optimized v3 |
|---|---|---|---|
| Answer-level hallucination F1 | 0.980 | 1.000 | 1.000 |
| Claim accuracy (all gold claims) | 0.494 | 1.000 | 1.000 |
| Claim accuracy (matched only) | 0.494 | 1.000 | 1.000 |
| Macro-F1 (3 verdicts) | 0.454 | 1.000 | 1.000 |
| F1 SUPPORTED | 0.683 | 1.000 | 1.000 |
| F1 CONTRADICTED | 0.368 | 1.000 | 1.000 |
| F1 UNSUPPORTED | 0.310 | 1.000 | 1.000 |
| Decomposition recall | 1.000 | 1.000 | 1.000 |
| Decomposition precision | 1.000 | 1.000 | 1.000 |
| Answer sentence coverage | 0.972 | 0.972 | 0.972 |
| Fused claims (claim carries distinctive words from ≥2 sentences) | 0.045 | 0.045 | 0.045 |
| Citation precision | 0.943 | 0.953 | 0.871 |
| Citation recall | 0.943 | 1.000 | 0.975 |
| Citation precision (right passage) | 1.000 | 0.965 | 0.946 |
| Citation recall (right passage) | 1.000 | 1.000 | 1.000 |
| Raw citation invalid rate | 0.000 | 0.000 | 0.011 |
| Latency p50 / p95 (ms) | 0.19 / 0.48 | 3966 / 6176 | 2747 / 3807 |
| Input / output tokens per case | 0 / 0 | 701 / 373 | 3162 / 558 |
| LLM calls / case | 0.00 | 1.00 | 3.35 |
| Cost / case (USD) | 0.0000 | 0.0024 | 0.0064 |
| Errored cases | 0 | 0 | 0 |

### test (3 runs, held out)

| Metric | baseline | minimal | optimized v3 |
|---|---|---|---|
| Answer-level hallucination F1 | 0.741 | 1.000 ± 0.000 | 1.000 ± 0.000 |
| Claim accuracy (all gold claims) | 0.705 | 0.978 ± 0.008 | 1.000 ± 0.000 |
| Claim accuracy (matched only) | 0.705 | 0.978 ± 0.008 | 1.000 ± 0.000 |
| Macro-F1 (3 verdicts) | 0.569 | 0.969 ± 0.020 | 1.000 ± 0.000 |
| F1 SUPPORTED | 0.829 | 0.988 ± 0.000 | 1.000 ± 0.000 |
| F1 CONTRADICTED | 0.333 | 0.948 ± 0.017 | 1.000 ± 0.000 |
| F1 UNSUPPORTED | 0.545 | 0.970 ± 0.043 | 1.000 ± 0.000 |
| Decomposition recall | 1.000 | 1.000 ± 0.000 | 1.000 ± 0.000 |
| Decomposition precision | 1.000 | 1.000 ± 0.000 | 1.000 ± 0.000 |
| Answer sentence coverage | 0.980 | 0.980 ± 0.000 | 0.980 ± 0.000 |
| Fused claims (claim carries distinctive words from ≥2 sentences) | 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 |
| Citation precision | 1.000 | 0.994 ± 0.009 | 0.932 ± 0.000 |
| Citation recall | 1.000 | 0.982 ± 0.000 | 0.982 ± 0.000 |
| Citation precision (right passage) | 1.000 | 0.994 ± 0.009 | 1.000 ± 0.000 |
| Citation recall (right passage) | 1.000 | 0.982 ± 0.000 | 0.982 ± 0.000 |
| Raw citation invalid rate | 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 |
| Latency p50 / p95 (ms) | 0.15 / 0.20 | 3443 / 4418 | 2769 / 4716 |
| Input / output tokens per case | 0 / 0 | 666 / 326 | 2555 / 466 |
| LLM calls / case | 0.00 | 1.00 ± 0.00 | 2.95 ± 0.00 |
| Cost / case (USD) | 0.0000 | 0.0022 ± 0.0000 | 0.0052 ± 0.0000 |
| Errored cases | 0 | 0 ± 0 | 0 ± 0 |

**The most useful result in this report.** With gold claims supplied, the per-claim pipeline judges every
claim correctly on both splits (1.000, 3 runs) while the single call makes two verdict errors on the
held-out split. End-to-end they tie. So:

* for LLM verifiers **the verification step is solved** on this dataset, and the entire residual
  end-to-end error is **decomposition** — which claims the system chooses to check, and how it words them;
* for the baseline the bottleneck is the opposite: lexical matching cannot decide entailment (0.494 dev
  oracle), while its sentence splitter already recovers 0.775 of the gold claims. Better decomposition
  would not have helped it, better NLI would;
* the pipeline's advantage is exactly as large as the decomposition step allows — and no larger.

In oracle mode the pipeline is also the faster option per case (2747 ms vs 3966 ms on dev, 2769 vs 3443
on test) and the cheaper one ($0.0052 vs $0.0022 aside — it costs more in dollars but less wall-clock):
one small call per claim in parallel beats one call carrying the whole answer plus every passage.

## Held-out final run (test split, 20 cases / 61 claims, 3 runs)

Run once with the frozen configuration; the label audit that preceded it is documented in
[ITERATIONS.md](ITERATIONS.md#dataset-calibration-also-eval-driven).

| Metric | baseline | minimal | optimized v3 |
|---|---|---|---|
| Answer-level hallucination F1 | 0.889 | 1.000 ± 0.000 | 1.000 ± 0.000 |
| Claim accuracy (all gold claims) | 0.590 | 0.984 ± 0.000 | 0.984 ± 0.000 |
| Claim accuracy (matched only) | 0.720 | 0.984 ± 0.000 | 0.984 ± 0.000 |
| Macro-F1 (3 verdicts) | 0.528 | 0.983 ± 0.000 | 0.970 ± 0.000 |
| F1 SUPPORTED | 0.778 | 0.988 ± 0.000 | 0.988 ± 0.000 |
| F1 CONTRADICTED | 0.353 | 0.960 ± 0.000 | 1.000 ± 0.000 |
| F1 UNSUPPORTED | 0.455 | 1.000 ± 0.000 | 0.923 ± 0.000 |
| Decomposition recall | 0.820 | 1.000 ± 0.000 | 1.000 ± 0.000 |
| Decomposition precision | 0.980 | 0.884 ± 0.000 | 0.803 ± 0.000 |
| Answer sentence coverage | 1.000 | 1.000 ± 0.000 | 1.000 ± 0.000 |
| Fused claims (claim carries distinctive words from ≥2 sentences) | 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 |
| Citation precision | 0.968 | 0.944 ± 0.000 | 0.908 ± 0.008 |
| Citation recall | 0.968 | 0.927 ± 0.000 | 0.958 ± 0.009 |
| Citation precision (right passage) | 0.968 | 1.000 ± 0.000 | 0.983 ± 0.000 |
| Citation recall (right passage) | 0.968 | 0.982 ± 0.000 | 0.982 ± 0.000 |
| Raw citation invalid rate | 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 |
| Latency p50 / p95 (ms) | 0.15 / 0.19 | 3521 / 4649 | 4791 / 7956 |
| Input / output tokens per case | 0 / 0 | 647 / 332 | 3894 / 661 |
| LLM calls / case | 0.00 | 1.00 ± 0.00 | 4.70 ± 0.00 |
| Cost / case (USD) | 0.0000 | 0.0022 ± 0.0000 | 0.0078 ± 0.0000 |
| Errored cases | 0 | 0 ± 0 | 0 ± 0 |

Both LLM methods score 0.984 claim accuracy and 1.000 answer-level F1; they fail in different places.
`minimal` loses on the verdict boundary (`prometheus-counter-17`: it reads "a counter only goes up,
**except when the process restarts**" and still calls "can only increase, never decrease" entailed) and
on `http-retry-21` (an over-claim labelled CONTRADICTED where the sources are silent). The pipeline loses
on decomposition: its single end-to-end failure is `pg-checkpoint-20` (a test-split case), where it
fused "writes a checkpoint record" with "Checkpoints shorten crash recovery" into "A checkpoint
**record** shortens crash recovery" and then correctly rejected its own invention.

**Cost basis.** USD per case uses the provider's published peak cache-miss rates for
`deepseek-v4-pro` ($1.32/M input, $3.96/M output), snapshot taken 2026-10-17 from the provider's pricing
page; off-peak is exactly half, and every input token is billed as a cache miss, so the column is an
upper bound rather than a bill. It is valid within one client transport; the two transports report usage
differently, which is why cached-prefix tokens are summed explicitly before pricing.

## Failure analysis

**The baseline under-commits.** BM25 plus a 60 % content-word overlap threshold labels paraphrased but
supported claims UNSUPPORTED ("covers only 27 % of the claim's content words"), so the distortions it
should catch (`sqlite-wal-01` NFS negation, `redis-aof-02` 2 s vs 1 s, `py-asyncio-04` completion order,
`k8s-probes-06` probe swap) come back as UNSUPPORTED instead of CONTRADICTED — F1 CONTRADICTED 0.368 on
dev. Its number and negation heuristics do fire, but only once the claim is nearly verbatim
(`docker-exit-05`, `systemd-restart-11`). Its high answer-level F1 is a case-mix artifact: nearly every
answer contains one distorted claim, so "flag everything" scores well at answer level while being wrong
claim by claim. Its citations look strong (precision 0.885, right passage 1.000) because it cites rarely
— low recall, high precision.

**The pipeline's residual error is decomposition wording.** On `redis-cluster-long-31` (dev) an early
revision trimmed the claim "The latency monitor records events slower than latency-monitor-threshold, **which is
given in seconds**." down to "…slower than latency-monitor-threshold." — deleting the unit error — and
the verifier then *correctly* supported the trimmed claim. A distortion removed before verification is
invisible to the verifier, to the retry logic and to the invariant checker alike. Prompt v3 fixed that
case (dev claim accuracy 0.981 → 0.989, zero variance); prompt v4 tried to fix the remaining fusion
defect and failed (see below).

**A predicted fix that half-worked and was still reverted (v4).** The sentence-coverage instrument did
what it promised: coverage rose (0.972 → 0.986) and the corrected fused-claim rate halved (0.043 →
0.022). It was nevertheless reverted, on evidence that does not depend on that metric: its "do not skip a
sentence" rule made the model invent a claim for the greeting in `no-claims-17` (answer-level F1 1.000 →
0.980), latency p50 rose 4657 → 5749 ms and cost $0.0080 → $0.0087 per case, and the fusion gain did not offset the edge-case regression.
The first version of this conclusion said fusion had got *worse* — that came from a metric with an ~11 %
false-positive floor (the baseline, unable to fuse, scored 0.113); the metric now decides on distinctive
content words and the baseline scores 0.000. The v5 successor is v4 plus one explicit exception, with the
keep-condition written against the corrected metric. Note that v4's motivating example
(`pg-checkpoint-20`) is a **test** case and `jwt-claims-14` the dev case of the same class — disclosed as
a protocol break in the log, with no reported test number depending on it.

**A metric that was measuring its own noise.** The fused-claim rate was the one instrument pointing at
v4 negatively, and it turned out to be an artifact: the baseline, which cannot fuse by construction,
scored 0.113 on it. Fixed to use distinctive content words (baseline now 0.000, v4 0.022, v3 0.043),
rescore-only, no model calls, with a regression test. Corrected numbers are in the tables above.

**Three client defects that only a real endpoint could expose.** (a) The Anthropic client was dead
against the installed SDK — `anthropic` 1.15 dropped `temperature` from `messages.create`, so the first
real call raised `TypeError` while every unit test passed, because they replace the SDK client wholesale.
Sampling is now pinned through the typed parameter or through `extra_body`, and a full dev run over that
transport reproduces the OpenAI-compatible path exactly (0.989 / 0.997 / 1.000, 4033 tokens per case).
(b) On that transport prompt-cache tokens sit outside `usage.input_tokens`, undercounting the cost column
12× (331 vs 4033 tokens per case for identical work); `_input_volume()` now sums the three usage fields.
(c) A stale `VERIFIER_BASE_URL` used to outrank `ANTHROPIC_BASE_URL`, silently sending Anthropic-format
requests to the OpenAI endpoint after a provider switch.

**Three labels were wrong, and the eval found them.** `kafka-partitions-10` was annotated SUPPORTED for
"records with the same key stay ordered within their partition even after the partition count changes";
both verifiers rejected it, both were right, and it was relabelled. `kafka-retention-11` had an answer
saying segments are "deleted" where the source says "eligible for deletion" — the verifiers were right
again. `http-retry-21` carried a universal claim the sources arguably implied false; it was replaced with
a claim the sources are simply silent about. One label was deliberately **kept** against the model
(`prometheus-counter-17`), because the dropped "except when the process restarts" exception is exactly
what that case tests. A whole-dataset read-back audit now agrees with 149/150 labels for the pipeline and
147/150 for the single call.

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
   金标又有噪声；其中金标噪声对判得更多的 optimized 更不利。v2.6 用自然分布回答和上游回答级金标复测后，
   minimal 的回答级 F1 为 0.720，optimized 为 0.609，配对差值区间不包含 0（见本文顶部）。v2.5 的结果原样保留，
   只作为方法论发现，不再作为方案排名。

## Threats to validity (historical synthetic benchmark)

* **150 claims, one annotator, one model family.** Differences below ~5 points on one split are noise;
  that is why the report shows 3-run means ± std and why five prompt versions and two models were
  compared on the same dev split (multiple comparisons, with the losers kept in the log).
* **The benchmark is at or near ceiling** for claim accuracy with these models (0.989 dev, 0.984 test).
  The report therefore leans on verdict-boundary F1, citation rows, sentence coverage, calls, tokens and
  latency, which still separate the methods. Hardening it further would need either ambiguity (bad
  labels) or needle-in-haystack contexts the service does not target.
* **The label audit is model-based**, so it can only find labels a model sharing this training data also
  finds contestable, and it shares a family with the system under test. It raises confidence; it does not
  establish inter-annotator agreement.
* **Cost is computed, not billed**, and comparable only within one transport.
* **Both transports were exercised live, but only against one provider** (DeepSeek, over its
  OpenAI-compatible and Anthropic-compatible endpoints, same models). The Anthropic SDK path is now
  proven to work, not proven equivalent on a second vendor.
* The empty-context cases are solved by construction, so they inflate UNSUPPORTED recall for every method
  and test robustness rather than discrimination.

## Next steps

**v2.6 follow-ups (current):**

1. **Do not promote optimized as the default on this evidence.** It is 6.6× the cost and 11.1 F1
   points behind minimal on natural-distribution answers. If the pipeline is kept, the next change
   should target its false positives on clean answers, not add more verification.
2. **Raise minimal's recall without losing precision.** The misses are concentrated in subtle
   conflicts and null-valued attributes (`ragtruth-2374`, `ragtruth-9840`). A targeted rule for
   “null means unknown, not false” is a falsifiable next experiment.
3. **Repeat with a second provider and a second model** before treating the ranking as general; this
   round used one model family and one prompt.
4. **A small human spot check** of the 62 positive and 118 upstream-unannotated responses would
   bound the annotation noise; it was deliberately out of scope here.

**Historical synthetic follow-ups:**

1. **v5 decomposition**, falsifiable target: keep the sentence-coverage mapping (which measurably worked:
   coverage 0.972 → 0.986, fusion 0.043 → 0.022) but state the exception explicitly ("a sentence with no
   factual content produces no claim"), and keep it only if `no-claims-17` returns an empty list again
   and the corrected fused-claim rate stays at or below v4's 0.022. Its motivating example came from the
   test split; see the protocol note in the log.
2. **A second human annotator** on a 30 % sample, to replace the model-based audit with real
   inter-annotator agreement, and a second provider for the comparison.
3. **A cheaper batched mode**: the pipeline's cost is dominated by one call per claim; batching small
   claims into a shared call is the opposite trade to the current design and is measurable with the same
   harness (`calls/case` and cost columns already exist).
4. **Blind spots left out of scope**: streaming, request caching, abstain/confidence output, non-English
   text, and long-document contexts beyond 9 passages.
