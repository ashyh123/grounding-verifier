# Documentation — version 2

Documentation set for the citation grounding verifier. **Docs v2, 2026-10-17.** Supersedes docs v1
(the single incrementally-grown `README.md` from earlier the same day).

The rule this edition is built on: every document has one job, the numbers live in exactly one place,
and nothing in the docs is transcribed by hand if a script can regenerate it.

## Index

| Document | What it answers | Audience |
|---|---|---|
| [../README.md](../README.md) | What is this, how do I run it, what does it cost me, where do I go next | someone arriving at the repo |
| [ARCHITECTURE.md](ARCHITECTURE.md) | How does `POST /verify` work, where is the trust boundary, how do I extend it | engineer reading or modifying the code |
| [EVALUATION.md](EVALUATION.md) | How is it measured, what does each metric mean, how do I reproduce or re-score | reviewer judging the benchmark |
| [REPORT.md](REPORT.md) | What were the results, what failed, what may not be concluded | reviewer judging the claims |
| [DATASET.md](DATASET.md) | What is in the 46 cases, how were they labelled, how hard are they | annotator or reviewer auditing the data |
| [ITERATIONS.md](ITERATIONS.md) | What was tried, what was kept, what was reverted and why | anyone judging the development process |

Reading order for a first pass: README → REPORT (results) → ITERATIONS (how they were reached) →
EVALUATION (whether to believe them) → ARCHITECTURE (how it is built) → DATASET (the data underneath).

## Sources of truth

| Question | Authority |
|---|---|
| Every measurement | `results/<run>/summary.json` (raw: one JSONL per run, one line per case) |
| The prompt that produced a run | `meta.prompt_version` in its JSONL, resolved through `verifier/prompts.PROMPT_SETS` |
| The reference labels | `data/eval.jsonl`, validated on load |
| Metric definitions | code in `eval/metrics.py`, described in EVALUATION.md |
| The current default configuration | `.env`, `verifier/prompts.DEFAULT_PROMPT_VERSION`, `README.md` |

Docs quote numbers that were regenerated from those files; if a document and a `summary.json` ever
disagree, the JSON is right.

## What changed in v2

1. **Split by job.** The v1 README had become a 410-line hybrid of front page, API reference,
   architecture note and results report. v2 splits it into a short front door plus `ARCHITECTURE.md`,
   `EVALUATION.md` and `REPORT.md`, and keeps `ITERATIONS.md` and `DATASET.md` as the deep sources.
2. **Regenerated every table** from `results/*/summary.json` instead of transcribing, which caught two
   stale values in the v1 prose (oracle latency quoted from a single run while the table showed 3-run
   means).
3. **Added a consistency test** (`tests/test_docs.py`): every `results/<dir>` path, every
   relative link and every cross-document anchor referenced from the docs must exist, the headline
   benchmark counts must match `data/eval.jsonl`, the documented default prompt version must match
   `prompts.DEFAULT_PROMPT_VERSION`, and the index must list every document. The docs cannot silently
   point at artifacts that were never written, or at headings that were reworded later.
4. **Absorbed everything discovered after v1 was written**: prompt v4 (implemented, measured, reverted),
   the real cost column with dated provider prices, the whole-dataset label audit, and the three client
   defects found by aiming the code at a live endpoint (Anthropic SDK `temperature`, cache-token
   accounting, base-URL precedence).
5. **Made the negative results first-class.** v2 has a documented place for "we tried this and it did not
   work": the v2 and v4 prompt versions and the non-reproducing model A/B are in the report and the log
   rather than deleted, because a reader deciding what to try next needs them more than another success
   story.

## Revision note (same day)

A metric change was applied to `results/` and to REPORT.md but not to the copy of the dev table in
ITERATIONS.md, and that stale row reached the public repository before a reader caught it. The response
is structural: every quoted metric row in every document is now checked against the summaries it came
from, and `DOCS_REFRESH=1 pytest tests/test_docs.py -k quoted` rewrites those rows in place, so a metric
change is never copied into prose by hand again.

## Conventions

* Numbers are given with the split and the number of runs (`dev`, 3 runs, mean ± std) and are never
  quoted from a single run when repeats exist.
* No hand-maintained counts (test totals, file sizes) in prose: they drift. Where a number must appear
  in several documents — the size of the benchmark — `tests/test_docs.py` checks it against the data.
* Claims about the system are labelled with how they were established: `measured` (a run in `results/`),
  `measured, reverted` (tried and rejected), or `not measured` (reasoning, clearly marked).
* Commands are copy-pasteable, and the ones in the header of each document can be run from the repo root
  as-is.
