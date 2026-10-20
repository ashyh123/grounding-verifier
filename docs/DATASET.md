# Evaluation dataset

## Current measurement target: RAGTruth v2.6 (response-level)

The current target is **`data/eval_ragtruth_resp.v2.6.jsonl`**: 210 RAGTruth responses, 30 dev / 180
test, 10 dev and 60 test per task (Data2txt / QA / Summary). The test split has 62 positive
responses (at least one upstream hallucination span); dev has 9. The answer-level unit is the
response, not an atomic claim.

**Sampling.** The pool is the upstream RAGTruth `test` split with `quality=good`, all six upstream
generators, and the natural label distribution. There is no minimum length and no GPT-share target —
those were v2.2–v2.5 devices for making an adversarial claim-level set and would distort this one.
One response is drawn per `source_id`; dev and test never share a near-duplicate group. The sample
excludes all 63 v2.x cases and their 5-gram Jaccard ≥ 0.8 groups, near-duplicates of the old
`data/eval.jsonl`, and legacy project IDs. The technical caps are the maximum observed in v2.5
(context ≤ 1626 words, answer ≤ 304 words); 6 answers were excluded over the answer cap and 0
contexts over the context cap. Sampling used seed `20261022` and did not read labels; the rules were
committed before the draw. Counts and the full exclusion log:
[selection-stats.md](../data/annotation/v2.6/selection-stats.md).

**Gold.** `gold_response` is true iff the upstream response has at least one human-marked
hallucination span. `gold_sentences` is produced by the deterministic splitter in
`annotation/v26/sentences.py`; a sentence is hallucinated iff it overlaps an upstream span. No model
participates in gold construction — no decomposition, no evidence location, no label mapping.
`source_labels` keeps the upstream spans and their Evident/Subtle and Conflict/Baseless types for
grouping. Context passages may only lose `passage N:` markers or leading/trailing whitespace, and
every such change is recorded in `passage_map`; the answer is never edited.

**Known limitation.** Upstream annotation can miss hallucinations. An answer with no upstream span
is called **“upstream-unannotated”**, not “clean”; no human review was added. This noise is shared
with other RAGTruth users and can be compared externally, but it no longer stacks our own claim
splitting and overlap mapping on top.

Statistics (positives are responses with at least one upstream span):

| Task | dev | test | test positives |
|---|---:|---:|---:|
| Data2txt | 10 | 60 | 40 |
| QA | 10 | 60 | 8 |
| Summary | 10 | 60 | 14 |
| **Total** | **30** | **180** | **62** |

The v2.6 freeze is [data/annotation/v2.6/freeze.json](../data/annotation/v2.6/freeze.json); verify
it with `uv run pytest -q tests/test_v26_freeze.py`. The dev threshold calibration and cost estimate
are in [p2-dev-report.md](../data/annotation/v2.6/p2-dev-report.md); the test measurement and its
stop-condition check are in [p4-test-report.md](../data/annotation/v2.6/p4-test-report.md).

## Exploratory: RAGTruth v2.5 claim-level

v2.5 is retained as exploratory analysis, not as the current target. v2.6 uses new responses with no
id or source overlap; the verifier code and prompt are unchanged.

v2.5 used **`data/eval_hard.v2.5.jsonl`**. It keeps the frozen v2.4 cases and adds 13
`subtle_supplement` cases (test 10 / dev 3) selected under
`data/annotation/v2.5/sampling_rules.json` with seed 20261021. `data/eval_hard.jsonl` remains
the historical v2.3 dataset at commit **c78d411**, and `data/eval_hard.v2.4.jsonl` remains the
v2.4 dataset at **cbccac9**; neither is overwritten or redirected on disk.

The v2.5 changes were based only on label distribution and annotation-pipeline diagnostics.
When the sample was selected, **no evaluated verifier had been run on the hard test**; the v2.5 test
was measured later, and its results are exploratory (see [REPORT.md](REPORT.md)), not the
current headline. The selection
pool is RAGTruth upstream `train` (quality=good, at least one Subtle Conflict) plus the
remaining qualified upstream-`test` candidates. Selected cases record `upstream_split`; all 13
selected here came from upstream `train`. The sample excludes legacy project IDs/source groups,
existing v2.4 source IDs and near-duplicate groups, and takes one response per source_id and
per connected near-duplicate component. Task quotas are Summary test 4 / dev 1, QA test 3 / dev
1, Data2txt test 3 / dev 1. The GPT-4/GPT-3.5 target is at least half; the realized sample has
7 GPT cases out of 13. No model sets a label.

