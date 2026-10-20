"""Recompute a claim's upstream label overlaps from its exact answer spans.

The v2.3 merge dropped `overlapping_source_labels` from the published gold claims, so the
natural 30 cases lost the provenance that v2.4 kept only for split children. This module
restores that field for every claim without changing any label.

Rules mirror `annotation.draft_claims.draft_ragtruth` and `ragtruth_verdict` exactly:
overlap is half-open character intersection between an exact answer span and an upstream
annotation; Conflict wins over Baseless, otherwise the claim is SUPPORTED.
"""
from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from pathlib import Path

from annotation import sources as S

VALID_LABELS = {'Evident Conflict', 'Subtle Conflict', 'Evident Baseless Info',
                'Subtle Baseless Info', 'Conflict', 'Baseless'}


def _check_label(label: dict, answer: str, case_id: str) -> None:
    if (label.get('label_type') not in VALID_LABELS
            or type(label.get('start')) is not int or type(label.get('end')) is not int
            or not 0 <= label['start'] < label['end'] <= len(answer)
            or answer[label['start']:label['end']] != label.get('text')):
        raise ValueError(f'{case_id}: invalid upstream label at {label.get("start")}:{label.get("end")}')


def exact_spans(claim: dict, answer: str, case_id: str) -> list[dict]:
    spans = claim.get('answer_spans') or []
    if not spans:
        raise ValueError(f'{case_id} {claim.get("claim_id")}: claim has no answer spans')
    out = []
    for span in spans:
        start, end = span.get('start'), span.get('end')
        if (span.get('match') != 'exact' or type(start) is not int or type(end) is not int
                or not 0 <= start < end <= len(answer)
                or answer[start:end] != span.get('quote')):
            raise ValueError(f'{case_id} {claim.get("claim_id")}: non-exact answer span')
        out.append(span)
    return out


def claims_overlaps(claim: dict, answer: str, labels: list[dict], case_id: str) -> list[dict]:
    """Upstream labels whose half-open character range intersects an exact answer span."""
    spans = exact_spans(claim, answer, case_id)
    for label in labels:
        _check_label(label, answer, case_id)
    return [copy.deepcopy(label) for label in labels
            if any(label['start'] < span['end'] and span['start'] < label['end'] for span in spans)]


def verdict_from_overlaps(overlaps: list[dict]) -> str:
    if any('Conflict' in label['label_type'] for label in overlaps):
        return 'CONTRADICTED'
    if any('Baseless' in label['label_type'] for label in overlaps):
        return 'UNSUPPORTED'
    return 'SUPPORTED'


def backfill_case(case: dict) -> tuple[dict, list[str]]:
    answer = case['generated_answer']
    labels = case.get('source_labels', {}).get('labels', [])
    updated = copy.deepcopy(case)
    errors = []
    for claim in updated['gold_claims']:
        overlaps = claims_overlaps(claim, answer, labels, case['id'])
        claim['overlapping_source_labels'] = overlaps
        derived = verdict_from_overlaps(overlaps)
        if derived != claim['verdict']:
            errors.append(f'{case["id"]} {claim["claim_id"]}: '
                          f'verdict {claim["verdict"]} but overlaps derive {derived}')
    return updated, errors


def verify_case(case: dict) -> list[str]:
    """Check stored overlaps and the verdict mapping for one case without rewriting it."""
    answer = case['generated_answer']
    labels = case.get('source_labels', {}).get('labels', [])
    errors = []
    for claim in case['gold_claims']:
        expected = claims_overlaps(claim, answer, labels, case['id'])
        stored = claim.get('overlapping_source_labels')
        if stored != expected:
            errors.append(f'{case["id"]} {claim["claim_id"]}: stored overlaps differ from replay')
        derived = verdict_from_overlaps(expected)
        if derived != claim['verdict']:
            errors.append(f'{case["id"]} {claim["claim_id"]}: '
                          f'verdict {claim["verdict"]} but overlaps derive {derived}')
    return errors


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def write_new(path: Path, rows: list[dict]) -> None:
    with path.open('x', encoding='utf-8') as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def report(rows: list[dict], source: Path, output: Path) -> dict:
    claims = [claim for case in rows for claim in case['gold_claims']]
    by_verdict = Counter(claim['verdict'] for claim in claims)
    with_overlap = Counter(claim['verdict'] for claim in claims
                           if claim['overlapping_source_labels'])
    types = Counter(label['label_type'] for claim in claims
                    for label in claim['overlapping_source_labels'])
    return {'design_version': '2.5', 'operation': 'overlap_backfill',
            'rule': 'Conflict wins, then Baseless, else SUPPORTED; exact half-open span overlap',
            'input': S.rel(source), 'input_sha256': digest(source),
            'output_sha256': digest(output), 'cases': len(rows), 'claims': len(claims),
            'claims_with_overlap': sum(bool(claim['overlapping_source_labels']) for claim in claims),
            'by_verdict': dict(sorted(by_verdict.items())),
            'with_overlap_by_verdict': dict(sorted(with_overlap.items())),
            'overlap_label_types': dict(sorted(types.items())),
            'verdict_replay_mismatches': 0}
