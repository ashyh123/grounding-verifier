import asyncio

from verifier.baseline import BaselineVerifier
from verifier.schemas import VerifyRequest
from verifier.validate import check_response_invariants

from .test_core import P

ANS = ("SQLite WAL mode allows multiple processes across different host machines on an NFS network "
       "share to write concurrently. Automatic checkpointing occurs by default when the WAL passes "
       "approximately 2000 pages. By default, WAL files are encrypted with AES-256 at rest.")


def test_baseline_runs_and_respects_invariants():
    r = asyncio.run(BaselineVerifier().verify(VerifyRequest(context_passages=P, generated_answer=ANS)))
    assert len(r.claims) == 3
    assert check_response_invariants(P, r.claims) == []
    verdicts = [c.verdict.value for c in r.claims]
    assert verdicts[1] == "CONTRADICTED"  # 2000 vs 1000
    assert verdicts[2] == "UNSUPPORTED"
    print(verdicts)


def test_baseline_empty_inputs():
    r = asyncio.run(BaselineVerifier().verify(VerifyRequest(context_passages=[], generated_answer="X is Y.")))
    assert r.claims[0].verdict.value == "UNSUPPORTED"
    r = asyncio.run(BaselineVerifier().verify(VerifyRequest(context_passages=P, generated_answer="")))
    assert r.claims == []
