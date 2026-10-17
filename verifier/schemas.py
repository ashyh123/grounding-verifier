from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_PASSAGES = 50
MAX_PASSAGE_CHARS = 20_000
MAX_ANSWER_CHARS = 10_000


class Verdict(str, Enum):
    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    UNSUPPORTED = "UNSUPPORTED"


class VerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context_passages: list[str] = Field(default_factory=list, max_length=MAX_PASSAGES)
    generated_answer: str = Field(max_length=MAX_ANSWER_CHARS)

    @field_validator("context_passages")
    @classmethod
    def _passage_len(cls, v: list[str]) -> list[str]:
        for i, p in enumerate(v):
            if len(p) > MAX_PASSAGE_CHARS:
                raise ValueError(f"context_passages[{i}] exceeds {MAX_PASSAGE_CHARS} chars")
        return v


class Citation(BaseModel):
    index: int = Field(ge=0)
    quote: str = Field(min_length=1)
    start_char: int = Field(ge=0)
    end_char: int = Field(ge=0)


class Claim(BaseModel):
    claim_text: str
    verdict: Verdict
    reasoning: str
    citations: list[Citation] = Field(default_factory=list)


class Meta(BaseModel):
    method: str
    model: str | None = None
    prompt_version: str | None = None  # optimized verifier only; records the hill-climb step
    latency_ms: float = 0.0
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    retries: int = 0
    # Counts BEFORE deterministic repair, used by the eval report.
    raw_citations_total: int = 0
    raw_citations_invalid: int = 0
    downgraded_claims: int = 0
    warnings: list[str] = Field(default_factory=list)


class VerifyResponse(BaseModel):
    claims: list[Claim]
    meta: Meta | None = None
