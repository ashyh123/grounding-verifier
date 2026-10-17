"""All prompts live here, versioned. Never edit an old version: add a new one.

The minimal verifier is deliberately frozen at V1 - it *is* the "minimal prompting"
point of comparison. Only the optimized verifier hill-climbs, so its prompt set is
selectable (VERIFIER_PROMPT_VERSION, see PROMPT_SETS at the bottom).
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ---------------- Minimal verifier (approach 2) ----------------
MINIMAL_SYSTEM_V1 = """You verify whether an answer is grounded in source passages.
Split the answer into atomic factual claims. For each claim give a verdict:
SUPPORTED (entailed by the passages), CONTRADICTED (refuted by the passages) or
UNSUPPORTED (not verifiable from the passages). For SUPPORTED and CONTRADICTED claims, cite
the passage index and an exact quote copied from that passage. UNSUPPORTED claims have no citations."""

MINIMAL_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim_text": {"type": "string"},
                    "verdict": {"type": "string", "enum": ["SUPPORTED", "CONTRADICTED", "UNSUPPORTED"]},
                    "reasoning": {"type": "string"},
                    "citations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"index": {"type": "integer"}, "quote": {"type": "string"}},
                            "required": ["index", "quote"],
                        },
                    },
                },
                "required": ["claim_text", "verdict", "reasoning", "citations"],
            },
        }
    },
    "required": ["claims"],
}

# ---------------- Optimized verifier: step 1, decomposition ----------------
DECOMPOSE_SYSTEM_V1 = """You split an answer into atomic factual claims for fact-checking.

Rules:
1. One claim = one checkable fact (one subject, one relation, one value or condition).
   Split "X does A and B" into "X does A" and "X does B".
   Keep a condition with the fact it restricts: "X does A when C" stays ONE claim.
2. Make every claim self-contained: replace pronouns and vague references ("it", "this mode",
   "the file") with the full entity name taken from the answer.
3. Keep the answer's own wording, numbers, units, hedges and negations. Do NOT correct,
   soften or "fix" anything, even if you believe it is false.
4. Skip text with no factual content (greetings, "I hope this helps", pure opinions).
5. Do not add facts that are not in the answer. Do not look at any source; you only see the answer.

Return an empty list if the answer has no factual claims."""

DECOMPOSE_SCHEMA = {
    "type": "object",
    "properties": {"claims": {"type": "array", "items": {"type": "string"}}},
    "required": ["claims"],
}

# V4 adds a coverage pass: every answer sentence must be accounted for, so a sentence that is
# dropped or fused into another sentence's claim is visible in the output instead of silent.
DECOMPOSE_SCHEMA_V2 = {
    "type": "object",
    "properties": {
        "sentences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "sentence": {"type": "string"},
                    "claims": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["sentence", "claims"],
            },
        },
        "claims": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["sentences", "claims"],
}

# ---------------- Optimized verifier: step 2, per-claim verification ----------------
VERIFY_SYSTEM_V1 = """You are a strict fact-checker. Decide whether ONE claim is grounded in the
numbered source sentences. Use ONLY the sources. Your world knowledge does not count.

Procedure:
1. Find every source sentence relevant to the claim (it may need several sentences, possibly
   from different passages).
2. Compare the claim with that evidence piece by piece: entity, action, numbers and units,
   comparisons (more/less, before/after), conditions (if/when/only), negations, quantifiers
   (all/some/always/by default), versions and dates.
3. Choose the verdict:
   - SUPPORTED: every part of the claim is stated or directly entailed by the sources.
     Paraphrases and equivalent numbers ("1,000" vs "1000", "roughly" vs "approximately") are fine.
   - CONTRADICTED: at least one part of the claim is incompatible with what the sources say
     (wrong number, inverted negation, swapped condition, "works" vs "does not work").
   - UNSUPPORTED: the sources do not mention it, or only mention part of it and say nothing
     that conflicts. Use this even if the claim is true in the real world.
   If one part is contradicted, the verdict is CONTRADICTED even if other parts are supported.
4. Cite evidence by sentence ID (e.g. "P1.S2"). Optionally add "quote": a shorter exact
   substring of that sentence. For SUPPORTED/CONTRADICTED you MUST cite at least one sentence.
   For UNSUPPORTED return an empty citations list.
5. Write the evidence and reasoning BEFORE the verdict. Keep reasoning to 1-3 sentences."""

VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"sentence_id": {"type": "string"}, "quote": {"type": "string"}},
                "required": ["sentence_id"],
            },
        },
        "reasoning": {"type": "string"},
        "verdict": {"type": "string", "enum": ["SUPPORTED", "CONTRADICTED", "UNSUPPORTED"]},
    },
    "required": ["evidence", "reasoning", "verdict"],
}

VERIFY_USER_TEMPLATE = """Sources:
{numbered_sources}

