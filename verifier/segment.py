"""Split passages into sentences while keeping exact character offsets."""
from __future__ import annotations

import re
from dataclasses import dataclass

# A sentence ends at . ! ? (optionally followed by a closing quote/bracket)
# that is followed by whitespace and then an uppercase letter, digit, quote or bracket.
# "3.7.0" and "e.g. foo" are NOT split because no whitespace+uppercase follows the dot.
_BOUNDARY = re.compile(r"""(?<=[.!?])["')\]]?\s+(?=["'(\[A-Z0-9])""")
_ABBREVIATIONS = ("e.g.", "i.e.", "etc.", "vs.", "Mr.", "Dr.", "approx.", "Fig.", "No.")


@dataclass(frozen=True)
class Sentence:
    sid: str  # "P{passage}.S{sentence}", e.g. "P1.S2"
    passage_index: int
    start: int  # inclusive offset into the passage
    end: int  # exclusive offset into the passage
    text: str  # == passage[start:end]


def split_passage(passage: str, passage_index: int) -> list[Sentence]:
    sentences: list[Sentence] = []
    cursor = 0
    for m in _BOUNDARY.finditer(passage):
        candidate = passage[cursor : m.start()]
        if candidate.rstrip().endswith(_ABBREVIATIONS):
            continue
        _append(sentences, passage, passage_index, cursor, m.start())
        cursor = m.end()
    _append(sentences, passage, passage_index, cursor, len(passage))
    return sentences


def _append(out: list[Sentence], passage: str, p_idx: int, start: int, end: int) -> None:
    # trim whitespace but keep offsets exact
    while start < end and passage[start].isspace():
        start += 1
    while end > start and passage[end - 1].isspace():
        end -= 1
    if start < end:
        out.append(Sentence(f"P{p_idx}.S{len(out)}", p_idx, start, end, passage[start:end]))


def split_passages(passages: list[str]) -> list[Sentence]:
    result: list[Sentence] = []
    for i, p in enumerate(passages):
        result.extend(split_passage(p, i))
    return result


def render_numbered(passages: list[str]) -> str:
    """Text block given to the LLM, one sentence per line with its ID."""
    lines: list[str] = []
    for i, p in enumerate(passages):
        lines.append(f"<passage index={i}>")
        for s in split_passage(p, i):
            lines.append(f"[{s.sid}] {s.text}")
        lines.append("</passage>")
    return "\n".join(lines)


def split_answer(answer: str) -> list[str]:
    """Used by the baseline to turn an answer into 'claims'."""
    return [s.text for s in split_passage(answer, 0)]
