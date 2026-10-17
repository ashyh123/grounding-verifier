import asyncio

import pytest

from verifier.llm import Usage
from verifier.llm_verifiers import MinimalVerifier, OptimizedVerifier
from verifier.schemas import VerifyRequest
from verifier.validate import check_response_invariants

from .test_core import P


class FakeLLM:
    """Scripted responses keyed by tool name; records calls."""
    model = "fake"

    def __init__(self, script):
        self.script = {k: list(v) for k, v in script.items()}
        self.calls = []

    async def call_tool(self, system, messages, tool_name, tool_schema, usage: Usage):
        usage.calls += 1
        self.calls.append((tool_name, messages, tool_schema))
        return self.script[tool_name].pop(0)


def test_optimized_happy_path():
    llm = FakeLLM({
        "claims": [{"claims": ["WAL works over NFS.", "WAL is encrypted."]}],
        "verdict": [
            {"evidence": [{"sentence_id": "P0.S2"}], "reasoning": "no NFS", "verdict": "CONTRADICTED"},
            {"evidence": [], "reasoning": "not mentioned", "verdict": "UNSUPPORTED"},
        ],
    })
    r = asyncio.run(OptimizedVerifier(llm).verify(
        VerifyRequest(context_passages=P, generated_answer="whatever")))
    assert [c.verdict.value for c in r.claims] == ["CONTRADICTED", "UNSUPPORTED"]
    assert check_response_invariants(P, r.claims) == []


def test_optimized_retry_on_bad_sentence_id():
    llm = FakeLLM({
        "claims": [{"claims": ["WAL checkpoints at about 1000 pages."]}],
        "verdict": [
            {"evidence": [{"sentence_id": "P7.S1"}], "reasoning": "bad id", "verdict": "SUPPORTED"},
            {"evidence": [{"sentence_id": "P1.S1", "quote": "approximately 1000 pages"}],
             "reasoning": "fixed", "verdict": "SUPPORTED"},
        ],
    })
    r = asyncio.run(OptimizedVerifier(llm).verify(
        VerifyRequest(context_passages=P, generated_answer="whatever")))
    c = r.claims[0]
    assert c.verdict.value == "SUPPORTED" and c.citations[0].quote == "approximately 1000 pages"
    assert r.meta.retries == 1 and r.meta.raw_citations_invalid == 1
    assert "Valid sentence IDs" in llm.calls[-1][1][-1]["content"]


def test_optimized_downgrades_after_retries_exhausted():
    bad = {"evidence": [{"sentence_id": "P9.S9"}], "reasoning": "x", "verdict": "SUPPORTED"}
    llm = FakeLLM({"claims": [{"claims": ["A."]}], "verdict": [bad, bad, bad]})
    r = asyncio.run(OptimizedVerifier(llm).verify(
        VerifyRequest(context_passages=P, generated_answer="A.")))
    assert r.claims[0].verdict.value == "UNSUPPORTED" and r.meta.downgraded_claims == 1


def test_optimized_empty_context_skips_llm():
    llm = FakeLLM({"claims": [{"claims": ["A is B."]}]})
    r = asyncio.run(OptimizedVerifier(llm).verify(
        VerifyRequest(context_passages=[], generated_answer="A is B.")))
    assert r.claims[0].verdict.value == "UNSUPPORTED" and len(llm.calls) == 1


def test_v4_decomposition_schema_carries_the_sentence_coverage_pass():
    """v4 asks for a sentence->claims mapping, so the prompt set has to send that schema."""
    llm = FakeLLM({"claims": [{"sentences": [{"sentence": "WAL is encrypted.",
                                             "claims": ["WAL is encrypted."]}],
                               "claims": ["WAL is encrypted."]}],
                   "verdict": [{"evidence": [], "reasoning": "not mentioned", "verdict": "UNSUPPORTED"}]})
    r = asyncio.run(OptimizedVerifier(llm, prompt_version="v4").verify(
        VerifyRequest(context_passages=P, generated_answer="WAL is encrypted.")))
    tool_name, _, schema = llm.calls[0]
    assert tool_name == "claims" and "sentences" in schema["properties"]
    assert r.meta.prompt_version == "v4" and r.claims[0].verdict.value == "UNSUPPORTED"


def test_v1_v3_decomposition_stays_flat():
    llm = FakeLLM({"claims": [{"claims": ["A."]}],
                   "verdict": [{"evidence": [], "reasoning": "x", "verdict": "UNSUPPORTED"}]})
    asyncio.run(OptimizedVerifier(llm, prompt_version="v1").verify(
        VerifyRequest(context_passages=P, generated_answer="A.")))
    assert "sentences" not in llm.calls[0][2]["properties"]


def test_unknown_prompt_version_is_rejected():
    with pytest.raises(ValueError, match="unknown prompt version"):
        OptimizedVerifier(FakeLLM({}), prompt_version="v99")


def test_minimal_malformed_output_is_repaired():
    llm = FakeLLM({"report": [{"claims": [
        {"claim_text": "checkpoint 1000", "verdict": "SUPPORTED", "reasoning": "r",
         "citations": [{"index": 0, "quote": "Automatic checkpointing occurs by default"}]},
        {"claim_text": "encrypted", "verdict": "SUPPORTED", "reasoning": "r",
         "citations": [{"index": 5, "quote": "AES"}]},
        "garbage",
    ]}]})
    r = asyncio.run(MinimalVerifier(llm).verify(
        VerifyRequest(context_passages=P, generated_answer="x")))
    assert [c.verdict.value for c in r.claims] == ["SUPPORTED", "UNSUPPORTED"]
    assert r.claims[0].citations[0].index == 1  # relocated
    assert r.meta.downgraded_claims == 1
    assert check_response_invariants(P, r.claims) == []
