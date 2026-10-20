"""Locate initial evidence for the v2.5 subtle supplement using the v2.4 exact rules.

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
from annotation.draft_claims import annotation_model, preflight
from annotation.map_labels import map_case, read_jsonl, write_new
from annotation.merge import build_case, digest, unique
from annotation.v24 import evidence as v24_evidence
from annotation.v24.complete import materialize as v24_materialize

OUT = S.ANNOTATION_DIR / 'v2.5'
APPROVED_MODEL = 'mimo-v2.6-pro'
SUBSET = 'subtle_supplement'
PROTECTED = ('source', 'split', 'context_passages', 'generated_answer', 'source_labels', 'source_group_id')


def prepare_subtle(root: Path) -> tuple[list[dict], list[dict]]:
    directory = root / 'subtle'
    candidates = unique(read_jsonl(root / 'subtle_candidates.jsonl'), 'id')
    drafts = unique(read_jsonl(directory / 'drafts.jsonl'), 'id')
    redrafts = (unique(read_jsonl(directory / 'redrafts.jsonl'), 'id')
                if (directory / 'redrafts.jsonl').exists() else {})
    if set(drafts) != set(candidates) or set(redrafts) - set(drafts):
        raise ValueError('drafts must account for all selected cases without replacement')
    report = json.loads((directory / 'mapping-report.json').read_text(encoding='utf-8'))
    if digest(directory / 'drafts.jsonl') != report['drafts_sha256']:
        raise ValueError('draft hash differs from mapping')
    expected, removed, ready = [], [], []
    for cid, original in drafts.items():
        if any(original[k] != candidates[cid][k] for k in PROTECTED):
            raise ValueError('subtle supplement source changed')
        S.require_annotation_model(original['provenance']['annotation_model'], 'draft model')
        if original['provenance']['annotation_model'] != APPROVED_MODEL:
            raise ValueError('v2.5 draft model differs from the approved mimo-v2.6-pro')
        active = redrafts.get(cid, original)
        if cid in redrafts:
            before, _ = map_case(original)
            if (before['label_mapping']['status'] != 'needs_redraft' or active.get('redraft_error')
                    or any(active[k] != candidates[cid][k] for k in PROTECTED)
                    or active['provenance']['annotation_model'] != original['provenance']['annotation_model']):
                raise ValueError('invalid same-model single redraft')
        mapped, exclusions = map_case(active, redrafted=cid in redrafts)
        expected.append(mapped)
        removed.extend(exclusions)
        if mapped['label_mapping']['status'] == 'needs_redraft':
            raise ValueError('uncovered labels require the registered one redraft')
        if mapped['label_mapping']['status'] != 'ready':
            continue
        row = build_case(mapped)
        row.update(subset=SUBSET, tags=list(mapped['difficulty_tags']),
                   gold_claims=copy.deepcopy(mapped['claims']),
                   notes='Labels mapped from upstream RAGTruth humans; no second human review.',
                   provenance={**mapped['provenance'], 'annotation_origin': 'ragtruth_human',
                               'source_group': mapped['source_group_id'], 'design_version': '2.5',
                               'secondary_human_review': False})
        for claim in row['gold_claims']:
            claim.update(evidence=[], evidence_status='none')
        ready.append(row)
    if expected != read_jsonl(directory / 'mapped.jsonl') or removed != read_jsonl(directory / 'excluded.jsonl'):
        raise ValueError('mapping/exclusions differ from upstream replay')
    return ready, removed


def materialize(cases: list[dict], records: list[dict]) -> list[dict]:
    result = v24_materialize(cases, records)
    for case in result:
        for claim in case['gold_claims']:
            if claim.get('evidence_origin') == 'v2.4_initial_prompt':
                claim['evidence_origin'] = 'v2.5_initial_prompt'
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, default=OUT)
    args = ap.parse_args()
    directory = args.root / 'subtle'
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / 'evidenced.jsonl'
    if destination.exists():
        raise SystemExit('STOP: evidence output exists; replay with merge, no repeat calls')
    cases, _ = prepare_subtle(args.root)
    model = annotation_model()
    if model != APPROVED_MODEL:
        raise SystemExit('STOP: v2.5 authorization is limited to mimo-v2.6-pro')
    preflight()
    records = asyncio.run(v24_evidence.rerun(cases, directory, model))
    result = materialize(cases, records)
    write_new(destination, result)
    write_new(directory / 'model_doubts.jsonl', [r for r in records if r['doubt']])
    print(json.dumps({'cases': len(result), 'claims': sum(len(c['gold_claims']) for c in result),
                      'calls': len(records), 'exact': sum(r['evidence_status'] == 'exact' for r in records),
                      'model_doubts': sum(bool(r['doubt']) for r in records)}))


if __name__ == '__main__':
    main()
