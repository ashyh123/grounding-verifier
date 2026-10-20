# Evaluation method

## v2.5 preregistration (2026-10-20, before hard-test measurement)

This round measures `data/eval_hard.v2.5.jsonl`: the frozen v2.4 set plus 13
`subtle_supplement` cases (test 10 / dev 3) selected under
`data/annotation/v2.5/sampling_rules.json` with seed 20261021. No evaluated verifier has been
run on the hard test. The v2.4 metric definitions, alignment rules and bootstrap settings are
inherited unchanged; `eval/v25.py` scores saved predictions without provider calls.

* Report `all` (headline), `natural`, `conflict_supplement` and `subtle_supplement` with the
  same definitions; bootstrap each subset independently. `all` means all subsets in the
  selected split. The supplements intentionally change label prevalence; all-data precision is
  not a natural-population estimate.
* **Preregistered sensitivity:** rerun every primary metric after removing gold claims whose
  `doubt_category` is `suspected_wrong_label` or `c_vs_u_boundary`. Report primary and
  sensitivity results side by side. The sensitivity analysis removes claims, not cases; its
  intervals still resample complete cases. It never changes a gold label.
* **Preregistered groups:** by origin (`subtle` if any overlapping upstream fragment starts
  with Subtle, else `evident` if any starts with Evident, else `clean`) and by generator
  model. A case can appear in more than one origin group, so group `n_cases` is not a partition.
* `doubt_category` is a structured model classification over context, claim and fixed label.
  Categories are `agree`, `suspected_wrong_label`, `c_vs_u_boundary`, `partial_claim`,
  `evidence_not_found`. It is annotation-pipeline provenance, not a label and not a benchmark
  prediction.
* Scoring command after measurement is separately authorized:

```bash
uv run python -m eval.v25 --data data/eval_hard.v2.5.jsonl --split test \
  --predictions <saved-run.jsonl> --doubts data/annotation/v2.5/doubt_classes.jsonl \
  --out <new-report.json>
# Add --oracle only for a run generated from gold claims in their original order.
```

The CLI requires exactly the selected case IDs, including explicit error records for failures;
it records dataset/prediction/doubt hashes and refuses output overwrite. Hard-test measurement
remains **unmeasured**.

## v2.4 preregistration (2026-10-20, before hard-test measurement)

This round measures `data/eval_hard.v2.4.jsonl`. No verifier has been run on its hard test.
The following metrics are registered before freezing; historical synthetic results below do
not describe v2.4. `eval/v24.py` scores saved predictions without provider calls, reusing the
frozen alignment rules in `eval/scoring.py`. No alignment threshold is tuned in this round.

* **Primary: claim-level hallucination detection**, C+U positive, S negative, precision/recall/F1.
  An aligned C↔U prediction is a detection TP; a missed C/U is FN; predicted C/U on S is FP.
  Every unmatched C/U prediction (including duplicates) adds FP. Missing S does not count as TP
  or TN, so omission never creates successful detection. Provider errors count as empty output.
* **Three-label macro-F1**, equal mean of S/C/U F1. Missed gold contributes its label's FN;
  every unmatched prediction contributes its predicted label's FP. This explicitly penalizes
  extra claims, unlike the historical gold-only confusion macro-F1. No label is omitted when
  absent; zero denominators yield zero. Gold n appears beside every label; n<20 says “仅供参考”.
* **95% percentile confidence intervals** on detection P/R/F1, macro-F1 and per-label P/R/F1:
  resample complete cases with replacement, same number of cases per draw, 10000 replicates,
  NumPy default_rng seed 20261020. Repeated draws retain multiplicity and all claims of a case.
  Intervals describe sampling uncertainty conditional on these labels/alignment, not annotation
  correctness, generation variance, or performance on an unselected population.
* Report `all` (headline), `natural` and `conflict_supplement` separately with the same definitions;
  bootstrap each subset independently. Empty subsets have no metric. The supplement intentionally
  changes label prevalence; all-data precision is not a natural-population estimate.
  Here `all` means all subsets within the selected split (default `test`); `--split all` includes
  dev as well and must not be described as held-out performance.
