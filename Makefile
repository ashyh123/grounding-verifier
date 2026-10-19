.PHONY: install test serve data eval-dev eval-dev-v2 eval-test \
        annotate annotate-draft annotate-check annotate-zh annotate-prereview \
        annotate-triage annotate-review annotate-round2 annotate-merge annotate-map annotate-evidence annotate-freeze
install:
	uv sync
test:
	uv run pytest -q
serve:
	uv run uvicorn verifier.api:app --host 0.0.0.0 --port 8000
data:
	uv run python -m eval.dataset data/eval.jsonl
eval-dev:
	uv run python -m eval.run --split dev --runs 1
eval-dev-v2:
	uv run python -m eval.run --split dev --runs 1 --methods optimized --prompt-version v2 --out results/dev-v2
eval-test:
	uv run python -m eval.run --split test --runs 3 --out results/final_e2e
	uv run python -m eval.run --split test --runs 3 --oracle --methods baseline minimal optimized --out results/final_oracle

# ---- v2.3 pilot (stop after report; annotation/README.md) ------------------------------------
annotate-map:
	uv run python -m annotation.map_labels --drafts data/annotation/drafts.jsonl --out-dir data/annotation/pilot5-dev-v2.3
annotate-evidence:
	uv run python -m annotation.find_evidence --mapped data/annotation/pilot5-dev-v2.3/mapped.jsonl

# Historical v2.2 tools below are retained; review/translation/triage/merge are not the v2.3 flow.
# T0-T2 are safe to re-run; they are deterministic and need no credentials.
annotate:
	uv run python -m annotation.fetch_sources
	uv run python -m annotation.select_cases
annotate-draft:
	uv run python -m annotation.draft_claims --resume
annotate-check:
	uv run python -m annotation.check_drafts
annotate-zh:
	uv run python -m annotation.zh --build
annotate-prereview:
	uv run python -m annotation.prereview --build
annotate-triage:
	uv run python -m annotation.triage
annotate-review:
	uv run python -m annotation.review_app --round 1 --needs-review
annotate-round2:
	uv run python -m annotation.round2_queue
	uv run python -m annotation.review_app --round 2
annotate-merge:
	uv run python -m annotation.merge --runs data/annotation/pilot5-dev-v2.3 data/annotation/full-v2.3 --drafts data/annotation/drafts.jsonl data/annotation/drafts.remaining25.jsonl
	uv run python -m eval.dataset data/eval_hard.jsonl
annotate-freeze:
	uv run python -m annotation.freeze
	uv run python -m annotation.freeze --check
