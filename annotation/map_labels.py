"""v2.3: derive labels from RAGTruth human spans, never from draft/review verdicts.

Failure modes: invalid offsets, overlapping/disconnected spans, 20/21 outside characters,
Conflict+Baseless precedence, >30% exclusions, uncovered labels before/after one redraft.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
from collections import Counter
from pathlib import Path

from . import sources as S
from .draft_claims import (CallStats, DraftClient, annotation_model, case_record,
                           draft_case, draft_ragtruth, preflight)
from verifier.llm import Usage
from datetime import datetime, timezone
import time


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_new(path: Path, records: list[dict]) -> None:
    with path.open('x', encoding='utf-8') as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + '\n')


def map_case(case: dict, redrafted: bool = False) -> tuple[dict, list[dict]]:
    if not case['source'].startswith('ragtruth_') or case.get('draft_error') or not case['claims']:
        raise ValueError(f"{case['id']}: requires a successful RAGTruth draft")
    mapped = copy.deepcopy(case)
    labels = case['source_labels']['labels']
    for label in labels:
        if (type(label.get('start')) is not int or type(label.get('end')) is not int
                or not 0 <= label['start'] < label['end'] <= len(case['generated_answer'])
                or label['label_type'] not in ('Evident Conflict', 'Subtle Conflict',
                                                'Evident Baseless Info', 'Subtle Baseless Info',
                                                'Conflict', 'Baseless')):
            raise ValueError(f"{case['id']}: invalid upstream annotation")
    # Recompute from original answer quotes; old verdicts, flags and waivers cannot set gold.
    derived, _ = draft_ragtruth(case, case['claims'])
    excluded, retained = [], []
    for original, claim in zip(case['claims'], derived):
        if claim['upstream_verdict'] is None:
            raise ValueError(f"{original['claim_id']}: answer spans must be unique exact substrings")
        row = {**copy.deepcopy(original), 'verdict': claim['upstream_verdict'],
               'upstream_verdict': claim['upstream_verdict'], 'answer_spans': claim['answer_spans'],
               'label_source': 'ragtruth_human', 'evidence': [], 'evidence_status': 'pending',
               'overlapping_source_labels': claim['overlapping_source_labels'],
               'flags': claim['flags']}
        if any(flag['flag'] == 'partial_overlap' for flag in claim['flags']):
            excluded.append({'case_id': case['id'], 'source': case['source'], 'split': case['split'],
                             'claim_id': row['claim_id'], 'reason': 'partial_overlap', 'claim': row})
        else:
            retained.append(row)
    uncovered = [label for label in labels if not any(
        label['start'] < span['end'] and span['start'] < label['end']
        for claim in derived for span in claim['answer_spans'])]
    reason = ('source_label_uncovered' if uncovered and redrafted else
              'too_many_excluded' if len(excluded) / len(case['claims']) > .30 else None)
    mapped.update(claims=retained, design_version='2.3',
                  label_mapping={'original_claims': len(case['claims']),
                                 'excluded_claims': len(excluded),
                                 'uncovered_source_labels': uncovered,
                                 'redraft_attempted': redrafted,
                                 'status': 'excluded' if reason else 'needs_redraft' if uncovered else 'ready',
                                 'exclusion_reason': reason})
    if reason:
        excluded.append({'case_id': case['id'], 'source': case['source'], 'split': case['split'],
                         'reason': reason, 'scope': 'case', 'retained_claims_removed': len(retained)})
    return mapped, excluded


async def redraft_once(case: dict, output: Path) -> dict:
    model = annotation_model()
    original_model = case['provenance']['annotation_model']
    if model != original_model:
        raise SystemExit(f'STOP: uncovered spans require the same drafting model: {original_model}')
    preflight()
    client, usage = DraftClient(model), Usage()
    stats = CallStats(started_at=datetime.now(timezone.utc).isoformat())
    started = time.monotonic()
    try:
        claims, notes, raw = await draft_case(case, client, usage)
        if client.response_model != original_model:
            raise ValueError('redraft response must use the original drafting model')
        for i, claim in enumerate(claims, 1):
            claim['claim_id'] = f"{case['id']}-redraft1-c{i}"
            claim['derived_from'] = [c['claim_id'] for c in case['claims']]
        stats.errors = notes
        record = None
    except Exception as error:
        record = {'id': case['id'], 'redraft_error': type(error).__name__}
    finally:
        stats.calls, stats.input_tokens, stats.output_tokens = usage.calls, usage.input_tokens, usage.output_tokens
        stats.retries, stats.seconds = usage.retries, time.monotonic() - started
        stats.finished_at = datetime.now(timezone.utc).isoformat()
        stats.response_model = client.response_model
        await client.close()
    if record is None:
        record = case_record(case, claims, stats, model, raw)
    record['redraft_provenance'] = {**vars(stats), 'model': model, 'parameters': client.parameters,
                                    'reason': 'source_label_uncovered'}
    with output.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + '\n')
    if record.get('redraft_error'):
        raise SystemExit('STOP: redraft failed; recorded one attempt, no automatic retry')
    return record


def summary(cases: list[dict], excluded: list[dict]) -> list[dict]:
    rows = []
    for case in cases:
        mapping = case['label_mapping']
        rows.append({'id': case['id'], 'claims': mapping['original_claims'],
                     'retained': len(case['claims']) if mapping['status'] == 'ready' else 0,
                     'labels': dict(Counter(c['verdict'] for c in case['claims'])),
                     'excluded_claims': mapping['excluded_claims'],
                     'exclusion_reasons': dict(Counter(e['reason'] for e in excluded
                                                      if e['case_id'] == case['id'])),
                     'status': mapping['status']})
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--drafts', type=Path, default=S.ANNOTATION_DIR / 'drafts.jsonl')
    ap.add_argument('--out-dir', type=Path, required=True)
    ap.add_argument('--only', nargs='+')
    ap.add_argument('--redraft-uncovered', action='store_true', help='paid call; user model/key authorization required')
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    destinations = [args.out_dir / name for name in ('mapped.jsonl', 'excluded.jsonl', 'mapping-report.json')]
    if any(p.exists() for p in destinations):
        raise SystemExit('STOP: mapping outputs already exist; archive them before a new run')
    cases = read_jsonl(args.drafts)
    if args.only:
        wanted = set(args.only)
        cases = [c for c in cases if c['id'] in wanted]
        if wanted != {c['id'] for c in cases}:
            raise SystemExit('STOP: unknown requested case IDs')
    if len({c['id'] for c in cases}) != len(cases):
        raise SystemExit('STOP: duplicate case IDs')
    redrafts = args.out_dir / 'redrafts.jsonl'
    prior = {r['id']: r for r in read_jsonl(redrafts)} if redrafts.exists() else {}
    mapped, exclusions = [], []
    for case in cases:
        row, removed = map_case(case)
        if row['label_mapping']['status'] == 'needs_redraft' and args.redraft_uncovered:
            redraft = prior.get(case['id'])
            if redraft is None:
                redraft = asyncio.run(redraft_once(case, redrafts))
            if redraft.get('redraft_error'):
                raise SystemExit('STOP: previous redraft failed; one attempt already recorded')
            row, removed = map_case(redraft, redrafted=True)
        mapped.append(row)
        exclusions.extend(removed)
    write_new(destinations[0], mapped)
    write_new(destinations[1], exclusions)
    report = {'design_version': '2.3', 'drafts_sha256': hashlib.sha256(args.drafts.read_bytes()).hexdigest(),
              'cases': summary(mapped, exclusions)}
    destinations[2].write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