* Answers with no upstream span annotations are called **“上游无标注回答”**. Report how many such
  cases have any model_doubts journal record (unique cases and records separately). Neither their
  SUPPORTED mapping nor their model evidence establishes independent human confirmation.

After measurement is separately authorized, score each saved run independently (do not pool runs
as independent cases), using a fresh output outside historical `results/`:

```bash
uv run python -m eval.v24 --data data/eval_hard.v2.4.jsonl --split test \
  --predictions <saved-run.jsonl> --out <new-report.json>
# Add --oracle only for a run generated from gold claims in their original order.
```

The CLI requires exactly the selected case IDs, including explicit error records for failures;
it records dataset/prediction hashes and refuses output overwrite. README must present all-data
and natural headline numbers together once measured. At freeze time both remain **unmeasured**.

**2026-10-19 v2.2 scoring correction:** the alignment guards and grouped metrics below are
implemented on `eval-v2`. Published summaries and historical numbers remain unchanged until the
rescore comparison is reviewed. No hard-test evaluation is authorised by this change.

How the three verifiers are measured, what every number means, and which of them can be trusted for
what. Dataset contents and labelling rules live in [DATASET.md](DATASET.md); the measured results are in
[REPORT.md](REPORT.md); the version-by-version history in [ITERATIONS.md](ITERATIONS.md).

## Dataset and splits

46 hand-authored cases / 150 gold claims, every line validated on load
(`uv run python -m eval.dataset data/eval.jsonl`):

| | dev | test | total |
|---|---|---|---|
| Cases | 26 | 20 | 46 |
| Gold claims | 89 | 61 | 150 |
| SUPPORTED / CONTRADICTED / UNSUPPORTED | 49 / 30 / 10 | 42 / 13 / 6 | 91 / 43 / 16 |

