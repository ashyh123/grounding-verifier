"""Load + validate data/eval.jsonl. Run: python -m eval.dataset data/eval.jsonl"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, Field

from verifier.schemas import Verdict

ALLOWED_TAGS = {
    "supported", "paraphrase", "number_off", "unit_change", "negation_flip", "condition_swap",
    "quantifier_shift", "comparison_flip", "entity_swap", "temporal_version", "extrinsic",
    "extrinsic_true_world", "multi_passage", "empty_context", "no_claims", "mixed",
}


class GoldEvidence(BaseModel):
    index: int
    quote: str


class GoldClaim(BaseModel):
    claim_text: str
    verdict: Verdict
    tags: list[str] = Field(default_factory=list)
    evidence: list[GoldEvidence] = Field(default_factory=list)


class EvalCase(BaseModel):
    id: str
    split: str  # "dev" | "test"
    tags: list[str]
    context_passages: list[str]
    generated_answer: str
    gold_claims: list[GoldClaim]
    notes: str = ""


def load(path: str | Path) -> list[EvalCase]:
    cases = [EvalCase.model_validate_json(line)
             for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    errors = validate(cases)
    if errors:
        raise ValueError("dataset invalid:\n" + "\n".join(errors))
    return cases


def validate(cases: list[EvalCase]) -> list[str]:
    errs: list[str] = []
    ids = Counter(c.id for c in cases)
    errs += [f"duplicate id {i}" for i, n in ids.items() if n > 1]
    for c in cases:
        if c.split not in ("dev", "test"):
            errs.append(f"{c.id}: split must be dev|test")
        for t in c.tags + [t for g in c.gold_claims for t in g.tags]:
            if t not in ALLOWED_TAGS:
                errs.append(f"{c.id}: unknown tag {t}")
        for k, g in enumerate(c.gold_claims):
            if g.verdict is Verdict.UNSUPPORTED and g.evidence:
                errs.append(f"{c.id} claim {k}: UNSUPPORTED must have no evidence")
            if g.verdict is not Verdict.UNSUPPORTED and not g.evidence:
                errs.append(f"{c.id} claim {k}: {g.verdict.value} needs evidence")
            for e in g.evidence:
                if not 0 <= e.index < len(c.context_passages):
                    errs.append(f"{c.id} claim {k}: evidence index {e.index} out of range")
                elif e.quote not in c.context_passages[e.index]:
                    errs.append(f"{c.id} claim {k}: evidence quote not verbatim: {e.quote[:50]!r}")
    return errs


def summary(cases: list[EvalCase]) -> str:
    v = Counter(g.verdict.value for c in cases for g in c.gold_claims)
    s = Counter(c.split for c in cases)
    t = Counter(t for c in cases for t in c.tags)
    return f"cases={len(cases)} splits={dict(s)} claim_verdicts={dict(v)} tags={dict(t)}"


if __name__ == "__main__":
    print(summary(load(sys.argv[1] if len(sys.argv) > 1 else "data/eval.jsonl")))
