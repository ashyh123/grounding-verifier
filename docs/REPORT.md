# Results report

Measured results for the three verifiers, the failures behind them, and what may not be concluded from
them. Every table below was regenerated from the raw artifacts in `results/` (one JSONL per run plus
`summary.json`), never transcribed by hand — those files, not this document, remain the ground truth. The decisions that produced this configuration are in [ITERATIONS.md](ITERATIONS.md); the metric
definitions in [EVALUATION.md](EVALUATION.md).

Configuration for all numbers: provider `DeepSeek`, model `deepseek-v4-pro` with
`VERIFIER_EXTRA_BODY={"thinking":{"type":"disabled"}}`, prompt set `v3`, `temperature=0`. Every LLM row
is the mean of 3 runs; the baseline is deterministic and ran once.

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
| Fused claims | 0.000 | 0.000 ± 0.000 | 0.041 ± 0.001 | 0.042 | 0.043 ± 0.000 | 0.022 ± 0.000 |
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
| Fused claims | 0.045 | 0.045 | 0.045 |
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
| Fused claims | 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 |
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
| Fused claims | 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 |
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
0.980), latency rose 23 % and cost 12 %, and the fusion gain did not offset the edge-case regression.
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

## Threats to validity

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