Every claim carries `overlapping_source_labels`, recomputed from its exact `answer_spans` and
the upstream human fragments. The verdict must replay from those overlaps with Conflict
precedence, then Baseless, else SUPPORTED. The v2.3 merge had dropped this field on the
original 30 cases; v2.5 restores it without changing any label. A unit test replays the rule
for every gold claim.

`doubt_category` (`agree`, `suspected_wrong_label`, `c_vs_u_boundary`, `partial_claim`,
`evidence_not_found`) is recorded for every existing doubt and every C/U claim, including the
new cases. It is used only for the preregistered sensitivity analysis; it never changes a gold
label. “上游无标注回答” still means only that RAGTruth provided no marked hallucination span;
it does not establish that the answer is correct.

Statistics, exclusions, lengths, evidence coverage, doubt categories and target checks are in
[the v2.5 report](../data/annotation/v2.5/final_report.md) and
`data/annotation/v2.5/audit.json`. Retained counts: 63 例 / 782 条主张
(S701/C37/U44)；test 45 例 / 537 条主张 (S483/C27/U27)，natural 30 例 / 382 条主张，
conflict_supplement 20 例 / 256 条主张，subtle_supplement 13 例 / 144 条主张。 The target “test Subtle Conflict 来源的 C ≥ 8” was **not met**:
7 retained (6 new + 1 natural). The unchanged partial_overlap rule excluded 11 new claims,
8 of them C, including conflict-bearing statements. No cases were added and no rule was
relaxed.

The v2.5 freeze is `data/annotation/v2.5/freeze.json`;
verify it with `uv run python -m annotation.v25.freeze --check`. Offline replay is
`uv run python -m annotation.v25.merge --check`. The v2.4 freeze remains valid at `cbccac9`;
v2.5 explicitly authorizes the `annotation/README.md` status update and the minimal v2.4 freeze
validation adaptation. Preregistered metrics and the saved-run scoring command are in
[EVALUATION.md](EVALUATION.md). The v2.5 test was measured after the freeze; its results are
exploratory and are not the current headline.

## Historical target: RAGTruth v2.4

This round used **`data/eval_hard.v2.4.jsonl`**. The text below records the v2.4 state; exact
v2.3 texts remain available at c78d411.

v2.4 changes are based only on label distribution and evidence-pipeline diagnostics.
**No evaluated verifier has been run on the hard test during this workflow**, so these changes
do not use test performance to tune the dataset. The c78d411 dataset, annotation artifacts,
scoring/verifier code and freeze are retained. This document and EVALUATION.md receive the
explicitly required v2.4 additions; their exact v2.3 texts remain available at c78d411.

The version keeps the 30 original cases as `natural`, repairs passage indices with literal
quote replay and an explicit numbered prompt, and splits the ten excluded parent claims at
upstream annotation boundaries without sending label types to the drafting model. It adds
20 fixed `conflict_supplement` cases under preregistered task/split/length/deduplication rules.
The user explicitly removed only the supplement's infeasible GPT-share minimum; all other
selection rules remain fixed. Both annotation roles use mimo-v2.6-pro. No model sets labels.

Statistics, exclusions, doubts, lengths, evidence coverage and target checks are in
[the v2.4 report](../data/annotation/v2.4/final_report.md) and `data/annotation/v2.4/audit.json`.
The report separates offline index repair from the 98 original-none new-prompt calls;
existing exact claims were not rerun. Every original retained claim/text/label is preserved,
and new split children have new IDs plus `derived_from`. Retired parents are listed separately
from their replacement children's retained/excluded counts. No replacement cases are sampled.
If a recovered child has exactly the same text and human label as an existing gold claim and
their literal answer spans overlap, retain the existing gold and attach `merged_derivations`.
The child remains in the recovery journal and audit but does not count twice. Repeated text
at different answer positions stays separate; this rule uses no semantic model judgment.

“上游无标注回答” means only that RAGTruth provided no marked hallucination span. Counts of such
cases with model_doubts are logged in the audit; there is no independent human confirmation.
The old all-retained-S count is not a count of verified correct answers. Evidence coverage
measures exact textual presence, not whether the quote semantically proves the claim.

The new freeze is `data/annotation/v2.4/freeze.json`; verify it with
`uv run python -m annotation.v24.freeze --check`. To rederive mapping/evidence and compare the
dataset/audit without model calls, run `uv run python -m annotation.v24.merge --check`.
The original freeze's hashes for the two updated docs refer to their historical c78d411 text;
the v2.4 freeze checks that historical text and pins the new documentation separately.
Hard-test measurement awaits separate instructions. Preregistered metrics and the saved-run
scoring command are in [EVALUATION.md](EVALUATION.md).

