"""Deterministic sentence splitter and sentence-level gold for v2.6.

Regex and fixed rules only: no model, no network, no locale. The rules are frozen with the dataset
(`RULES_VERSION`); changing any rule changes `gold_sentences` and requires a new dataset version.

Rules
1. A run of whitespace that contains a newline ends a sentence (lists, paragraphs, JSON-ish lines).
2. A terminator run `[.!?]+` plus optional closing quotes/brackets, followed by whitespace, ends a
   sentence when the next character is an uppercase letter, a digit, an opening quote/bracket or a
   list bullet, and the terminator is not an abbreviation / initial / list number (rule 3).
3. No break after: a fixed list of abbreviations (`ABBREVIATIONS`, compared case-insensitively
   without the final period), a single capital letter (an initial), a dotted abbreviation such as
   `e.g` or `U.S`, or a bare number that starts a line (`1. Item`).
4. Sentences tile the text: `start` of sentence i+1 equals `end` of sentence i, the first starts at 0
   and the last ends at len(text). Whitespace belongs to the sentence it follows (leading whitespace
   of the whole text belongs to the first sentence). Overlap tests use the content bounds
   (whitespace stripped), so a label never "touches" a sentence through whitespace alone.
"""
from __future__ import annotations

import re

RULES_VERSION = 'v2.6-sentences-1'

ABBREVIATIONS = frozenset({
    'mr', 'mrs', 'ms', 'dr', 'prof', 'sr', 'jr', 'st', 'mt', 'ft', 'vs', 'etc', 'inc', 'ltd', 'co',
    'corp', 'no', 'nos', 'vol', 'fig', 'approx', 'dept', 'est', 'gen', 'gov', 'sen', 'rep', 'lt',
    'col', 'capt', 'sgt', 'rev', 'hon', 'ave', 'blvd', 'rd', 'apt', 'ste', 'jan', 'feb', 'mar',
    'apr', 'jun', 'jul', 'aug', 'sep', 'sept', 'oct', 'nov', 'dec', 'a.m', 'p.m', 'e.g', 'i.e',
    'u.s', 'u.k', 'ph.d',
})
_TERMINATOR = re.compile(r'[.!?]+["\'’”)\]]*(\s+)')
_NEWLINE_RUN = re.compile(r'[^\S\n]*\n\s*')
_NEXT_START = re.compile(r'[A-Z0-9"\'‘“(\[\-*•]')
_LAST_TOKEN = re.compile(r'(\S+)$')


def _is_non_break(text: str, terminator_start: int) -> bool:
    """True when the period at `terminator_start` belongs to an abbreviation, initial or list number."""
    line_start = text.rfind('\n', 0, terminator_start) + 1
    token_match = _LAST_TOKEN.search(text[line_start:terminator_start])
    if not token_match:
        return False
    token = token_match.group(1).strip('"\'‘“([')
    if text[terminator_start] != '.':
        return False
    if token.lower() in ABBREVIATIONS:
        return True
    if len(token) == 1 and token.isalpha() and token.isupper():
        return True
    if re.fullmatch(r'(?:[A-Za-z]\.)+[A-Za-z]', token):
        return True
    if token.isdigit() and text[line_start:terminator_start].strip() == token:
        return True  # "1. Item": a bare number opening the line
    return False


def split_sentences(text: str) -> list[dict]:
    """Tile `text` into sentences: [{'index', 'start', 'end', 'text'}], text == ''.join(parts)."""
    breaks: set[int] = set()
    for match in _NEWLINE_RUN.finditer(text):
        if match.end() < len(text):
            breaks.add(match.end())
    for match in _TERMINATOR.finditer(text):
        nxt = match.end()
        if nxt >= len(text) or not _NEXT_START.match(text[nxt]):
            continue
        if _is_non_break(text, match.start()):
            continue
        breaks.add(nxt)
    cuts = [0, *sorted(b for b in breaks if 0 < b < len(text)), len(text)]
    return [{'index': i, 'start': a, 'end': b, 'text': text[a:b]}
            for i, (a, b) in enumerate(zip(cuts, cuts[1:])) if b > a]


def content_bounds(sentence: dict) -> tuple[int, int]:
    text = sentence['text']
    lead = len(text) - len(text.lstrip())
    return sentence['start'] + lead, sentence['start'] + len(text.rstrip())


def gold_sentences(answer: str, labels: list[dict]) -> list[dict]:
    """Sentence tiles plus `hallucinated` and the overlapping upstream spans (half-open ranges)."""
    out = []
    for sentence in split_sentences(answer):
        lo, hi = content_bounds(sentence)
        hits = [{'start': label['start'], 'end': label['end'], 'label_type': label['label_type']}
                for label in labels if label['start'] < hi and label['end'] > lo]
        out.append({**sentence, 'hallucinated': bool(hits), 'overlapping_labels': hits})
    return out
