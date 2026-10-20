"""Prompts for annotation drafting.

RAGTruth v2.2 drafts only atomic claims and exact answer quotes, without labels or evidence.
The retained legacy source prompts embed docs/DATASET.md rules; they are excluded this round.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import sources as S

DATASET_DOC = S.ROOT / "docs" / "DATASET.md"
TOOL_NAME = "submit_claims"


def rules_excerpt(path: Path = DATASET_DOC) -> str:
    """The 'Labelling rules' section of docs/DATASET.md, verbatim."""
    text = path.read_text(encoding="utf-8")
    start = text.index("## Labelling rules")
    end = text.index("\n## ", start + 1)
    body = text[start:end].strip()
    return body.split("\n", 1)[1].strip()  # drop the heading: the prompt introduces the block


def _rules_block() -> str:
    return (f"## Decomposition and verdict rules\n\n"
            f"These are the rules from {DATASET_DOC.name}, quoted verbatim:\n\n"
            f"{rules_excerpt()}")


SYSTEM_RAGTRUTH = """You draft annotation candidates for a citation-grounding benchmark.

Split the complete answer into atomic factual claims. Use the context only to resolve references;
do not correct the answer against it. Return claim_text, answer_spans and reasoning for each claim.

Rules for your part:

* One claim = one checkable proposition. Split conjunctions, comparisons and multi-part statements
  into separate claims; keep qualifiers, conditions and trailing clauses attached to the claim they
  qualify.
* Preserve every factual assertion, including repetitions and assertions absent from the context.
  Do not invent assertions. Do not change the meaning, numbers, negation, modality or attribution.
* Keep the answer's wording wherever possible. You may repeat a shared subject to make split
  claims understandable; do not add facts while doing so.
* answer_spans contains one or more exact quotes from the ANSWER that express this claim,
  including any shared subject and qualifiers it needs. Offsets are computed by the script.
  Each quote must occur exactly once in the answer; extend it with adjacent answer text when
  needed to disambiguate repeated text. Quotes are answer provenance, not source evidence.
* reasoning explains the decomposition and how the answer spans express the claim.
* Do not assign truth labels or select source evidence. A separate blind review does that later.

"""


SYSTEM_FACTSCORE = """You help draft annotation candidates for a citation-grounding benchmark.

The response you are given is a biography written by a language model, and it already comes with
human-annotated atomic facts and their labels (S = supported by Wikipedia, NS = not supported,
IR = irrelevant). The atomic facts are fixed: do not rewrite, split or merge them, and do not add
facts of your own. Use the `fact` field to say which given atomic fact each of your entries is
about (0-based, in the order shown).

For each fact:

* `claim_text` must be the given fact, copied exactly.
* Your verdict is your judgement against the Wikipedia text in the prompt: SUPPORTED if the
  passages state or directly entail it, CONTRADICTED if the passages state something incompatible
  (a different number, place, date, role), UNSUPPORTED if the passages are silent about it and
  nothing conflicts.
* Give verbatim evidence (passage `index` and an exact `quote`) for every SUPPORTED or CONTRADICTED
  verdict. Silence stays UNSUPPORTED and gets no evidence.
* The Wikipedia text may be a truncated extract of the article; if the evidence you would expect is
  missing, prefer UNSUPPORTED over CONTRADICTED.

""" + _rules_block()


SYSTEM_HALUEVAL = """You draft annotation candidates for a citation-grounding benchmark.

The summary you are given is the hallucinated one from a supervised hallucination pair: the same
document also has a correct summary, which is shown to you. Split the hallucinated summary into
atomic claims and, for each one, say whether the document supports it, contradicts it, or says
nothing about it. Everything you return here is a suggestion for a human reviewer: this source
carries no claim-level ground truth, so every claim of this case is reviewed by hand.

* Copy the summary's wording; do not rephrase.
* One claim = one checkable proposition, with its qualifiers attached.
* Set `tampered` to true when the claim is a distortion of what the document says (the kind of
  change that separates the hallucinated summary from the correct one), false otherwise.