`data/eval.jsonl` — 46 hand-authored cases (26 `dev`, 20 `test`), 150 gold claims.
Every line is validated on load; an invalid dataset refuses to run (`python -m eval.dataset data/eval.jsonl`).
How these cases are turned into numbers: [EVALUATION.md](EVALUATION.md#metrics).

## v2.6 response fields

| Field | Meaning |
|---|---|
| `id` | Stable response id (`ragtruth-…`) |
| `split` | `dev` or `test`; v2.6 dev and test share no near-duplicate group |
| `task` | `Data2txt`, `QA` or `Summary` |
| `generator_model` | One of the six upstream RAGTruth generators |
| `context_passages` | Upstream passages after the allowed marker/whitespace transforms |
| `passage_map` | Records any passage transform; the answer itself is never edited |
| `generated_answer` | The upstream model answer, verbatim |
| `source_labels` | Upstream spans (`start`, `end`, `text`, `label_type`, `meta`) |
| `gold_response` | True iff `source_labels.labels` is non-empty |
| `gold_sentences` | Deterministic sentence tiles with `start`, `end`, `text`, `hallucinated` |
| `provenance` | Upstream split/source/response identifiers and the task type |

Machine-enforced invariants (`eval/v26.py::validate_rows`): unique ids; `split` in {dev, test};
`gold_response` agrees with the upstream spans; every span's `answer[start:end]` equals its `text`;
and `''.join(sentence texts)` tiles `generated_answer` exactly.

## Historical synthetic case fields

The sections from here through “Known limitations” describe the original 46-case synthetic set, not
v2.6. v2.6 takes its labels directly from upstream spans and does not use these claim-labelling
rules.

| Field | Meaning |
|---|---|
| `id` | Stable case id, used in result files, failure listings and the iteration log |
| `split` | `dev` (allowed during hill-climbing) or `test` (held out until the final run) |
| `tags` | Case-level failure bucket, used for per-tag accuracy in the report |
| `context_passages` | 0–9 short technical passages, documentation style |
| `generated_answer` | A plausible assistant answer over those passages, 0–11 factual claims |
| `gold_claims` | Reference atomic claims with verdict, optional per-claim tag, verbatim evidence |
| `notes` | Why the case exists / what it traps |

Machine-enforced invariants (`eval/dataset.py::validate`):

* unique ids; `split` in {dev, test}; every tag in `ALLOWED_TAGS`
* `UNSUPPORTED` gold claims have **no** evidence; `SUPPORTED`/`CONTRADICTED` have **at least one**
* every evidence `index` is in range and every evidence `quote` is a **verbatim substring** of that passage

## Labelling rules

Verdicts follow the assignment. The decision order that makes the labels reproducible:

1. **CONTRADICTED** — some part of the claim is incompatible with the sources: a different number
   or unit, an inverted negation, a swapped condition (conditional claim vs unconditional source),
   an inverted comparison, a different entity, wrong version or date, or a quantifier that the
   source does not support ("all"/"always" where the source says "by default").
   One contradicted part decides the whole claim.
2. **SUPPORTED** — every part is stated or directly entailed by the sources, and nothing conflicts.
   Paraphrase, synonyms, and equal numbers written differently ("1,000" = "1000" = "approximately 1000")
   count as support.
3. **UNSUPPORTED** — the sources are silent about the claim or about one of its parts, and nothing
   conflicts. Silence stays UNSUPPORTED even when the claim is true in the real world
   (`redis-aof-02`, `nginx-upstream-12`), and it does not become CONTRADICTED just because the claim
   sounds wrong (`dns-ttl-13`, `replica-lag-18` (test)).

**Gold claims are atomic, and so is the claim contract.** "A topic's partition count can be
increased and can also be decreased" is two claims in the reference, because the decomposition
contract tells the verifier to split conjunctions. An earlier revision bundled such pairs into one
gold claim and was fixed: it unfairly punished the optimized path for doing what its own prompt
asks, and the two halves can carry different verdicts.

Edge cases that are labelled explicitly:

* **Empty context** (`empty-context-16`, `empty-context-19` (test)): nothing can be grounded, so every claim
  is UNSUPPORTED and carries no evidence. These cases check that the service does not crash or call
  the model to verify anything.
* **No factual claims** (`no-claims-17`): a conversational answer; the correct output is an empty
  claims list, not a fabricated claim.
* **Multi-sentence evidence** (`kafka-partitions-10`, `k8s-probes-03` (test), `k8s-limits-28`): one claim
  may need several sentences, sometimes from different passages.

## Difficulty calibration

The first revision of this dataset (37 cases, short passages, claims that near-paraphrase a single
source sentence) turned out to be **saturated**: every method scored 0.96–0.98 claim accuracy and the
methods could not be told apart. The measured response was to add a harder half with the failure
modes that actually distinguish systems:

| Hard-case recipe | Why | Cases |
|---|---|---|
| Distractor sentences carrying the same numbers/entities | lexical matching must not be enough | `docker-signals-24`, `pg-hba-order-25` |
| Parameter soup (5 similar settings in 3 passages, one value altered) | retrieval must land on the right sentence | `pg-autovacuum-tuning-23`, `kafka-autocommit-26` |
| Conditions in subordinate clauses, reversed scope | the sentence must be read to the end | `redis-expiry-replica-30`, `python-set-order-29` |
| Entity pairs crossed in both directions (stop/kill, 137/143, CPU/memory) | the failure is detected only if the entity is checked | `docker-signals-24`, `k8s-limits-28` |
| Long context, long answer (9 passages, 11 claims) | single-call architectures strain | `redis-cluster-long-31` |

## Coverage

Case ids are from the `dev` split unless marked `(test)`.

| Bucket (tag) | Cases | Examples |
|---|---|---|
| `supported` (whole answer grounded) | 37 | `pg-btree-05` (test), `sql-join-09` (test) |
| `paraphrase` | 4 | `sqlite-wal-01`, `raft-election-14` (test) |
| `number_off` | 6 | `redis-aof-02`, `docker-exit-05`, `pg-checkpoint-20` (test) |
| `unit_change` | 3 | `systemd-restart-11`, `cache-s-maxage-10` (test) |
| `negation_flip` | 10 | `python-gil-08` (test), `http-cache-07`, `redis-aof-rewrite-27` |
| `condition_swap` | 6 | `pg-autovacuum-03`, `jwt-claims-14`, `prometheus-counter-17` (test) |
| `quantifier_shift` | 5 | `redis-maxmemory-04` (test), `pg-mvcc-22` (test), `kafka-autocommit-26` |
| `comparison_flip` | 9 | `tcp-slowstart-06` (test), `http2-multiplex-16` (test), `numpy-views-15` |
| `entity_swap` | 3 | `k8s-probes-06`, `docker-signals-24`, `k8s-limits-28` |
| `temporal_version` | 3 | `tls-0rtt-08`, `pandas-cow-15` (test) |
| `extrinsic` (plausible, unstated) | 8 | `dns-ttl-13`, `replica-lag-18` (test), `redis-cluster-long-31` |
| `extrinsic_true_world` (true outside the context) | 2 | `redis-aof-02`, `nginx-upstream-12` |
| `multi_passage` (evidence spans passages) | 11 | `kafka-partitions-10`, `k8s-probes-03` (test), `k8s-limits-28` |
| `empty_context` | 2 | `empty-context-16`, `empty-context-19` (test) |
| `no_claims` | 1 | `no-claims-17` |
| `mixed` | 3 | `sqlite-wal-01`, `py-asyncio-04`, `redis-cluster-long-31` |

## Statistics

| | dev | test | total |
|---|---|---|---|
| Cases | 26 | 20 | 46 |
| Gold claims | 89 | 61 | 150 |
| SUPPORTED | 49 | 42 | 91 |
| CONTRADICTED | 30 | 13 | 43 |
| UNSUPPORTED | 10 | 6 | 16 |
| Distorted (non-supported) claims | 40 | 19 | 59 |
| Passages per case | 9 (1×), 3 (2×), 2 (22×), 1 (1×) | 3 (1×), 2 (17×), 0 (2×) | 2.11 avg |
| Claims needing ≥2 evidence quotes | 3 | 0 | 3 |
| Longest answer | 11 claims / 869 chars | 4 claims / 313 chars | — |

`test` is the held-out split: it is only read by `make eval-test` and never used to choose a prompt,
a model or a threshold.

## Known limitations

* **Single annotator, authored by the same person who wrote the verifier.** The labels are
  self-consistent and machine-validated for form (verbatim quotes, invariants), not for judgement.
  There is no inter-annotator agreement study; a real benchmark would measure one.
  A whole-dataset read-back audit (every gold claim re-judged in oracle mode) agrees with **149/150
  labels** for the per-claim verifier and 147/150 for the single call; the one disagreement is the
  deliberate trap case. That is a model-based second read, not a human annotator, so it raises
  confidence without establishing inter-annotator agreement (docs/ITERATIONS.md).
* Three items were corrected because the eval showed them to be bad benchmark items rather than model
  errors: `kafka-partitions-10` (a label that contradicted the sources, found because both verifiers
  rejected it), `kafka-retention-11` (test) (answer wording that conflated "eligible for deletion" with
  "deleted") and `http-retry-21` (test) (a universal claim the sources arguably implied false). Each is
  recorded in the case's `notes` and in docs/ITERATIONS.md, including the pre- and post-audit numbers.
  A fourth contested label, `prometheus-counter-17` (test), was deliberately kept against the model.
* 150 claims is enough to rank three methods on this domain, not to publish a number. Differences
  below ~5 points on a single split should be treated as noise; the final test report therefore shows
  mean ± std over 3 runs.
* **The benchmark proved easier than intended for a strong model**: after the hardening pass above,
  the best methods still sit at 0.97–0.99 claim accuracy on dev. Making it harder still would mean
  either ambiguity (bad labels) or needle-in-haystack contexts that the service does not target.
  The report therefore leans on the metrics that still separate the methods — citation precision,
  decomposition, calls per case, latency — rather than on claim accuracy alone.
* Technical documentation in English only; no multi-hop arithmetic, no tables, no non-English text.
* The empty-context cases are solved by construction (no passages ⇒ UNSUPPORTED), so they inflate
  UNSUPPORTED recall for every method that follows the contract. They test robustness, not discrimination.
* UNSUPPORTED is 16 of 150 gold claims (10.7 %), so per-label F1 for it rests on few examples, and part of
  it comes from the empty-context cases above.
* 11 cases are tagged `multi_passage` because their evidence is spread across passages, but only 3
  individual gold claims need evidence from two or more passages. Cross-passage synthesis at the claim
  level is under-tested.
* `UNSUPPORTED` is the thinnest class (16 claims), so its F1 is the noisiest column of the report.
* Answers are written to be verifiable from the passages, i.e. claim decomposition is never
  adversarial here; a claim that cannot be checked without world knowledge is not in the set.

## Historical RAGTruth v2.3 human-label pipeline

The new hard dataset uses labels mapped directly from upstream RAGTruth human annotations,
without a second human review: Conflict overlap → CONTRADICTED, Baseless overlap → UNSUPPORTED,
no overlap → SUPPORTED, with Conflict taking precedence. Every retained reference will carry
`label_source: ragtruth_human`. Models only decompose answers and locate evidence; they cannot
assign or modify these labels. Upstream omissions and mistakes therefore remain possible.

A partially overlapping claim is excluded if more than 20 answer-span characters lie outside the
union of upstream fragments. A case is excluded if more than 30% of its claims are excluded.
An upstream hallucination fragment overlapping no drafted claim requires one fresh decomposition
by the same drafting model, without upstream labels in its prompt; if still uncovered, exclude the
whole case as `source_label_uncovered`. No replacement cases are sampled. These exclusions may
bias the retained dataset toward easier examples; reports must disclose the removed counts.

For S/C claims, source evidence must be an exact substring, with offsets computed by the script.
If no exact evidence is found, keep the human label with `evidence_status: none`; score its verdict
accuracy but exclude it from citation precision and recall. An `exact` match establishes textual
presence, not semantic sufficiency. Model doubts are logged, never converted into label changes.
The original synthetic dataset retains its existing validation and scoring rules.

The user approved expansion after the five-dev-case pilot. `data/eval_hard.jsonl` now contains
all 30 selected cases and 368 retained claims (332 S / 6 C / 30 U), after excluding 10 partial-overlap
claims; no whole cases were excluded or replaced. Dev: cases=10, claims=118 (102 S / 2 C / 14 U);
test: cases=20, claims=250 (230 S / 4 C / 16 U). Test negative-label counts fall below the earlier
30-per-class expectation; this is not evidence of a sufficiently hard or balanced benchmark.
All ten exclusions removed C/U claims, demonstrating the bias risk described above.

Exact references were located for 240/338 S/C claims (71.0%); the remaining 98 S/C references have
no located evidence. The 35 doubt-log records comprise 31 model doubts/not-found reports and four
unusable-output diagnostics; the latter are explicitly separate from semantic label doubts.
“上游无标注回答” number 2 dev / 5 test; all-retained-S answers number 4 / 8 and may still
contain excluded hallucinated assertions. Multi-passage evidence counts are 22 / 42; these do not
establish that multi-passage reasoning is necessary. Audit and freeze metadata live under
`data/annotation/`. See the [final statistics](../data/annotation/full-v2.3/report.md).
No hard-test verifier has been run as part of this annotation/freeze workflow.
See [annotation workflow](../annotation/README.md).
