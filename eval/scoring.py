"""One owner for direct-parent and approved-unit alignment, shared by metrics and reports."""
from __future__ import annotations

from dataclasses import dataclass

from verifier.align import align_claims

from .dataset import EvalCase, GoldClaim


@dataclass
class ParentAlignment:
    matches: dict[int, list[int]]  # fully covered parent index -> prediction indices
    used_predictions: set[int]    # includes correctly aligned parts of an incomplete parent
    guard_rejected_pairs: int
    duplicate_predictions: int
    matched_units: dict[int, GoldClaim]  # split prediction index -> its approved reference unit


def align_case(case: EvalCase, predictions: list[dict], oracle: bool) -> ParentAlignment:
    if oracle:
        count = min(len(case.gold_claims), len(predictions))
        return ParentAlignment({i: [i] for i in range(count)}, set(range(count)), 0, 0, {})
    whole = align_claims([p['claim_text'] for p in predictions], [g.claim_text for g in case.gold_claims])
    matches = {gi: [pi] for pi, gi, _score in whole.pairs}
    used = {pi for pi, _gi, _score in whole.pairs}
    # Preserve valid whole-parent matches. Approved subitems only fill gaps using unused outputs.
    owners, reference_units = [], []
    for gi, units in sorted(case._scoring_units.items()):
        if gi not in matches:
            owners.extend([gi] * len(units))
            reference_units.extend(units)
    available = [i for i in range(len(predictions)) if i not in used]
    parts = align_claims([predictions[i]['claim_text'] for i in available],
                         [unit.claim_text for unit in reference_units])
    by_parent: dict[int, list[int]] = {}
    matched_units = {}
    for pi, ui, _score in parts.pairs:
        original_index = available[pi]
        used.add(original_index)
        matched_units[original_index] = reference_units[ui]
        by_parent.setdefault(owners[ui], []).append(original_index)
    for gi, indices in by_parent.items():
        if len(indices) == len(case._scoring_units[gi]):
            matches[gi] = indices
    duplicates = (set(whole.duplicate_pred_indices)
                  | {available[i] for i in parts.duplicate_pred_indices}) - used
    return ParentAlignment(matches, used, whole.guard_rejected_pairs + parts.guard_rejected_pairs,
                           len(duplicates), matched_units)


def parent_verdict(predictions: list[dict], indices: list[int]) -> str:
    """Registered parents/units are all SUPPORTED: every used child must be SUPPORTED.

    A contradiction takes precedence over missing support. Single-prediction parents keep the
    prediction's own verdict, including ordinary C/U parents and oracle position matches.
    """
    priority = {'SUPPORTED': 0, 'UNSUPPORTED': 1, 'CONTRADICTED': 2}
    return max((predictions[i]['verdict'] for i in indices), key=priority.__getitem__)
