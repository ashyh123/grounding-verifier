.PHONY: install test serve data eval-dev eval-dev-v2 eval-test
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
