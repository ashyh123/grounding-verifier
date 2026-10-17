"""Align predicted claims to gold claims (used by eval/metrics.py)."""
from __future__ import annotations

import numpy as np
from rapidfuzz import fuzz
from scipy.optimize import linear_sum_assignment

ALIGN_THRESHOLD = 60.0  # token_set_ratio below this => not the same claim


def align_claims(pred: list[str], gold: list[str],
                 threshold: float = ALIGN_THRESHOLD) -> list[tuple[int, int, float]]:
    """Return (pred_idx, gold_idx, score) pairs, one-to-one, score >= threshold."""
    if not pred or not gold:
        return []
    sim = np.zeros((len(pred), len(gold)))
    for i, p in enumerate(pred):
        for j, g in enumerate(gold):
            sim[i, j] = fuzz.token_set_ratio(p.lower(), g.lower())
    rows, cols = linear_sum_assignment(-sim)  # maximize similarity
    return [(int(r), int(c), float(sim[r, c])) for r, c in zip(rows, cols)
            if sim[r, c] >= threshold]


def span_overlap(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    """Overlap ratio between two (index, start, end) spans, relative to b (gold)."""
    if a[0] != b[0]:
        return 0.0
    inter = max(0, min(a[2], b[2]) - max(a[1], b[1]))
    return inter / max(1, b[2] - b[1])
