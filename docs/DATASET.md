# Evaluation dataset

`data/eval.jsonl` — 46 hand-authored cases (26 `dev`, 20 `test`), 150 gold claims.
Every line is validated on load; an invalid dataset refuses to run (`python -m eval.dataset data/eval.jsonl`).
How these cases are turned into numbers: [EVALUATION.md](EVALUATION.md#metrics).

## What a case is

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