**Split policy:** `dev` is read as often as needed while iterating (prompts, models, thresholds).
`test` is read once, at the end, by `make eval-test`, with the configuration chosen on dev. Model choice,
prompt version and any threshold were all decided on dev; the label audit and the two held-out label
corrections are documented as exceptions in
[ITERATIONS.md](ITERATIONS.md#dataset-calibration-also-eval-driven).

## Harness

```bash
make eval-dev     # baseline + minimal + optimized on dev, 1 run
make eval-test    # held-out split, 3 runs end-to-end + 3 runs oracle → results/final_e2e, results/final_oracle

uv run python -m eval.run --methods minimal optimized --split dev --runs 3 --prompt-version v3 --out results/dev-v3-x3
uv run python -m eval.report results/dev-v3-x3                  # comparison table
uv run python -m eval.report results/dev-v3-x3 --failures optimized   # per-case error listing
# Recompute only in an independent copy until changed historical numbers have been reviewed:
cp -R results/dev-v3-x3 /tmp/dev-v3-x3-rescore
uv run python -m eval.run --rescore /tmp/dev-v3-x3-rescore
```

`eval/run.py` writes one JSONL per run (one line per case: `id`, `claims`, `meta`, or `error`) plus
`summary.json` with every metric. `eval/metrics.py` contains pure functions over those files — no LLM
calls anywhere in the reporting path. `eval/report.py` renders the markdown table and the failure list.

**Rescore mode** recomputes `summary.json` from the JSONL already on disk. Metric definitions change far
more often than predictions do, and re-running a paid evaluation to change a denominator is the wrong
trade. Rescoring **refuses** a run whose case ids do not match the current dataset: such a run predates a
dataset change, and scoring it would produce numbers that were never measured.

## Alignment: how a predicted claim meets a gold claim

Predicted claims use `rapidfuzz.token_set_ratio` with threshold 60. Before the Hungarian
assignment, a candidate pair is excluded when its numeric sets or explicit negation presence differ.
Only admissible edges enter the assignment: it maximises matched cardinality first, then total
similarity. This prevents a blocked or sub-threshold edge from stealing a valid match.

- Numbers retain standalone signs and dotted versions; thousands separators are removed (`1,000`
  and `1000` agree). Hyphens in identifiers such as AES-256 and date separators are not negative signs.
  Number words, unit conversion and implicit quantities are not normalised.
- Explicit English negation includes not/no/never/cannot/without/neither/nor and n't contractions,
  including curly apostrophes. Presence is compared; negation scope and double negation are not parsed.
- `guard_rejected_pairs` counts **all threshold-passing candidate edges rejected by the guards**,
  not just selected assignment edges. Multiple rejected edges can involve the same claim, so this
  count need not equal omissions or extra predictions.
- Unmatched gold is `MISSED`; unmatched predictions are counted as extra outputs. An unmatched
  prediction with an admissible edge is a *lexical duplicate candidate*; the remaining unmatched
  outputs are counted as added predictions. These labels do not prove semantic duplication/novelty.
- `oracle=True` still compares gold-fed claims by position, skips alignment, and records zero guard
  rejections. Oracle results remain a label-classification diagnostic.

The tests include changed and missing numbers, negation flips, condition deletion that removes a
negator, partial compound coverage that drops a number, duplicate outputs and new outputs. **The
last two guarded omissions do not establish a general solution for dropped conditions or partial
claims.** If number sets and negation presence remain unchanged, token-set similarity can still
accept a non-equivalent statement. Automatic alignment remains approximate and requires the planned
human semantic audit. The guard can also reject valid paraphrases (e.g. a number word vs a digit).

## User-approved scoring units (2026-10-19)

`data/eval.jsonl` remains byte-identical. Its sibling `data/eval.scoring_units.jsonl` is a separate,
append-only approval registry. Evidence additions are appended as complete revisions linked to the
preceding approval line by `supersedes_sha256`; earlier approvals are never overwritten. A revision
may update evidence, but cannot silently change approved unit texts or verdicts. The latest active
units must each have nonempty evidence that is an exact substring of the indexed context. The user
has approved two SUPPORTED units for the compound parent
in `kafka-retention-11`: the default retention-check interval is 300000 milliseconds, and deletion
is not immediate. This is a scoring decomposition, not a replacement of the original gold record.

The loader checks the full dataset SHA256, case ID, exact parent text/verdict, explicit user approval,
unique nonempty unit texts, and SUPPORTED labels for parent and units. It refuses stale/duplicate
registrations and non-SUPPORTED units; this first implementation does not infer sublabels for C/U
parents. Unregistered gold claims keep their original scoring units. Registration metadata lives
outside dataset JSON and is not silently imported from model-produced case fields.

Scoring first preserves strict one-to-one matches to complete original parents. For still-unmatched,
registered parents only, it matches unused predictions to the approved units using **the same numeric,
negation and similarity checks**. Every prediction is used once across both stages. A parent is
covered only if all its units match; all matched child labels must be SUPPORTED for it to be correct.
A wrong child label makes that parent wrong (C takes precedence over U); a missing child makes it
MISSED. Correctly aligned parts of an incomplete parent still count as used predictions, but earn
no complete-parent coverage or accuracy credit. No matching objective uses predicted verdict labels.

- Gold count, all-gold accuracy, confusion and grouped metrics stay at the original **parent** level.
- Decomposition recall = fully covered parents / original gold parents. `matched_pairs` now counts
  fully covered parents, including approved combinations, rather than individual child matches.
- Decomposition precision = **used predictions / all predictions**. `used_predictions` exposes this
  separate numerator; used child outputs are not penalised as extra predictions. Remaining extra,
  duplicate-candidate and added-candidate counts exclude all used outputs.
- Guard counts include rejected high-similarity edges in both the direct and child stages. They remain
  diagnostic candidate-edge counts, not rejected-parent or semantic-error counts.
- A split prediction's citations are compared **only with its matched unit's evidence**; an exact
  quotation from the other unit is not automatically accepted. Whole-parent and oracle predictions
  use the union of the parent's approved unit evidence; ordinary unregistered parents retain their
  original gold evidence. The base dataset is not rewritten.
- A predicted quotation must exactly equal its declared context slice before it can earn strict or
  passage credit. Invalid/missing quote text, bad offsets and wrong indices stay in the prediction
  denominator but get zero credit. There is no normalised/fuzzy repair in citation scoring.
- Citation precision counts distinct citations per predicted claim, retaining their attribution.
  Recall deduplicates reference spans within each parent and requires a >=50% overlap from a valid
  citation assigned to that reference's unit (or the full parent). Cross-unit swapping cannot gain
  credit just because the two quotes occur in the same passage. Removing a citation reduces recall.
- `citation_counts` exposes predicted/hit, gold/gold_hit and invalid-final-citation counts. The invalid
  count is separate from `raw_citation_invalid_rate`, which still comes from the original run metadata.
- Oracle keeps original parent order, labels and decomposition; no lexical guard or child expansion
  is applied. Its citation metrics can change when the approved reference evidence is completed,
  just like end-to-end metrics. Reports disclose the full registry SHA256; freeze the append-only
  registry alongside the scoring code.

For Kafka, the split outputs match the number unit and negation unit separately, cover one parent,
and earn one parent point. `600000` cannot match the number unit; `Deletion is immediate` cannot
match the negated unit. Keeping the original complete sentence also remains a valid direct match.
The first unit's reference is `log.retention.check.interval.ms defaults to 300000 milliseconds`;
the second is `segments are not deleted the moment a limit is exceeded`. Both are exact substrings
of passage 1. This completes this parent's scoring evidence without changing its labels, answer or
context. There is no branch for the Kafka case ID or a particular model in the scoring implementation.

## Metrics

| Metric | Definition | Read it as |
|---|---|---|
| Answer-level hallucination P/R/F1 | positive class = "this answer contains at least one non-SUPPORTED claim" | does the service flag a bad answer at all — coarse but the user-facing question |
| Claim accuracy (all gold claims) | correct verdicts ÷ gold claims, missed claims counted wrong | the headline number |
| Claim accuracy (matched only) | correct verdicts ÷ matched pairs | verdict quality without decomposition loss |
| Macro-F1 (3 verdicts) | unweighted mean of per-label F1 | the number that exposes a method collapsing on one class |
| F1 SUPPORTED / CONTRADICTED / UNSUPPORTED | per-label P/R/F1 over the confusion matrix | which boundary the method gets wrong |
| Decomposition recall / precision | fully covered parents ÷ gold parents; used predictions ÷ all predictions | incomplete parents lower recall; unused output lowers precision |
| Guard-rejected candidate pairs | threshold-passing candidate edges rejected by numeric / negation checks across direct and child stages | a diagnostic edge count, not a count of semantic errors |
| Missed / extra / duplicate / added counts | unmatched gold; unmatched predictions; extra predictions with an admissible edge; remaining extra predictions | all counts are approximate lexical diagnostics |
| **Answer sentence coverage** | share of the answer's sentences matched by some predicted claim (≥60 token-set) | did every sentence of the answer reach the verifier — measured against the answer, no labels needed |
| **Fused claim rate** | share of predicted claims that carry ≥2 distinctive content words from each of two different answer sentences | did a claim swallow two sentences into one, hiding the one it swallowed. A claim that *is* an answer sentence scores zero by construction; the earlier similarity-based version had an ~11 % false-positive floor (the baseline scored 0.113 while being unable to fuse) |
| Citation precision / recall | exact valid predicted quotes overlapping their assigned unit/parent evidence; recall additionally needs ≥50 % gold-span coverage | evidence-region matching, not a general proof of semantic sufficiency |
| Citation precision / recall (right passage) | same question, credit if the cited passage is one of the annotated evidence passages | the annotation-taste-free version of the previous row |
| Raw citation invalid rate | invalid citations ÷ raw citations **before** repair | how sloppy the model is on its own — the repair must not hide this |
| Latency p50 / p95 | per-case wall clock at `--concurrency 4` | not a throughput measurement |
| Input / output tokens per case, calls per case, cost per case | from `meta`, summed over retries separately | cost proxy; cost = tokens × the `.env` prices |

## Grouped claim metrics

`summary.json` now carries `groups` and the markdown report renders each dimension with explicit
case and gold-claim denominators, matched count, all-gold/matched accuracy, recall, per-label P/R/F1,
macro-F1 and confusion counts. Every group uses the **same full-case parent outcome** as the main table;
there is no second alignment on a filtered gold subset. Failed/missing predictions count as missed
gold within each applicable group. Groups contain cases with at least one gold claim; a case can
appear in both claim-level multi-passage groups.

| Dimension | Rule |
|---|---|
| task | ragtruth_summary → Summary, ragtruth_qa → QA, ragtruth_data2txt → Data2txt; otherwise unknown |
| difficulty | case-level tags + difficulty_tags; subtle takes priority over evident for mixed cases; otherwise clean / unknown |
| context_length_words | whitespace word count of final passages: 0–399 / 400–799 / 800+ |
| multi_passage | true only for an explicit gold-claim multi_passage tag; case tags or multiple evidence passages alone do not establish complementary evidence |

Group precision over *predicted* claims is not reported: unmatched outputs have no reliable
claim-level group assignment. Historical synthetic cases without RAGTruth metadata stay unknown;
this scoring change does not invent task or evident/subtle labels. Preserved summaries without new
metrics render N/A in those rows until approved rescoring replaces them.

## Oracle mode: separating "judged wrongly" from "checked the wrong text"

`--oracle` feeds the gold claims in and skips decomposition. This is the single most informative switch in
the harness, because it splits the error budget in two:

| | dev | test |
|---|---|---|
| baseline, end-to-end → oracle | 0.382 → 0.494 | 0.590 → 0.705 |
| minimal, end-to-end → oracle | 0.989 → **1.000** | 0.984 → 0.978 |
| optimized v3, end-to-end → oracle | 0.989 → **1.000** | 0.984 → **1.000** |

Reading: for both LLM verifiers on dev, **verification is solved** once the claims are given, so the
end-to-end error is decomposition; for the baseline the bottleneck is the opposite (lexical matching
cannot decide entailment, and its sentence splitter already recovers 0.775 of the gold claims). That
attribution is what directed the whole v3/v4 iteration cycle, and it is only visible because the oracle
run exists.

## Adding a metric

1. add the counter to `eval/metrics.compute` (pure function, no I/O);
2. add a row to `eval/report.ROWS`;
3. copy every historical run to a separate directory, run `--rescore` there, compare existing numeric
   fields, and stop for user review if published numbers change — no provider calls or overwrite.

That is how answer sentence coverage and the fused-claim rate were added when prompt v4 needed them
measured, and how the cost column was filled in after real prices replaced the placeholder zeros.

## Measurement caveats

* **150 claims, one annotator.** Differences below ~5 points on one split are noise; the final test
  report therefore shows mean ± std over 3 runs, and the dev hill-climb repeats runs before deciding.
  A model-based read-back audit agrees with 149/150 labels (147/150 for the single call) — a second
  reader, not a second human annotator.
* **Multiple comparisons.** Five prompt versions and two models were compared on the same dev split.
  The pinned configuration (v3, `deepseek-v4-pro`) is the one that won on 3-run means; the losers are
  kept in the log, including the ones whose single-run advantage did not reproduce.
* **Cost is computed, not billed**, from prices snapshot-dated in `docs/ITERATIONS.md` and configured in
  `.env`; every input token is billed at the cache-miss rate, so the column is an upper bound. It is
  comparable within one client transport, because the two transports report usage differently (fixed
  in `_input_volume`, still worth knowing when reading historical artifacts).
* **The dataset is easier than intended** for a strong model: after the hardening pass, methods sit at
  0.97–0.99 claim accuracy on dev. The report therefore leans on verdict-boundary F1, citation rows,
  sentence coverage, calls and cost — not on claim accuracy alone.
* **The empty-context cases are solved by construction** (no passages ⇒ UNSUPPORTED), so they inflate
  UNSUPPORTED recall for every method and test robustness, not discrimination.

## RAGTruth v2.3 references without located evidence

`GoldClaim.label_source=ragtruth_human` requires explicit `evidence_status=exact|none`.
`none` requires empty evidence and permits S/C labels without a reference quote. These claims
remain in verdict accuracy, decomposition and confusion denominators, but both their gold evidence
and their aligned predictions' citations are excluded from citation precision/recall (strict and
passage variants). `exact` requires nonempty verbatim evidence. Historical references keep their
existing evidence requirement. The aggregate raw-provider citation-invalid diagnostic is unchanged.
No historical result directory is rescored or overwritten by this change.