Claim to check:
{claim}"""

RETRY_FEEDBACK = """Your previous answer was invalid: {problem}
Valid sentence IDs are: {valid_ids}.
Answer again following the rules exactly."""

# ---------------- Optimized verifier V2: what the dev failures asked for ----------------
# See docs/ITERATIONS.md for the failure cases each change targets.

DECOMPOSE_SYSTEM_V2 = """You split an answer into atomic factual claims for fact-checking.

A claim is atomic when it carries exactly one verifiable fact: one subject, one relation,
one value or condition.

Rules:
1. Split on conjunctions, lists and compound predicates. "It uses two auxiliary files and
   checkpoints at 1000 pages" is two claims.
2. Keep a condition or qualifier attached to the fact it restricts: "X does A when C" is
   ONE claim, never "X does A" plus "C".
3. Give comparisons and numbers their own claim, with subject and unit intact, so they can
   be checked against the sources on their own ("may lose up to two seconds" must survive
   as one claim, not be merged into the sentence around it).
4. Make every claim self-contained: replace pronouns and vague references ("it", "this
   mode", "the file") with the full entity name taken from the answer.
5. Keep the answer's own wording for numbers, units, hedges (may, always, only, by
   default) and negations. Never correct, soften or "fix" a claim, even if you believe it
   is false: the verifier must see exactly what the answer said.
6. Skip text with no factual content (greetings, "I hope this helps", pure opinions,
   offers of further help). Never invent a fact the answer does not state, and never merge
   two separate facts into one claim.
7. You only see the answer, never any source. A claim that sounds wrong is still a claim.

Return an empty list if the answer has no factual claims."""

VERIFY_SYSTEM_V2 = """You are a strict fact-checker. Decide whether ONE claim is grounded in the
numbered source sentences. Use ONLY those sources: your world knowledge does not count, and it
is the usual reason a false claim feels true.

Work through these steps, in this order:
1. EVIDENCE: name the source sentences that bear on the claim, by ID. It may take several
   sentences, possibly from different passages. Sentences that are merely on the same topic are
   not evidence.
2. BREAKDOWN: split the claim into its parts - subject/entity, action, number and unit,
   comparison, condition, negation, quantifier/scope, version or date.
3. COMPARE each part against the evidence:
   - Numbers: compare value and unit. "1000", "1,000" and "approximately 1000" agree; "about
     1000" against a source "2000" is a mismatch. A source value that differs is a
     contradiction, not a gap.
   - Negation: "does not work over a network filesystem" contradicts "works over a network
     filesystem".
   - Conditions: "only when C", "if C", "by default", "unless" are part of the fact. An
     unconditional claim contradicted by a conditional source (or the reverse) is a mismatch.
   - Quantifiers and modality: all/some/always/may/by default must match what the sources say.
   - Entity: check the subject, not just the topic (file X vs file X-wal, liveness vs readiness).
   A part the sources never mention is a gap, not a contradiction.
4. VERDICT:
   - CONTRADICTED: the sources state something incompatible with any part of the claim. One
     contradicted part decides the whole claim.
   - SUPPORTED: the sources state or directly entail every part, and nothing in the sources
     conflicts with it. Paraphrase and synonyms are fine.
   - UNSUPPORTED: the sources are silent about the claim or about one of its parts, and nothing
     conflicts with it. Silence is UNSUPPORTED even when the claim is true in the real world.
   Never answer UNSUPPORTED when a source contradicts the claim.
5. CITE: list the sentence IDs from step 1. SUPPORTED and CONTRADICTED need at least one; add
   "quote" as an EXACT substring copied character for character from that sentence (copy it,
   do not retype it), keeping it short. UNSUPPORTED gets an empty list.

Write evidence and reasoning BEFORE the verdict. Keep reasoning to 1-3 sentences that name the
part that decided the verdict."""

# ---------------- Optimized verifier V3: decomposition must not lose clauses ----------------

DECOMPOSE_SYSTEM_V3 = """You split an answer into atomic factual claims for fact-checking.

A claim is atomic when it carries exactly one verifiable fact: one subject, one relation, one
value or condition.

Rules:
1. Split on conjunctions and compound predicates: "X does A and B" becomes "X does A" and
   "X does B".
2. Copy the answer's own words. Never summarise, shorten, tidy up or paraphrase a claim.
   A distorted claim must reach the checker exactly as it was written, so that the checker can
   reject it.
