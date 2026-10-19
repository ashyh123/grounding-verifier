"""Load + validate an evaluation dataset. Run: python -m eval.dataset [data/eval.jsonl]

Two schemas share this loader:

* the synthetic regression suite (`data/eval.jsonl`) — the original fields;
* the v2 hard set (`data/eval_hard.jsonl`) — the same fields plus `source`, `source_labels`,
  `generator_model`, `context_words`, `difficulty_tags` and `provenance`. They are optional, so the
  original file validates exactly as before.

The v2-only invariants (source groups never straddle splits, `annotation_origin` disclosed,
`context_words` matches the passages) run whenever those fields are present.
"""
from __future__ import annotations

import hashlib
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, PrivateAttr

from verifier.schemas import Verdict

ALLOWED_TAGS = {
    "supported", "paraphrase", "number_off", "unit_change", "negation_flip", "condition_swap",
    "quantifier_shift", "comparison_flip", "entity_swap", "temporal_version", "extrinsic",
    "extrinsic_true_world", "multi_passage", "empty_context", "no_claims", "mixed",
    # v2 hard-set difficulty tags (design doc §3)
    "evident", "subtle", "conflict", "baseless", "clean", "numeric", "long_context",
    "dense_facts", "hallucinated_source",
}

V2_SOURCES = {
    "ragtruth_summary", "ragtruth_qa", "ragtruth_data2txt",
    "factscore_instructgpt", "factscore_chatgpt", "factscore_perplexityai",
    "halueval_summary",
}
ANNOTATION_ORIGINS = {"llm_draft", "human", "human_reviewed", "ragtruth_human"}


class GoldEvidence(BaseModel):
    index: int
    quote: str


class GoldClaim(BaseModel):
    claim_text: str
    verdict: Verdict
    tags: list[str] = Field(default_factory=list)
    evidence: list[GoldEvidence] = Field(default_factory=list)
    label_source: Literal['ragtruth_human'] | None = None
    evidence_status: Literal['exact', 'none'] | None = None


class ScoringRegistration(BaseModel):
    dataset_sha256: str
    case_id: str
    parent_claim_text: str
    parent_verdict: Literal["SUPPORTED"]
    units: list[GoldClaim] = Field(min_length=2)
    approved_by: Literal["user"]
    approved_on: str
    supersedes_sha256: str | None = None


class EvalCase(BaseModel):
    id: str
    split: str  # "dev" | "test"
    tags: list[str]
    context_passages: list[str]
    generated_answer: str
    gold_claims: list[GoldClaim]
    notes: str = ""
    # v2 hard set (optional: the synthetic suite does not carry them)
    source: str | None = None
    source_labels: dict = Field(default_factory=dict)
    generator_model: str | None = None
    context_words: int | None = None
    difficulty_tags: list[str] = Field(default_factory=list)
    provenance: dict = Field(default_factory=dict)
    # Scoring metadata comes only from the separately approved registry, never the dataset JSON.
    _scoring_units: dict[int, list[GoldClaim]] = PrivateAttr(default_factory=dict)
    _scoring_registry_sha256: str | None = PrivateAttr(default=None)


