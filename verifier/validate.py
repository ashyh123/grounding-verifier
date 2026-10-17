"""Deterministic validation of untrusted model output.

Nothing the model says about citations is trusted. Every citation returned by the
service is rebuilt here as passages[index][start:end].
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from .schemas import Citation, Claim, Verdict
from .segment import Sentence, split_passages

FUZZY_THRESHOLD = 95.0
MIN_QUOTE_CHARS = 8  # shorter quotes are too ambiguous to fuzzy-match

# curly quotes, en/em dashes, non-breaking space (written with chr() so copy/paste can't mangle them)
_CHAR_MAP = {
    chr(0x2018): "'", chr(0x2019): "'", chr(0x201C): '"', chr(0x201D): '"',
    chr(0x2013): "-", chr(0x2014): "-", chr(0x00A0): " ",
}


@dataclass
class RawCitation:
    """Citation exactly as the model produced it. Every field may be wrong."""
    sentence_id: str | None = None
    index: int | None = None
    quote: str | None = None


@dataclass
class ResolveResult:
    citation: Citation | None
    how: str  # "exact" | "normalized" | "fuzzy" | "sentence" | "relocated" | "invalid:<reason>"


def _normalize_with_map(text: str) -> tuple[str, list[int]]:
    """Lowercase, NFKC, unify quotes/dashes, collapse whitespace.
    Returns normalized text and, for every normalized char, its offset in `text`."""
    out_chars: list[str] = []
    offsets: list[int] = []
    prev_space = False
    for i, ch in enumerate(text):
        ch = _CHAR_MAP.get(ch, ch)
        for c in unicodedata.normalize("NFKC", ch).lower():
            if c.isspace():
                if prev_space:
                    continue
                c, prev_space = " ", True
            else:
                prev_space = False
            out_chars.append(c)
            offsets.append(i)
    return "".join(out_chars), offsets


def find_span(haystack: str, needle: str) -> tuple[int, int, str] | None:
    """Locate `needle` inside `haystack`. Returns (start, end, how) in haystack offsets."""
    needle = needle.strip()
    if not needle:
        return None
    pos = haystack.find(needle)
    if pos != -1:
        return pos, pos + len(needle), "exact"

    norm_h, offs = _normalize_with_map(haystack)
    norm_n, _ = _normalize_with_map(needle)
    norm_n = norm_n.strip()
    pos = norm_h.find(norm_n)
    if pos != -1 and norm_n:
        return offs[pos], offs[pos + len(norm_n) - 1] + 1, "normalized"

    if len(norm_n) >= MIN_QUOTE_CHARS:
        al = fuzz.partial_ratio_alignment(norm_n, norm_h, score_cutoff=FUZZY_THRESHOLD)
        if al is not None and al.dest_end > al.dest_start:
            start, end = offs[al.dest_start], offs[al.dest_end - 1] + 1
            start, end = _snap_to_words(haystack, start, end)
            return start, end, "fuzzy"
    return None


def _snap_to_words(text: str, start: int, end: int) -> tuple[int, int]:
    while start > 0 and text[start - 1].isalnum():
        start -= 1
    while end < len(text) and text[end].isalnum():
        end += 1
    return start, end


def _make(passages: list[str], idx: int, start: int, end: int) -> Citation:
    quote = passages[idx][start:end]
    assert passages[idx][start:end] == quote and quote  # invariant, never trust callers
    return Citation(index=idx, quote=quote, start_char=start, end_char=end)


def resolve_citation(passages: list[str], raw: RawCitation,
                     sentences: dict[str, Sentence] | None = None) -> ResolveResult:
    if sentences is None:
        sentences = {s.sid: s for s in split_passages(passages)}

    # 1) sentence-id path (optimized verifier)
    if raw.sentence_id:
        s = sentences.get(raw.sentence_id.strip().strip("[]"))
        if s is None:
            return ResolveResult(None, "invalid:unknown_sentence_id")
        if raw.quote:
            hit = find_span(s.text, raw.quote)
            if hit:
                a, b, how = hit
                return ResolveResult(_make(passages, s.passage_index, s.start + a, s.start + b), how)
        return ResolveResult(_make(passages, s.passage_index, s.start, s.end), "sentence")

    # 2) index + quote path (minimal verifier, or optimized fallback)
    if not raw.quote:
        return ResolveResult(None, "invalid:empty_quote")
    if raw.index is not None and 0 <= raw.index < len(passages):
        hit = find_span(passages[raw.index], raw.quote)
        if hit:
            a, b, how = hit
            return ResolveResult(_make(passages, raw.index, a, b), how)

    # 3) wrong / missing index: look in every passage, take the first exact-ish hit
    for i, p in enumerate(passages):
        hit = find_span(p, raw.quote)
        if hit:
            a, b, _ = hit
            return ResolveResult(_make(passages, i, a, b), "relocated")

    if raw.index is not None and not (0 <= raw.index < len(passages)):
        return ResolveResult(None, "invalid:index_out_of_range")
    return ResolveResult(None, "invalid:quote_not_found")


@dataclass
class DraftClaim:
    """A claim as produced by any verifier, before invariants are enforced."""
    claim_text: str
    verdict: str
    reasoning: str
    raw_citations: list[RawCitation] = field(default_factory=list)


@dataclass
class EnforceStats:
    raw_total: int = 0
    raw_invalid: int = 0
    warnings: list[str] = field(default_factory=list)


def resolve_all(passages: list[str], draft: DraftClaim,
                stats: EnforceStats) -> list[Citation]:
    sentences = {s.sid: s for s in split_passages(passages)}
    good: list[Citation] = []
    seen: set[tuple[int, int, int]] = set()
    for raw in draft.raw_citations:
        stats.raw_total += 1
        r = resolve_citation(passages, raw, sentences)
        if r.citation is None:
            stats.raw_invalid += 1
            stats.warnings.append(f"dropped citation for '{draft.claim_text[:40]}': {r.how}")
            continue
        if r.how not in ("exact", "sentence"):
            stats.raw_invalid += 1  # repaired => it was not valid as given
        key = (r.citation.index, r.citation.start_char, r.citation.end_char)
        if key not in seen:
            seen.add(key)
            good.append(r.citation)
    return good


def finalize_claim(draft: DraftClaim, citations: list[Citation],
                   stats: EnforceStats) -> Claim:
    """Apply the verdict/citation invariants. Call AFTER any retries are exhausted."""
    try:
        verdict = Verdict(draft.verdict.strip().upper())
    except ValueError:
        stats.warnings.append(f"unknown verdict {draft.verdict!r} -> UNSUPPORTED")
        verdict = Verdict.UNSUPPORTED
        citations = []

    if verdict is Verdict.UNSUPPORTED:
        citations = []
    elif not citations:
        stats.warnings.append(
            f"'{draft.claim_text[:40]}' was {verdict.value} without valid citations -> UNSUPPORTED")
        verdict = Verdict.UNSUPPORTED
    reasoning = draft.reasoning.strip() or "No reasoning provided by the model."
    return Claim(claim_text=draft.claim_text.strip(), verdict=verdict,
                 reasoning=reasoning, citations=citations)


def check_response_invariants(passages: list[str], claims: list[Claim]) -> list[str]:
    """Final safety net used in tests and right before returning a response.
    Returns a list of violations (empty list == OK)."""
    errors: list[str] = []
    for ci, c in enumerate(claims):
        if c.verdict is Verdict.UNSUPPORTED and c.citations:
            errors.append(f"claim {ci}: UNSUPPORTED must have no citations")
        if c.verdict is not Verdict.UNSUPPORTED and not c.citations:
            errors.append(f"claim {ci}: {c.verdict.value} needs citations")
        for cit in c.citations:
            if not 0 <= cit.index < len(passages):
                errors.append(f"claim {ci}: index {cit.index} out of range")
                continue
            if passages[cit.index][cit.start_char:cit.end_char] != cit.quote:
                errors.append(f"claim {ci}: offsets do not match quote")
            if cit.quote not in passages[cit.index]:
                errors.append(f"claim {ci}: quote not verbatim")
    return errors
