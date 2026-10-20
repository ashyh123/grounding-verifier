"""Locate initial evidence for supplemental/recovered claims using the v2.4 exact rules.

All mapping, case dispositions, fixed labels and quote provenance are replayed before merge.
An interrupted evidence journal resumes only with identical requests and the approved model.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
from pathlib import Path

from annotation import sources as S
from annotation.draft_claims import annotation_model, preflight, draft_ragtruth
from annotation.find_evidence import EvidenceOutput
from annotation.map_labels import map_case, read_jsonl, write_new
from annotation.merge import build_case, digest, unique
from . import evidence, recover

OUT = S.ANNOTATION_DIR / 'v2.4'
APPROVED_MODEL = 'mimo-v2.6-pro'
PROTECTED = ('source', 'split', 'context_passages', 'generated_answer', 'source_labels', 'source_group_id')


def prepare_supplement(root: Path) -> tuple[list[dict], list[dict]]:
    directory = root / 'supplement'
    candidates = unique(read_jsonl(root / 'supplement_candidates.jsonl'), 'id')
    drafts = unique(read_jsonl(directory / 'drafts.jsonl'), 'id')
    redrafts = unique(read_jsonl(directory / 'redrafts.jsonl'), 'id') if (directory / 'redrafts.jsonl').exists() else {}
    if set(drafts) != set(candidates) or set(redrafts) - set(drafts):
        raise ValueError('drafts must account for all selected cases without replacement')
    if digest(directory / 'drafts.jsonl') != json.loads((directory / 'mapping-report.json').read_text())['drafts_sha256']:
        raise ValueError('draft hash differs from mapping')
    expected, removed, ready = [], [], []
    for cid, original in drafts.items():
        if any(original[k] != candidates[cid][k] for k in PROTECTED):
            raise ValueError('supplement source changed')
        S.require_annotation_model(original['provenance']['annotation_model'], 'draft model')
        if original['provenance']['annotation_model'] != APPROVED_MODEL:
            raise ValueError('v2.4 draft model differs from the approved mimo-v2.6-pro')
        active = redrafts.get(cid, original)
        if cid in redrafts:
            before, _ = map_case(original)
            if (before['label_mapping']['status'] != 'needs_redraft' or active.get('redraft_error')
                or any(active[k] != candidates[cid][k] for k in PROTECTED)
                or active['provenance']['annotation_model'] != original['provenance']['annotation_model']):
                raise ValueError('invalid same-model single redraft')
        mapped, exclusions = map_case(active, redrafted=cid in redrafts)
        expected.append(mapped); removed.extend(exclusions)
        if mapped['label_mapping']['status'] == 'needs_redraft':
            raise ValueError('uncovered labels require the registered one redraft')
        if mapped['label_mapping']['status'] != 'ready':
            continue
        row = build_case(mapped)
        row.update(subset='conflict_supplement', tags=list(mapped['difficulty_tags']),
                   gold_claims=copy.deepcopy(mapped['claims']),
                   notes='Labels mapped from upstream RAGTruth humans; no second human review.',
                   provenance={**mapped['provenance'], 'annotation_origin': 'ragtruth_human',
                               'source_group': mapped['source_group_id'], 'design_version': '2.4',
                               'secondary_human_review': False})
        for claim in row['gold_claims']:
            claim.update(evidence=[], evidence_status='none')
        ready.append(row)
    if expected != read_jsonl(directory / 'mapped.jsonl') or removed != read_jsonl(directory / 'excluded.jsonl'):
        raise ValueError('mapping/exclusions differ from upstream replay')
    return ready, removed


def prepare_recovered(root: Path) -> tuple[list[dict], list[dict]]:
    cases = unique(read_jsonl(root / 'natural.evidenced.jsonl'), 'id')
    candidates = unique(read_jsonl(S.ANNOTATION_DIR / 'candidates.jsonl'), 'id')
    parents = {r['claim_id']: r for d in ('pilot5-dev-v2.3', 'full-v2.3')
               for r in read_jsonl(S.ANNOTATION_DIR / d / 'excluded.jsonl') if r.get('claim')}
    calls = unique(read_jsonl(root / 'partial_split_calls.jsonl'), 'parent_claim_id')
    if set(calls) != set(parents):
        raise ValueError('recovery must account for exactly the original excluded parents')
    kept, removed = [], []
    for parent_id, call in calls.items():
        parent = parents[parent_id]; case = candidates[parent['case_id']]
        if call.get('error') or call['case_id'] != case['id'] or recover.request(case, parent['claim'])[1] != call['provenance']['prompt_sha256']:
            raise ValueError('invalid recovery request checkpoint')
        S.require_annotation_model(call['provenance']['model'], 'recovery model')
        if any(call['provenance'][field] != APPROVED_MODEL for field in ('model','response_model')):
            raise ValueError('recovery must use the approved mimo-v2.6-pro')
        derived, _ = draft_ragtruth(case, call['raw_draft']['claims'])
        for n, claim in enumerate(derived, 1):
            if claim['upstream_verdict'] is None:
                raise ValueError('recovery has nonliteral answer spans')
            claim.update(claim_id=f'{parent_id}-v24-split{n}', derived_from=[parent_id],
                         verdict=claim['upstream_verdict'], label_source='ragtruth_human', evidence_status='pending')
            wrapper = {'case_id':case['id'], 'claim':claim, 'split_provenance':call['provenance']}
            if any(f['flag'] == 'partial_overlap' for f in claim['flags']):
                removed.append({**wrapper, 'reason':'partial_overlap'})
            else:
                kept.append(wrapper)
        if derived != call['claims']:
            raise ValueError('recovery labels/spans differ from replay')
    if kept != read_jsonl(root / 'partial_recovered.jsonl') or removed != read_jsonl(root / 'partial_still_excluded.jsonl'):
        raise ValueError('recovery dispositions differ from replay')
    result = []
    for cid, case in cases.items():
        claims = [{**copy.deepcopy(r['claim']), 'split_provenance':r['split_provenance'],
                   'evidence':[], 'evidence_status':'none'} for r in kept if r['case_id'] == cid]
        if claims:
            result.append({**copy.deepcopy(case), 'gold_claims':claims})
    return result, removed


def materialize(cases: list[dict], records: list[dict]) -> list[dict]:
    wanted = {(c['id'], g['claim_id']) for c in cases for g in c['gold_claims'] if g['verdict'] != 'UNSUPPORTED'}
    by_key = {(r['case_id'], r['claim_id']): r for r in records}
    if len(by_key) != len(records) or set(by_key) != wanted:
        raise ValueError('missing/extra/duplicate evidence calls')
    result = copy.deepcopy(cases)
    for case in result:
        for claim in case['gold_claims']:
            if claim['verdict'] == 'UNSUPPORTED':
                continue
            row = by_key[(case['id'], claim['claim_id'])]
            if row.get('error') or row['verdict'] != claim['verdict'] or evidence.request(case, claim)[1] != row['provenance']['prompt_sha256']:
                raise ValueError('failed evidence call or changed label/request')
            for field in ('model', 'response_model'):
                S.require_annotation_model(row['provenance'][field], field)
                if row['provenance'][field] != APPROVED_MODEL:
                    raise ValueError('evidence must use the approved mimo-v2.6-pro')
            exact, rejected = [], []
            if not row.get('protocol_error'):
                raw = EvidenceOutput.model_validate(row['raw_evidence']).model_dump()
                exact, rejected = evidence.locate(case['context_passages'], raw['evidence'])
            if exact != row['evidence'] or rejected != row['rejected_quotes'] or row['evidence_status'] != ('exact' if exact else 'none'):
                raise ValueError('evidence differs from exact quote replay')
            claim.update(evidence=exact, evidence_status=row['evidence_status'],
                         evidence_provenance=row['provenance'], evidence_origin='v2.4_initial_prompt')
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('kind', choices=['supplement', 'recovered'])
    ap.add_argument('--root', type=Path, default=OUT)
    args = ap.parse_args()
    directory = args.root / args.kind
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / 'evidenced.jsonl'
    if destination.exists():
        raise SystemExit('STOP: evidence output exists; replay with merge, no repeat calls')
    cases, _ = (prepare_supplement if args.kind == 'supplement' else prepare_recovered)(args.root)
    model = annotation_model()
    if model != APPROVED_MODEL:
        raise SystemExit('STOP: v2.4 authorization is limited to mimo-v2.6-pro')
    preflight()
    records = asyncio.run(evidence.rerun(cases, directory, model))
    result = materialize(cases, records)
    write_new(destination, result)
    write_new(directory / 'model_doubts.jsonl', [r for r in records if r['doubt']])
    print(json.dumps({'cases':len(result), 'claims':sum(len(c['gold_claims']) for c in result),
                      'calls':len(records), 'exact':sum(r['evidence_status']=='exact' for r in records),
                      'model_doubts':sum(bool(r['doubt']) for r in records)}))


if __name__ == '__main__':
    main()