def load(path: str | Path) -> list[EvalCase]:
    cases = [EvalCase.model_validate_json(line)
             for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    errors = validate(cases)
    if errors:
        raise ValueError("dataset invalid:\n" + "\n".join(errors))
    _attach_scoring_units(Path(path), cases)
    return cases


def _attach_scoring_units(path: Path, cases: list[EvalCase]) -> None:
    registry = path.with_suffix(".scoring_units.jsonl")
    if not registry.is_file():
        return
    dataset_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    registry_hash = hashlib.sha256(registry.read_bytes()).hexdigest()
    by_id = {case.id: case for case in cases}
    latest: dict[tuple[str, int], tuple[ScoringRegistration, str]] = {}
    for line in registry.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = ScoringRegistration.model_validate_json(line)
        if item.dataset_sha256 != dataset_hash:
            raise ValueError(f"{registry}: scoring registration does not match dataset SHA256")
        case = by_id.get(item.case_id)
        parents = [(i, g) for i, g in enumerate(case.gold_claims) if g.claim_text == item.parent_claim_text
                   and g.verdict.value == item.parent_verdict] if case else []
        if len(parents) != 1:
            raise ValueError(f"{registry}: scoring parent must match exactly once: {item.case_id}")
        index, _parent = parents[0]
        if any(unit.verdict is not Verdict.SUPPORTED or not unit.claim_text.strip() for unit in item.units):
            raise ValueError(f"{registry}: only explicitly approved SUPPORTED units are supported")
        if len({u.claim_text for u in item.units}) != len(item.units):
            raise ValueError(f"{registry}: duplicate scoring unit")
        key = (item.case_id, index)
        previous = latest.get(key)
        if previous:
            old, old_hash = previous
            if item.supersedes_sha256 != old_hash:
                raise ValueError(f"{registry}: evidence revision must reference its preceding approval")
            if [(u.claim_text, u.verdict) for u in old.units] != [(u.claim_text, u.verdict) for u in item.units]:
                raise ValueError(f"{registry}: evidence revisions cannot change approved units or labels")
        elif item.supersedes_sha256 is not None:
            raise ValueError(f"{registry}: evidence revision has no preceding approval")
        latest[key] = (item, hashlib.sha256(line.encode("utf-8")).hexdigest())
        case._scoring_units[index] = item.units
    for (case_id, _index), (item, _hash) in latest.items():
        passages = by_id[case_id].context_passages
        for unit in item.units:
            if not unit.evidence:
                raise ValueError(f"{registry}: every active scoring unit needs exact source evidence")
            for evidence in unit.evidence:
                if (not 0 <= evidence.index < len(passages) or not evidence.quote.strip()
                        or evidence.quote not in passages[evidence.index]):
                    raise ValueError(f"{registry}: scoring-unit evidence must be an exact source substring")
    for case in cases:
        case._scoring_registry_sha256 = registry_hash


def validate(cases: list[EvalCase]) -> list[str]:
    errs: list[str] = []
    ids = Counter(c.id for c in cases)
    errs += [f"duplicate id {i}" for i, n in ids.items() if n > 1]
    for c in cases:
        if c.split not in ("dev", "test"):
            errs.append(f"{c.id}: split must be dev|test")
        for t in c.tags + [t for g in c.gold_claims for t in g.tags] + c.difficulty_tags:
            if t not in ALLOWED_TAGS:
                errs.append(f"{c.id}: unknown tag {t}")
        if c.source is not None and c.source not in V2_SOURCES:
            errs.append(f"{c.id}: unknown source {c.source!r}")
        origin = c.provenance.get("annotation_origin")
        if c.provenance and origin not in ANNOTATION_ORIGINS:
            errs.append(f"{c.id}: provenance.annotation_origin must be one of "
                        f"{sorted(ANNOTATION_ORIGINS)}, got {origin!r}")
        if c.context_words is not None:
            actual = len(" ".join(c.context_passages).split())
            if abs(actual - c.context_words) > 1:
                errs.append(f"{c.id}: context_words={c.context_words} but the passages have {actual}")
        for k, g in enumerate(c.gold_claims):
            if g.verdict is Verdict.UNSUPPORTED and g.evidence:
                errs.append(f"{c.id} claim {k}: UNSUPPORTED must have no evidence")
            no_reference = g.label_source == 'ragtruth_human' and g.evidence_status == 'none'
            if g.evidence_status is not None and g.label_source != 'ragtruth_human':
                errs.append(f"{c.id} claim {k}: evidence_status requires ragtruth_human labels")
            if g.label_source == 'ragtruth_human' and g.evidence_status is None:
                errs.append(f"{c.id} claim {k}: ragtruth_human requires evidence_status")
            if no_reference and g.evidence:
                errs.append(f"{c.id} claim {k}: evidence_status none requires empty evidence")
            if g.evidence_status == 'exact' and not g.evidence:
                errs.append(f"{c.id} claim {k}: evidence_status exact requires evidence")
            if g.verdict is not Verdict.UNSUPPORTED and not g.evidence and not no_reference:
                errs.append(f"{c.id} claim {k}: {g.verdict.value} needs evidence")
            for e in g.evidence:
                if not 0 <= e.index < len(c.context_passages):
                    errs.append(f"{c.id} claim {k}: evidence index {e.index} out of range")
                elif not e.quote.strip() or e.quote not in c.context_passages[e.index]:
                    errs.append(f"{c.id} claim {k}: evidence quote not verbatim: {e.quote[:50]!r}")
    errs += validate_source_groups(cases)
    return errs


def source_group(case: EvalCase) -> str | None:
    """The upstream item a case came from; cases sharing it must stay in one split."""
    prov = case.provenance or {}
    if prov.get("source_group"):
        return str(prov["source_group"])
    if prov.get("source_id") is not None:
        return f"{prov.get('dataset', case.source or '?')}:{prov['source_id']}"
    return None


def validate_source_groups(cases: list[EvalCase]) -> list[str]:
    splits: dict[str, set[str]] = defaultdict(set)
    for c in cases:
        key = source_group(c)
        if key:
            splits[key].add(c.split)
    return [f"source group {key!r} appears in both splits {sorted(s)}"
            for key, s in splits.items() if len(s) > 1]


def summary(cases: list[EvalCase]) -> str:
    v = Counter(g.verdict.value for c in cases for g in c.gold_claims)
    s = Counter(c.split for c in cases)
    t = Counter(t for c in cases for t in c.tags)
    return f"cases={len(cases)} splits={dict(s)} claim_verdicts={dict(v)} tags={dict(t)}"


def hard_summary(cases: list[EvalCase]) -> str:
    """Per-split statistics for the v2 set (design doc §1 targets are checked in annotation.merge)."""
    import statistics
    lines = []
    for split in ("dev", "test"):
        part = [c for c in cases if c.split == split]
        claims = [g for c in part for g in c.gold_claims]
        verdicts = Counter(g.verdict.value for g in claims)
        multi = sum(1 for g in claims if len({e.index for e in g.evidence}) >= 2)
        words = [len(" ".join(c.context_passages).split()) for c in part]
        by_source = Counter(c.source or "?" for c in part)
        median = f"{statistics.median(words):.0f}" if words else "0"
        lines.append(f"{split}: cases={len(part)} claims={len(claims)} "
                     f"S={verdicts.get('SUPPORTED', 0)} C={verdicts.get('CONTRADICTED', 0)} "
                     f"U={verdicts.get('UNSUPPORTED', 0)} multi_passage_claims={multi} "
                     f"median_context_words={median}")
        lines.append("  sources: " + ", ".join(f"{k}={v}" for k, v in sorted(by_source.items())))
    return "\n".join(lines)


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "data/eval.jsonl"
    loaded = load(path)
    print(summary(loaded))
    if any(c.source for c in loaded):
        print(hard_summary(loaded))
