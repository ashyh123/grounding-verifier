"""Merge v2.3 human-mapped runs, rechecking source labels and exact evidence offline.

Failure modes: missing/extra/duplicate cases, altered originals, altered labels, uncompleted
mapping, altered exclusions, missing/extra/error checkpoints, inexact quotes, output overwrite.
Legacy review merging is archived in merge_review.py and is not part of this pipeline.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median

from eval.dataset import EvalCase, validate
from . import sources as S
from .find_evidence import EvidenceOutput, locate, request
from .map_labels import map_case, read_jsonl, write_new


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unique(rows: list[dict], key: str) -> dict:
    result = {r[key]: r for r in rows}
    if len(result) != len(rows):
        raise ValueError(f'duplicate {key}')
    return result


def distribution(values: list[int]) -> dict:
    return {'n': len(values), 'min': min(values) if values else None,
            'median': median(values) if values else None,
            'mean': mean(values) if values else None, 'max': max(values) if values else None}


def verify_run(directory: Path, draft_files: list[Path], candidates: dict) -> tuple[list[dict], list[dict], list[dict], list[Path]]:
    report = json.loads((directory / 'mapping-report.json').read_text())
    matched = [p for p in draft_files if digest(p) == report['drafts_sha256']]
    if len(matched) != 1:
        raise ValueError('mapping must match exactly one original draft file SHA256')
    source = unique(read_jsonl(matched[0]), 'id')
    mapped = read_jsonl(directory / 'mapped.jsonl')
    evidenced = read_jsonl(directory / 'evidenced.jsonl')
    if set(source) != set(unique(mapped, 'id')) or set(source) != set(unique(evidenced, 'id')):
        raise ValueError('run must account for every draft, including excluded cases')
    redrafts_path = directory / 'redrafts.jsonl'
    redrafts = unique(read_jsonl(redrafts_path), 'id') if redrafts_path.exists() else {}
    if set(redrafts) - set(source):
        raise ValueError('redraft outside source cases')
    expected, exclusions = [], []
    protected = ('source', 'split', 'context_passages', 'generated_answer', 'source_labels', 'source_group_id')
    for cid, original in source.items():
        candidate = candidates.get(cid)
        if candidate is None or any(original[k] != candidate[k] for k in protected):
            raise ValueError(f'{cid}: original candidate fields changed')
        active = redrafts.get(cid, original)
        if cid in redrafts:
            before, _ = map_case(original)
            if (before['label_mapping']['status'] != 'needs_redraft' or active.get('redraft_error')
                    or any(active[k] != candidate[k] for k in protected)
                    or active['provenance']['annotation_model'] != original['provenance']['annotation_model']):
                raise ValueError(f'{cid}: invalid single redraft')
        row, removed = map_case(active, redrafted=cid in redrafts)
        expected.append(row)
        exclusions.extend(removed)
    if expected != mapped or exclusions != read_jsonl(directory / 'excluded.jsonl'):
        raise ValueError('mapping/exclusions differ from recomputed upstream rules')
    expected_by_id = unique(expected, 'id')
    calls = read_jsonl(directory / 'evidence_calls.jsonl')
    records = {}
    for row in calls:
        key = (row['case_id'], row['claim_id'])
        if key in records or row.get('error'):
            raise ValueError('duplicate or failed evidence checkpoint')
        records[key] = row
    wanted = set()
    for case in evidenced:
        baseline = copy.deepcopy(expected_by_id[case['id']])
        if baseline['label_mapping']['status'] == 'needs_redraft':
            raise ValueError('uncovered upstream label requires one redraft')
        if baseline['label_mapping']['status'] == 'ready':
            for claim in baseline['claims']:
                key = (case['id'], claim['claim_id'])
                wanted.add(key)
                if key not in records:
                    raise ValueError('missing evidence checkpoint')
                record = records[key]
                _, prompt_hash = request(baseline, claim)
                if (record['verdict'] != claim['verdict'] or record['label_source'] != 'ragtruth_human'
                        or record['provenance']['prompt_sha256'] != prompt_hash):
                    raise ValueError('evidence checkpoint changed fixed label or prompt')
                S.require_annotation_model(record['provenance']['model'], 'evidence model')
                exact = []
                if claim['verdict'] != 'UNSUPPORTED' and not record.get('protocol_error'):
                    S.require_annotation_model(record['provenance']['response_model'], 'response model')
                    data = EvidenceOutput.model_validate(record['raw_evidence']).model_dump()
                    exact, rejected = locate(case['context_passages'], data['evidence'])
                    if rejected != record['rejected_quotes']:
                        raise ValueError('rejected quotes changed')
                status = 'exact' if exact else 'none'
                if record['evidence'] != exact or record['evidence_status'] != status:
                    raise ValueError('evidence must be exactly re-derived from original quotes')
                claim.update(evidence=exact, evidence_status=status,
                             evidence_provenance=record['provenance'])
        if baseline != case:
            raise ValueError(f"{case['id']}: evidenced record changed source, mapping or claim fields")
    if wanted != set(records):
        raise ValueError('extra evidence checkpoint outside retained claims')
    if read_jsonl(directory / 'model_doubts.jsonl') != [r for r in calls if r['doubt']]:
        raise ValueError('doubts must match evidence journal')
    inputs = [matched[0], *(directory / name for name in (
        'mapped.jsonl', 'mapping-report.json', 'excluded.jsonl', 'evidenced.jsonl',
        'evidence_calls.jsonl', 'model_doubts.jsonl'))]
    if redrafts_path.exists():
        inputs.append(redrafts_path)
    return evidenced, exclusions, calls, inputs


def build_case(case: dict) -> dict:
    return {k: copy.deepcopy(case[k]) for k in (
        'id', 'source', 'split', 'context_passages', 'generated_answer', 'generator_model',
        'source_labels', 'context_words', 'difficulty_tags')}
    # The caller attaches gold and provenance to avoid implicit review metadata.


def assemble(candidates: list[dict], runs: list[Path], drafts: list[Path]) -> tuple[list[dict], dict]:
    candidate_by_id = unique(candidates, 'id')
    active, excluded, calls, inputs = [], [], [], []
    for run in runs:
        cases, removed, journal, files = verify_run(run, drafts, candidate_by_id)
        active.extend(cases); excluded.extend(removed); calls.extend(journal); inputs.extend(files)
    if set(unique(active, 'id')) != set(candidate_by_id):
        raise ValueError('runs must cover exactly the selected candidate IDs; no replacement sampling')
    result, dispositions = [], []
    by_task, by_split, by_label = defaultdict(Counter), defaultdict(Counter), defaultdict(Counter)
    joint = defaultdict(Counter)
    for case in sorted(active, key=lambda c: c['id']):
        keep = case['label_mapping']['status'] == 'ready'
        reason = case['label_mapping']['exclusion_reason']
        # Every active draft claim has exactly one disposition, including whole-case removal.
        partial = [r['claim'] for r in excluded if r['case_id'] == case['id'] and r.get('claim')]
        for claim in partial + case['claims']:
            removed = claim in partial or not keep
            why = 'partial_overlap' if claim in partial else reason
            outcome = 'excluded' if removed else 'retained'
            task, split, label = case['source'], case['split'], claim['verdict']
            by_task[task][outcome] += 1; by_split[split][outcome] += 1; by_label[label][outcome] += 1
            joint[(task, split, label)][outcome] += 1
            if removed:
                dispositions.append({'case_id': case['id'], 'claim_id': claim['claim_id'],
                                     'source': task, 'split': split, 'verdict': label, 'reason': why})
        if not keep:
            continue
        row = build_case(case)
        row.update(tags=list(case['difficulty_tags']), gold_claims=[
            {k: copy.deepcopy(c[k]) for k in ('claim_id', 'claim_text', 'answer_spans', 'verdict',
                'label_source', 'evidence_status', 'evidence', 'evidence_provenance')}
            | ({'derived_from': c['derived_from']} if 'derived_from' in c else {}) for c in case['claims']],
            notes='Labels mapped from RAGTruth human spans; no second human review.',
            provenance={**case['provenance'], 'annotation_origin': 'ragtruth_human',
                        'source_group': case['source_group_id'], 'design_version': '2.3',
                        'secondary_human_review': False})
        result.append(row)
    errors = validate([EvalCase.model_validate(c) for c in result])
    if errors:
        raise ValueError('invalid merged dataset: ' + '; '.join(errors))
    stats = {}
    for split in ('dev', 'test'):
        part = [c for c in result if c['split'] == split]
        claims = [g for c in part for g in c['gold_claims']]
        context = [c['context_words'] for c in part]
        stats[split] = {'cases': len(part), 'claims': len(claims),
            'labels': {lab: sum(g['verdict'] == lab for g in claims) for lab in S.VERDICTS},
            'multi_passage_evidence_claims': sum(len({e['index'] for e in g['evidence']}) > 1 for g in claims),
            'all_retained_labels_supported': sum(all(g['verdict'] == 'SUPPORTED' for g in c['gold_claims']) for c in part),
            'upstream_clean_answers': sum(not c['source_labels']['labels'] for c in part),
            'context_words': distribution(context),
            'context_length_buckets': {name: sum(lo <= n < hi for n in context) for name, lo, hi in (
                ('0-399', 0, 400), ('400-799', 400, 800), ('800+', 800, float('inf')))},
            'answer_words': distribution([len(c['generated_answer'].split()) for c in part]),
            'claims_per_case': distribution([len(c['gold_claims']) for c in part])}
    gold = [g for c in result for g in c['gold_claims']]
    eligible = sum(g['verdict'] != 'UNSUPPORTED' for g in gold)
    exact = sum(g['evidence_status'] == 'exact' for g in gold)
    audit = {'design_version': '2.3', 'label_source': 'ragtruth_human', 'secondary_human_review': False,
             'selected_cases': len(candidates), 'retained_cases': len(result),
             'retained_claims': len(gold), 'excluded_claims': len(dispositions),
             'by_task': dict(by_task), 'by_split': dict(by_split), 'by_label': dict(by_label),
             'by_task_split_label': [{'source': t, 'split': s, 'verdict': l, **counts}
                                    for (t,s,l), counts in sorted(joint.items())],
             'excluded_claim_details': dispositions,
             'claim_exclusion_reasons': dict(Counter(r['reason'] for r in dispositions)),
             'case_exclusion_reasons': dict(Counter(c['label_mapping']['exclusion_reason'] for c in active
                                                    if c['label_mapping']['status'] == 'excluded')),
             'excluded_cases': [{'id': c['id'], 'source': c['source'], 'split': c['split'],
                                 'reason': c['label_mapping']['exclusion_reason']} for c in active
                                if c['label_mapping']['status'] == 'excluded'],
             'redrafted_cases': [c['id'] for c in active if c['label_mapping']['redraft_attempted']],
             'evidence': {'exact_claims': exact, 'eligible_sc_claims': eligible,
                          'sc_coverage': exact / eligible if eligible else None,
                          'all_claim_coverage': exact / len(gold) if gold else None,
                          'rejected_quotes': sum(len(r['rejected_quotes']) for r in calls)},
             'model_doubts': sum(bool(r['doubt']) for r in calls),
             'model_label_doubts_or_not_found': sum(bool(r['doubt']) and not r.get('protocol_error') for r in calls),
             'unusable_model_outputs': sum(bool(r.get('protocol_error')) for r in calls),
             'usage': {k: sum(r['provenance'][k] for r in calls)
                       for k in ('calls', 'input_tokens', 'output_tokens')},
             'splits': stats,
             'input_files': {S.rel(p.resolve()): digest(p) for p in sorted(set(inputs))},
             'limitations': ['Unreviewed upstream human labels can contain omissions or mistakes.',
                            'Exclusions may bias retained cases toward easier examples.',
                            'Exact quotation establishes presence, not semantic sufficiency.',
                            'Multi-passage evidence does not establish necessary multi-passage reasoning.',
                            'All-retained-S answers may still contain excluded hallucinated claims.']}
    return result, audit


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--runs', nargs='+', type=Path, required=True)
    ap.add_argument('--drafts', nargs='+', type=Path, required=True)
    ap.add_argument('--candidates', type=Path, default=S.ANNOTATION_DIR / 'candidates.jsonl')
    ap.add_argument('--out', type=Path, default=S.ROOT / 'data/eval_hard.jsonl')
    ap.add_argument('--audit', type=Path, default=S.ANNOTATION_DIR / 'audit.json')
    args = ap.parse_args()
    if args.out.exists() or args.audit.exists():
        raise SystemExit('STOP: archive existing dataset/audit before creating a new version')
    cases, audit = assemble(read_jsonl(args.candidates), args.runs, args.drafts)
    audit['input_files'][S.rel(args.candidates.resolve())] = digest(args.candidates)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    write_new(args.out, cases)
    audit['dataset_sha256'] = digest(args.out)
    with args.audit.open('x', encoding='utf-8') as stream:
        json.dump(audit, stream, ensure_ascii=False, indent=2); stream.write('\n')
    print(json.dumps({k: audit[k] for k in ('selected_cases', 'retained_cases', 'retained_claims',
          'excluded_claims', 'excluded_cases', 'evidence', 'model_doubts', 'splits')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
