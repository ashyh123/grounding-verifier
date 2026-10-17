"""End-to-end check of the benchmark harness with the LLM replaced by a scripted stub.

This is what `make eval-dev` / `make eval-test` run, minus the provider: it guards the
JSONL format, the metric keys, the markdown report and the failure listing.
"""
import asyncio
import json
import sys
from pathlib import Path

from eval import report, run as eval_run
from eval.dataset import load
from verifier import config, prompts
from verifier.baseline import BaselineVerifier
from verifier.schemas import Citation, Claim, Meta, Verdict, VerifyResponse

DATA = str(Path(__file__).resolve().parent.parent / "data" / "eval.jsonl")
N_DEV = sum(1 for c in load(DATA) if c.split == "dev")


class StubVerifier:
    """Answers every case with one SUPPORTED claim citing the first passage, unverified."""

    def __init__(self, name: str):
        self.name = name
        self.model = "stub"

    def _result(self, passages: list[str]) -> VerifyResponse:
        claims = []
        if passages:
            quote = passages[0][:30]
            citations = [Citation(index=0, quote=quote, start_char=0, end_char=len(quote))]
            claims = [Claim(claim_text="Stub claim about the first passage.", verdict=Verdict.SUPPORTED,
                            reasoning="stub", citations=citations)]
        return VerifyResponse(claims=claims,
                              meta=Meta(method=self.name, model=self.model, latency_ms=1.0,
                                        llm_calls=1, input_tokens=100, output_tokens=10,
                                        prompt_version="v1" if self.name == "optimized" else None))

    async def verify(self, req):
        return self._result(req.context_passages)

    async def verify_claims(self, passages, claims):
        return self._result(passages)


def test_cli_writes_results_and_report(tmp_path, monkeypatch):
    def build(method: str, prompt_version: str = "v1"):
        return BaselineVerifier() if method == "baseline" else StubVerifier(method)

    monkeypatch.setattr(eval_run, "build", build)
    monkeypatch.setattr(sys, "argv", ["eval.run", "--data", DATA, "--split", "dev", "--runs", "1",
                                      "--methods", "baseline", "minimal", "optimized",
                                      "--out", str(tmp_path)])
    asyncio.run(eval_run.main())

    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["split"] == "dev" and summary["n_cases"] == N_DEV
    assert summary["prompt_version"] == (config.optional_env("VERIFIER_PROMPT_VERSION")
                                        or prompts.DEFAULT_PROMPT_VERSION)
    assert set(summary["methods"]) == {"baseline", "minimal", "optimized"}

    for method, runs in summary["methods"].items():
        assert len(runs) == 1  # baseline is deterministic, the rest ran once
        m = runs[0]
        for key in ("answer_level", "macro_f1", "per_label", "citation_precision",
                    "decomposition", "avg_llm_calls", "avg_cost_usd", "errors"):
            assert key in m, key
        assert m["errors"] == 0
        assert (tmp_path / f"{method}_run0.jsonl").is_file()

    rows = [json.loads(line) for line in (tmp_path / "minimal_run0.jsonl").read_text().splitlines()]
    assert len(rows) == N_DEV and {"id", "claims", "meta"} <= set(rows[0])

    table = report.table(summary)
    assert "Answer-level hallucination F1" in table and "Cost / case (USD)" in table
    assert "| baseline |" in table

    assert report.failures(tmp_path, "optimized", DATA).count("###") > 0

    # rescoring recomputes the same numbers from disk, without touching the provider
    before = json.loads((tmp_path / "summary.json").read_text())
    monkeypatch.setattr(eval_run, "build", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no calls")))
    monkeypatch.setattr(sys, "argv", ["eval.run", "--data", DATA, "--rescore", str(tmp_path)])
    asyncio.run(eval_run.main())
    after = json.loads((tmp_path / "summary.json").read_text())
    assert after["methods"]["optimized"][0]["macro_f1"] == before["methods"]["optimized"][0]["macro_f1"]
    assert "citation_passage_precision" in after["methods"]["optimized"][0]


def test_report_table_handles_multiple_runs(tmp_path, monkeypatch):
    def build(method: str, prompt_version: str = "v1"):
        return BaselineVerifier() if method == "baseline" else StubVerifier(method)

    monkeypatch.setattr(eval_run, "build", build)
    monkeypatch.setattr(sys, "argv", ["eval.run", "--data", DATA, "--split", "test", "--runs", "2",
                                      "--methods", "optimized", "--out", str(tmp_path)])
    asyncio.run(eval_run.main())
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert len(summary["methods"]["optimized"]) == 2
    assert "±" in report.table(summary)  # mean ± std across runs


def test_fusion_metric_has_no_false_positive_floor():
    """Regression for the old token-set-based fusion test.

    The baseline splits the answer into sentences verbatim, so its claims cannot fuse anything; the
    previous metric still scored it 0.113 because neighbouring sentences share vocabulary. Fusion is now
    decided on words that belong to exactly one sentence.
    """
    from eval.metrics import _fused_claims

    sentences = ["WAL mode is available since 3.7.0 and it is fast.",
                 "WAL mode does not work over a network filesystem because of shared memory.",
                 "Checkpointing occurs by default when the WAL passes approximately 1000 pages."]
    # baseline style: one claim per sentence, copied
    assert _fused_claims(sentences, sentences) == 0
    # a claim that carries distinctive words of two different sentences
    fused = ["WAL mode does not work over a network filesystem, and checkpointing occurs by default "
             "when it passes approximately 1000 pages."]
    assert _fused_claims(fused, sentences) == 1
    # a single-sentence answer can never fuse
    assert _fused_claims(sentences[:1], sentences[:1]) == 0