* Give verbatim evidence (passage `index`, exact `quote`) for SUPPORTED and CONTRADICTED verdicts;
  leave it empty for UNSUPPORTED.

""" + _rules_block()


SYSTEMS = {"ragtruth": SYSTEM_RAGTRUTH, "factscore": SYSTEM_FACTSCORE, "halueval": SYSTEM_HALUEVAL}


def family(source: str) -> str:
    """ragtruth_summary | ragtruth_qa | ragtruth_data2txt -> ragtruth; factscore_* -> factscore."""
    return source.split("_")[0]


def system_prompt(case: dict) -> str:
    return SYSTEMS[family(case["source"])]


def tool_schema(case: dict) -> dict:
    """One schema for all three sources; `fact` is only meaningful for FActScore."""
    family_ = family(case["source"])
    if family_ == "ragtruth":
        return {
            "type": "object", "additionalProperties": False,
            "properties": {"claims": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "properties": {
                    "claim_text": {"type": "string", "minLength": 1},
                    "answer_spans": {"type": "array", "minItems": 1, "items": {
                        "type": "object", "additionalProperties": False,
                        "properties": {"quote": {"type": "string", "minLength": 1}},
                        "required": ["quote"]}},
                    "reasoning": {"type": "string"},
                }, "required": ["claim_text", "answer_spans", "reasoning"]}}},
            "required": ["claims"],
        }
    claim_props: dict = {
        "claim_text": {"type": "string", "description": "the claim, copied from the answer"},
        "verdict": {"type": "string", "enum": ["SUPPORTED", "CONTRADICTED", "UNSUPPORTED"]},
        "reasoning": {"type": "string"},
        "evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"index": {"type": "integer"}, "quote": {"type": "string"}},
                "required": ["index", "quote"],
            },
        },
    }
    required = ["claim_text", "verdict", "reasoning"]
    if family_ == "factscore":
        claim_props["fact"] = {"type": "integer",
                               "description": "index of the given atomic fact (0-based)"}
        required.append("fact")
    elif family_ == "halueval":
        claim_props["tampered"] = {"type": "boolean"}
        required.append("tampered")
    else:
        claim_props["answer_span"] = {
            "type": "object",
            "properties": {"start": {"type": "integer"}, "end": {"type": "integer"}},
            "required": ["start", "end"],
        }
        required.append("answer_span")
    return {
        "type": "object",
        "properties": {"claims": {"type": "array", "items": {
            "type": "object", "properties": claim_props, "required": required}}},
        "required": ["claims"],
    }


def render_passages(passages: list[str]) -> str:
    return "\n\n".join(f"<passage index={i}>\n{p}\n</passage>" for i, p in enumerate(passages))


def user_prompt(case: dict) -> str:
    """RAGTruth exposes only passages and the complete answer, both verbatim."""
    family_ = family(case["source"])
    parts = [render_passages(case["context_passages"]), "---", "Answer:", case["generated_answer"]]
    labels = case.get("source_labels", {})
    if family_ == "ragtruth":
        return "\n".join(parts)
    elif family_ == "factscore":
        facts = labels.get("human_atomic_facts", [])
        numbered = [{"fact": i, "text": f["text"], "upstream_label": f["label"]}
                    for i, f in enumerate(facts) if f.get("label") != "IR"]
        dropped = [f["text"] for f in facts if f.get("label") == "IR"]
        parts += [
            "---",
            "Human-annotated atomic facts to judge (IR facts are omitted):",
            json.dumps(numbered, ensure_ascii=False, indent=1),
        ]
        if dropped:
            parts += [f"(For reference, {len(dropped)} fact(s) were labelled IR and are not to be "
                      f"judged: {json.dumps(dropped, ensure_ascii=False)})"]
    else:
        parts += ["---", "Correct summary of the same document:",
                  labels.get("right_summary", "")]
    return "\n".join(parts)


def prompt_hash(case: dict) -> str:
    """sha256 over the exact prompt pair + tool schema, recorded on every draft."""
    payload = json.dumps({"system": system_prompt(case), "user": user_prompt(case),
                          "tool": tool_schema(case), "tool_name": TOOL_NAME},
                         ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