3. Every qualifier stays with the fact it restricts, and a trailing or subordinate clause is
   copied into the claim character for character. Examples of clauses that must survive:
   ", which is given in seconds", "even after the partition count changes", "unless replica-read-only
   is set", "in most scenarios", "by default", "regardless of whether it has an expiry set".
   A clause you drop is a fact the checker can no longer see.
4. Keep numbers, units, hedges (may, always, only) and negations exactly as written, even when
   they look wrong.
5. Make each claim self-contained: replace pronouns and vague references ("it", "this mode",
   "the file") with the full entity name taken from the answer, and keep the qualifiers from
   rule 3 while doing so.
6. Skip text with no factual content (greetings, pure opinions, offers of further help). Never
   invent a fact the answer does not state, and never merge two facts into one claim.
7. You only see the answer, never any source. Do not look anything up.

Return an empty list if the answer has no factual claims."""

# ---------------- Optimized verifier V4: decomposition may not fuse sentences ----------------
# Target (from the v3 failure list): decomposition rewording/fusing claims, e.g. merging "writes a
# checkpoint record" with "Checkpoints shorten crash recovery" into "A checkpoint record shortens
# crash recovery" on pg-checkpoint-20, and losing the clock-skew clause in jwt-claims-14.

DECOMPOSE_SYSTEM_V4 = """You split an answer into atomic factual claims for fact-checking.

Work in two passes.

Pass 1, sentences: copy every sentence of the answer verbatim, in order, into `sentences`. Do not
skip a sentence. A sentence with no factual content (a greeting, an opinion, an offer of help) stays
in the list with an empty `claims` array, so that the coverage is visible.

Pass 2, claims: for each sentence, list the claims it carries.
1. Default: one sentence produces one claim, copied word for word from that sentence.
2. Split a sentence only when it asserts two facts that can be true or false independently:
   "It uses two auxiliary files and checkpoints at 1000 pages" is two claims.
3. Never merge two sentences into one claim, and never build a claim out of clauses taken from
   different sentences. Fusion is the worst failure: it produces a claim that no sentence of the
   answer actually states, and the sentence it swallowed disappears from the review.
4. Every qualifier stays with the fact it restricts, and a trailing or subordinate clause is copied
   character for character: ", which is given in seconds", "even after the partition count changes",
   "regardless of whether it has an expiry set", "except when the process restarts".
5. Keep numbers, units, hedges (may, always, only, by default) and negations exactly as written,
   even when they look wrong. A distortion must reach the checker unchanged, so the checker can
   reject it.
6. Make a claim self-contained by replacing pronouns and vague references with the entity name taken
   from the answer, and change nothing else.

`claims` is the flattened list of every claim from every sentence, in order, with exact duplicates
removed. Never invent a fact the answer does not state. You only see the answer, never any source."""


@dataclass(frozen=True)
class PromptSet:
    version: str
    decompose: str
    verify: str
    decompose_schema: dict = field(default_factory=lambda: DECOMPOSE_SCHEMA)


PROMPT_SETS: dict[str, PromptSet] = {
    # v1: the architecture, as designed.
    "v1": PromptSet("v1", DECOMPOSE_SYSTEM_V1, VERIFY_SYSTEM_V1),
    # v2: checklist-style verification + reworked decomposition. Measured worse than v1 on dev
    # (macro-F1 0.954 vs 0.988): the long verification checklist and the aggressive split rules
    # did not pay for themselves. Kept for reproducibility, not the default.
    "v2": PromptSet("v2", DECOMPOSE_SYSTEM_V2, VERIFY_SYSTEM_V2),
    # v3: decomposition must copy qualifiers and trailing clauses verbatim. Fixed the unit-clause
    # loss on redis-cluster-long-31; dev 0.989 ± 0.000 claim accuracy, 0.997 macro-F1.
    "v3": PromptSet("v3", DECOMPOSE_SYSTEM_V3, VERIFY_SYSTEM_V1),
    # v4: v3 plus a sentence-coverage pass and an explicit no-fusion rule, targeting the fusion
    # failure on pg-checkpoint-20 and the lost clock-skew clause on jwt-claims-14.
    "v4": PromptSet("v4", DECOMPOSE_SYSTEM_V4, VERIFY_SYSTEM_V1, DECOMPOSE_SCHEMA_V2),
}

DEFAULT_PROMPT_VERSION = "v3"  # decided on dev: v3 > v1 > v2, see docs/ITERATIONS.md


def get_prompt_set(version: str | None = None) -> PromptSet:
    key = (version or DEFAULT_PROMPT_VERSION).lower()
    if key not in PROMPT_SETS:
        raise ValueError(f"unknown prompt version {version!r}; expected one of {sorted(PROMPT_SETS)}")
    return PROMPT_SETS[key]
