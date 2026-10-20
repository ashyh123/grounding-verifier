# Documentation — version 2

Documentation set for the citation grounding verifier. **Docs v2, 2026-10-17; updated for v2.6 on
2026-10-20.** Supersedes docs v1 (the single incrementally-grown `README.md` from earlier the same day).

The rule this edition is built on: every document has one job, the numbers live in exactly one place,
and nothing in the docs is transcribed by hand if a script can regenerate it.

## Index

| Document | What it answers | Audience |
|---|---|---|
| [../README.md](../README.md) | What is this, how do I run it, what does it cost me, where do I go next | someone arriving at the repo |
| [ARCHITECTURE.md](ARCHITECTURE.md) | How does `POST /verify` work, where is the trust boundary, how do I extend it | engineer reading or modifying the code |
| [EVALUATION.md](EVALUATION.md) | How v2.7 and the historical benchmarks are measured, what each metric means, how to reproduce or re-score | reviewer judging the benchmark |
| [REPORT.md](REPORT.md) | What were the v2.7 and v2.6 results, what failed, what may not be concluded | reviewer judging the claims |
| [DATASET.md](DATASET.md) | What is in the v2.7 external sets, the v2.6 responses, and the historical 46-case synthetic set | annotator or reviewer auditing the data |
| [TEST_PLAN.md](TEST_PLAN.md) | Historical v2.5 test plan; the current v2.6 plan is the freeze record | reviewer comparing protocol versions |
| [ITERATIONS.md](ITERATIONS.md) | What was tried, what was kept, what was reverted and why | anyone judging the development process |

Reading order for a first pass: README → REPORT (results) → ITERATIONS (how they were reached) →
EVALUATION (whether to believe them) → ARCHITECTURE (how it is built) → DATASET (the data underneath).

## Sources of truth

| Question | Authority |
|---|---|
| Every measurement | `results/<run>/summary.json` (raw: one JSONL per run, one line per case); for v2.6 also `results/v2.6-test/report/v26_report.json` |
| The prompt that produced a run | `meta.prompt_version` in its JSONL, resolved through `verifier/prompts.PROMPT_SETS` |
| The reference labels (current) | `data/eval_ragtruth_resp.v2.6.jsonl` for v2.6; RAGTruth++ and LLM-AggreFact are local-only v2.7 sources (manifests under `data/annotation/v2.7/`) |
| The reference labels (historical) | `data/eval.jsonl` for the synthetic set, `data/eval_hard.v2.5.jsonl` for the exploratory claim-level set |
| Metric definitions (current) | `eval/v27.py` (track A and track B orchestration), `eval/v26.py` (sentence/answer metrics), described in EVALUATION.md's v2.7 section |
| Metric definitions (historical) | `eval/metrics.py`, `eval/v25.py` |
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

## v2.7 revision (2026-10-20)

**Post-report scoring correction:** a claim-count mismatch is now a document failure. Track A minimal
has 32/461 such failures (6.94 %), above the 5 % stop line; the main result counts them wrong, while
truly excluding them removes the optimized lead. README's track A conclusion gives both versions,
uses the 5/5 per-subset split, and notes that Lfqa/TofuEval subsets contain only 2–3 documents. A
README-only documentation re-seal (plus a status-summary correction) was explicitly authorized and
logged; code, prompt, data and metric hashes did not change.

The headline is now three-part: v2.6 end-to-end under RAGTruth original annotation; v2.7 track B
(RAGTruth++ loose vs strict) and track A (LLM-AggreFact oracle). The key result is that the
minimal/optimized ranking is **decided by the annotation standard**: minimal is better under loose
gold, optimized under strict gold; with claims given, optimized verifies more accurately. The v2.5
and v2.6 results remain as prior/exploratory evidence. The v2.7 freeze is
`data/annotation/v2.7/freeze.json`; external raw data is local-only and git-ignored.

## v2.6 revision (2026-10-20)

The headline target is now `data/eval_ragtruth_resp.v2.6.jsonl`: 180 unseen RAGTruth test responses,
gold from the upstream human spans, no model in labelling, response-level F1. The measured order is
minimal 0.720 > optimized 0.609 > baseline 0.521. The v2.5 claim-level result is kept as exploratory
methodology, and the 46-case synthetic benchmark remains as history. The test run, freeze and
stop-condition check are in `data/annotation/v2.6/`; the metric code is `eval/v26.py`. The docs
consistency tests still pin the synthetic headline counts, and now also pin the v2.6 freeze through
`tests/test_v26_freeze.py`.

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
