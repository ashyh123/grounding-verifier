"""Align predicted claims to gold claims (used by eval/metrics.py)."""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
from rapidfuzz import fuzz
from scipy.optimize import linear_sum_assignment

ALIGN_THRESHOLD = 60.0  # token_set_ratio below this => not the same claim


_NUMBER = re.compile(r"[-+]?\d+(?:[.,]\d+)*")
_WORD = re.compile(r"[a-z]+(?:'[a-z]+)?")
_NEGATIONS = {"not", "no", "never", "cannot", "without", "neither", "nor"}


@dataclass
class Alignment:
    pairs: list[tuple[int, int, float]]
    guard_rejected_pairs: int
    duplicate_pred_indices: frozenset[int]


def _guard_signature(text: str) -> tuple[frozenset[str], bool]:
    numbers = set()
    for match in _NUMBER.finditer(text):
        value = match.group().replace(",", "")
        # AES-256 and date separators are not signed numbers; a standalone -10 is.
        if value[0] in "+-" and match.start() and text[match.start() - 1].isalnum():
            value = value[1:]
        numbers.add(value.lstrip("+"))
    words = _WORD.findall(text.lower().replace("’", "'"))
    negative = any(word in _NEGATIONS or word.endswith("n't") for word in words)
    return frozenset(numbers), negative


def align_claims(pred: list[str], gold: list[str],
                 threshold: float = ALIGN_THRESHOLD) -> Alignment:
    """Match only threshold-passing, number/polarity-compatible pairs, one-to-one.

    Maximise the number of admissible matches, then total similarity. Rejected-pair count is
    over candidate edges (not assignments), so it can exceed the number of unmatched claims.
    A duplicate is an unmatched prediction with an admissible edge to a matched gold claim.
    Lexical compatibility is an approximation, not proof of semantic equivalence.
    """
    if not pred or not gold:
        return Alignment([], 0, frozenset())
    sim = np.zeros((len(pred), len(gold)))
    eligible = np.zeros(sim.shape, dtype=bool)
    p_signatures = [_guard_signature(p) for p in pred]
    g_signatures = [_guard_signature(g) for g in gold]
    rejected = 0
    for i, p in enumerate(pred):
        for j, g in enumerate(gold):
            sim[i, j] = fuzz.token_set_ratio(p.lower(), g.lower())
            if sim[i, j] >= threshold:
                if p_signatures[i] == g_signatures[j]:
                    eligible[i, j] = True
                else:
                    rejected += 1
    # One additional admissible match outweighs every possible similarity-score difference.
    bonus = 100 * min(len(pred), len(gold)) + 1
    rows, cols = linear_sum_assignment(-np.where(eligible, bonus + sim, 0))
    pairs = [(int(r), int(c), float(sim[r, c])) for r, c in zip(rows, cols) if eligible[r, c]]
    matched_pred = {p for p, _, _ in pairs}
    duplicates = frozenset(i for i in range(len(pred)) if i not in matched_pred and eligible[i].any())
    return Alignment(pairs, rejected, duplicates)


def span_overlap(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    """Overlap ratio between two (index, start, end) spans, relative to b (gold)."""
    if a[0] != b[0]:
        return 0.0
    inter = max(0, min(a[2], b[2]) - max(a[1], b[1]))
    return inter / max(1, b[2] - b[1])
