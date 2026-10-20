"""Merge the frozen v2.4 data with the v2.5 subtle supplement; emit dataset/statistics/audit.

    uv run python -m annotation.v25.merge
    uv run python -m annotation.v25.merge --check

No verifier or provider calls. Every claim keeps its human label; overlap provenance is replayed
from exact answer spans, and every evidence quote must be a literal substring.
"""
from __future__ import annotations

import argparse
import copy
import json
from collections import Counter
from pathlib import Path

from annotation import sources as S
from annotation.map_labels import read_jsonl, write_new
from annotation.merge import digest, distribution, unique
from eval.dataset import EvalCase, validate
from . import overlaps

OUT = S.ANNOTATION_DIR / 'v2.5'
V24 = OUT / 'v24_with_overlaps.jsonl'
SUBTLE = OUT / 'subtle' / 'evidenced.jsonl'
DATASET = S.ROOT / 'data' / 'eval_hard.v2.5.jsonl'
AUDIT = OUT / 'audit.json'
REPORT = OUT / 'final_report.md'
SENSITIVE = {'suspected_wrong_label', 'c_vs_u_boundary'}


def evidence_stats(cases: list[dict]) -> dict:
    gold = [claim for case in cases for claim in case['gold_claims'] if claim['verdict'] != 'UNSUPPORTED']
    exact = sum(claim['evidence_status'] == 'exact' for claim in gold)
    return {'exact': exact, 'eligible_sc': len(gold), 'coverage': exact / len(gold) if gold else None}


def claim_origin(claim: dict) -> str:
    types = [label['label_type'] for label in claim.get('overlapping_source_labels') or []]
    if any(name.startswith('Subtle') for name in types):
        return 'subtle'
    if any(name.startswith('Evident') for name in types):
        return 'evident'
    return 'clean'


def load_cases(root: Path) -> tuple[list[dict], list[dict]]:
    v24 = read_jsonl(root / 'v24_with_overlaps.jsonl')
    subtle_path = root / 'subtle' / 'evidenced.jsonl'
    subtle = read_jsonl(subtle_path) if subtle_path.exists() else []
    result = []
    for case in [*copy.deepcopy(v24), *copy.deepcopy(subtle)]:
        case['provenance']['design_version'] = '2.5'
        result.append(case)
    result.sort(key=lambda case: case['id'])
    errors = []
    for case in result:
        errors.extend(overlaps.verify_case(case))
        for claim in case['gold_claims']:
            for evidence in claim['evidence']:
                if (case['context_passages'][evidence['index']]
                        [evidence['start_char']:evidence['end_char']] != evidence['quote']):
                    errors.append(f'{case["id"]} {claim["claim_id"]}: nonliteral evidence')
    if errors:
        raise ValueError('; '.join(errors[:20]))
    model_errors = validate([EvalCase.model_validate(case) for case in result])
    if model_errors:
        raise ValueError('; '.join(model_errors))
    unique(result, 'id')
    return result, subtle


def read_exclusions(root: Path) -> tuple[list[dict], dict]:
    path = root / 'subtle' / 'excluded.jsonl'
    rows = read_jsonl(path) if path.exists() else []
    report = json.loads((root / 'subtle' / 'mapping-report.json').read_text(encoding='utf-8')) \
        if (root / 'subtle' / 'mapping-report.json').exists() else {}
    return rows, report


def doubt_summary(root: Path, claim_ids: set[str]) -> dict:
    path = root / 'doubt_classes.jsonl'
    rows = read_jsonl(path) if path.exists() else []
    by_category = Counter(row.get('category') or 'protocol_error' for row in rows)
    by_label = {}
    for row in rows:
        category = row.get('category') or 'protocol_error'
        by_label.setdefault(category, Counter())[row['verdict']] += 1
    sensitive = [row for row in rows if row.get('category') in SENSITIVE]
    return {'records': len(rows), 'in_dataset': sum(row['claim_id'] in claim_ids for row in rows),
            'by_category': dict(sorted(by_category.items())),
            'by_category_label': {key: dict(sorted(value.items()))
                                  for key, value in sorted(by_label.items())},
            'sensitivity_claims_in_dataset': sorted(row['claim_id'] for row in sensitive
                                                    if row['claim_id'] in claim_ids),
            'sensitivity_claims_classification_only': sorted(
                row['claim_id'] for row in sensitive if row['claim_id'] not in claim_ids),
            'protocol_errors': sum(bool(row.get('protocol_error')) for row in rows),
            'errors': sum(bool(row.get('error')) for row in rows)}


def build_audit(root: Path, cases: list[dict]) -> dict:
    gold = [(case, claim) for case in cases for claim in case['gold_claims']]
    joint = Counter((case['split'], case['source'], case['subset'], claim['verdict'])
                    for case, claim in gold)
    origin_joint = Counter((case['split'], case['source'], case['subset'], claim['verdict'],
                            claim_origin(claim)) for case, claim in gold)
    exclusions, mapping = read_exclusions(root)
    excluded_claims = [row for row in exclusions if row.get('claim')]
    excluded_cases = [row for row in exclusions if row.get('scope') == 'case']
    sensitivity = doubt_summary(root, {claim['claim_id'] for _case, claim in gold})
    test_subtle_c = sum(claim['verdict'] == 'CONTRADICTED' and case['split'] == 'test'
                        and any('Subtle Conflict' in label['label_type']
                                for label in claim.get('overlapping_source_labels') or [])
                        for case, claim in gold)
    excluded_subtle_c = sum(
        row['claim'].get('verdict') == 'CONTRADICTED' and any(
            'Subtle Conflict' in label['label_type']
            for label in row['claim'].get('overlapping_source_labels') or [])
        for row in excluded_claims)
    test_c = sum(claim['verdict'] == 'CONTRADICTED' and case['split'] == 'test'
                 for case, claim in gold)
    by_split_subset = []
    for split in ('dev', 'test', 'all'):
        for subset in ('all', 'natural', 'conflict_supplement', 'subtle_supplement'):
            part = [case for case in cases
                    if (split == 'all' or case['split'] == split)
                    and (subset == 'all' or case['subset'] == subset)]
            labels = Counter(claim['verdict'] for case in part for claim in case['gold_claims'])
            by_split_subset.append({
                'split': split, 'subset': subset, 'cases': len(part),
                'claims': sum(labels.values()), **{label: labels[label] for label in S.VERDICTS},
                'evidence': evidence_stats(part),
                'context_words': distribution([case['context_words'] for case in part]),
                'answer_words': distribution([len(case['generated_answer'].split()) for case in part])})
    by_task = {task: evidence_stats([case for case in cases if case['source'] == task])
               for task in sorted({case['source'] for case in cases})}
    selected = json.loads((root / 'selection.json').read_text(encoding='utf-8'))
    v24_audit = json.loads((S.ANNOTATION_DIR / 'v2.4' / 'audit.json').read_text(encoding='utf-8'))
    new_cases = [case for case in cases if case['subset'] == 'subtle_supplement']
    inputs = [p for p in root.rglob('*') if p.is_file()
              and p.name not in ('audit.json', 'freeze.json', 'final_report.md')]
    inputs += [S.ROOT / 'data' / 'eval_hard.v2.4.jsonl']
    return {
        'design_version': '2.5', 'base_freeze_commit': 'cbccac9',
        'historical_freeze_commit': 'c78d411', 'hard_test_verifier_run': False,
        'label_source': 'ragtruth_human', 'secondary_human_review': False,
        'selected_cases': 50 + len(read_jsonl(root / 'subtle_candidates.jsonl')),
        'retained_cases': len(cases),
        'retained_claims': len(gold), 'excluded_claims': len(excluded_claims),
        'excluded_cases': len(excluded_cases),
        'excluded_claim_details': [
            {'case_id': row['case_id'], 'claim_id': row['claim'].get('claim_id'),
             'label': row['claim'].get('verdict'), 'reason': row.get('reason')}
            for row in excluded_claims],
        'excluded_by_label': dict(sorted(Counter(
            row['claim'].get('verdict') for row in excluded_claims).items())),
        'excluded_subtle_conflict_c': excluded_subtle_c,
        'case_exclusion_details': [
            {'case_id': row['case_id'], 'reason': row.get('reason'),
             'retained_claims_removed': row.get('retained_claims_removed')}
            for row in excluded_cases],
        'historical_v24': {'retained_cases': v24_audit['retained_cases'],
                           'retained_claims': v24_audit['retained_claims'],
                           'excluded_claims': v24_audit['excluded_claims'],
                           'excluded_cases': len(v24_audit.get('excluded_cases') or [])},
        'by_split_task_subset_label': [
            {'split': split, 'source': source, 'subset': subset, 'label': label, 'claims': count}
            for (split, source, subset, label), count in sorted(joint.items())],
        'evident_subtle': [
            {'split': split, 'source': source, 'subset': subset, 'label': label,
             'origin': origin, 'claims': count}
            for (split, source, subset, label, origin), count in sorted(origin_joint.items())],
        'splits_subsets': by_split_subset,
        'evidence': {'overall': evidence_stats(cases), 'by_task': by_task,
                     'subtle_supplement': evidence_stats(new_cases)},
        'doubt_categories': sensitivity,
        'upstream_splits': dict(sorted(Counter(
            case['provenance'].get('upstream_split') for case in new_cases
            if case['subset'] == 'subtle_supplement').items())),
        'sampling': {'rules_sha256': selected['rules_sha256'],
                     'selection_sha256': digest(root / 'selection.json'),
                     'counts': selected['counts'], 'gpt_counts': selected['gpt_counts'],
                     'gpt_cases': selected.get('gpt_cases'),
                     'max_feasible_gpt_cases': selected.get('max_feasible_gpt_cases')},
        'mapping': mapping,
        'targets': {
            'test_contradicted': {'observed': test_c, 'minimum': 15, 'met': test_c >= 15},
            'test_contradicted_from_subtle_conflict': {
                'observed': test_subtle_c, 'minimum': 8, 'met': test_subtle_c >= 8},
            'data2txt_evidence': {
                'observed': by_task['ragtruth_data2txt']['coverage'], 'minimum': .7,
                'met': by_task['ragtruth_data2txt']['coverage'] >= .7}},
        'limitations': [
            'Upstream annotations may omit facts or contain errors; no second human review.',
            'Exact quotation proves textual presence, not semantic sufficiency.',
            'The targeted supplements change label prevalence; natural results must accompany all results.',
            'The sensitivity analysis removes claims, not cases; its CIs resample cases.'],
        'input_files': {S.rel(path.resolve()): digest(path) for path in sorted(set(inputs))},
    }


def render(audit: dict) -> str:
    lines = ['# v2.5 合并统计（数据诊断，无被测方案成绩）', '',
             '| split | subset | 案例 | 主张 | S | C | U | S/C 精确证据 |',
             '|---|---|---:|---:|---:|---:|---:|---:|']
    for row in audit['splits_subsets']:
        lines.append(f"| {row['split']} | {row['subset']} | {row['cases']} | {row['claims']} | "
                     f"{row['SUPPORTED']} | {row['CONTRADICTED']} | {row['UNSUPPORTED']} | "
                     f"{row['evidence']['exact']}/{row['evidence']['eligible_sc']} |")
    lines += ['', '| 任务 | S/C 精确证据 | 覆盖率 |', '|---|---:|---:|']
    for task, stats in audit['evidence']['by_task'].items():
        lines.append(f"| {task} | {stats['exact']}/{stats['eligible_sc']} | "
                     f"{stats['coverage']:.1%} |")
    lines += ['', '| split / subset | context words min / median / mean / max | '
                  'answer words min / median / mean / max |', '|---|---|---|']
    for row in audit['splits_subsets']:
        values = [' / '.join(str(round(row[key][name], 1)) if row[key][name] is not None else '-'
                             for name in ('min', 'median', 'mean', 'max'))
                  for key in ('context_words', 'answer_words')]
        lines.append(f"| {row['split']} / {row['subset']} | {values[0]} | {values[1]} |")
    lines += ['', '## 审计摘要', '',
              f"- 新增 {audit['sampling']['counts']['test']} test / "
              f"{audit['sampling']['counts']['dev']} dev；上游 split：{audit['upstream_splits']}；"
              f"GPT {audit['sampling']['gpt_cases']}/{sum(audit['sampling']['counts'].values())}。",
              f"- 剔除主张 {audit['excluded_claims']}；整例剔除 {audit['excluded_cases']}。"
              f"历史 v2.4 剔除主张 {audit['historical_v24']['excluded_claims']} 另记。",
              f"- 证据：全部 S/C {audit['evidence']['overall']['exact']}/"
              f"{audit['evidence']['overall']['eligible_sc']}；新增集 "
              f"{audit['evidence']['subtle_supplement']['exact']}/"
              f"{audit['evidence']['subtle_supplement']['eligible_sc']}。",
              f"- doubt_category：{audit['doubt_categories']['by_category']}；"
              f"敏感性分析将剔除 {len(audit['doubt_categories']['sensitivity_claims_in_dataset'])} 条。",
              f"- 目标：test Subtle-Conflict 来源的 C = "
              f"{audit['targets']['test_contradicted_from_subtle_conflict']['observed']}（≥8）："
              f"{'达到' if audit['targets']['test_contradicted_from_subtle_conflict']['met'] else '未达到'}；"
              f"partial_overlap 剔除中另有 {audit['excluded_subtle_conflict_c']} 条此类 C，"
              f"未追加案例、未改规则。",
              '', '```json', json.dumps({'targets': audit['targets'],
                                         'doubt_categories': audit['doubt_categories'],
                                         'upstream_splits': audit['upstream_splits']},
                                        ensure_ascii=False, indent=2), '```',
              '', '本轮修改只依据标签分布和流水线诊断；未运行任何 hard-test 被测方案。',
              '所有标签来自 RAGTruth 人工跨度映射；引文精确存在不保证语义充分，无二次人工确认。']
    return '\n'.join(lines) + '\n'


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, default=OUT)
    ap.add_argument('--out', type=Path, default=DATASET)
    ap.add_argument('--check', action='store_true')
    args = ap.parse_args()
    cases, new_cases = load_cases(args.root)
    if args.check:
        if read_jsonl(args.out) != cases:
            raise SystemExit('STOP: dataset differs from replayed merge')
        audit = json.loads((args.root / 'audit.json').read_text(encoding='utf-8'))
        if audit['retained_cases'] != len(cases) or audit['retained_claims'] != sum(
                len(case['gold_claims']) for case in cases):
            raise SystemExit('STOP: audit counts differ from dataset')
        for name, sha in audit['input_files'].items():
            if digest(S.ROOT / name) != sha:
                raise SystemExit(f'STOP: audit input changed: {name}')
        print(json.dumps({'cases': len(cases), 'claims': audit['retained_claims'],
                          'subtle_cases': len(new_cases), 'errors': 0}, ensure_ascii=False))
        return
    if args.out.exists() or (args.root / 'audit.json').exists() or (args.root / 'final_report.md').exists():
        raise SystemExit('STOP: v2.5 merge outputs exist; archive before rerunning')
    audit = build_audit(args.root, cases)
    write_new(args.out, cases)
    (args.root / 'audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n',
                                          encoding='utf-8')
    (args.root / 'final_report.md').write_text(render(audit), encoding='utf-8')
    print(json.dumps({'cases': len(cases), 'claims': audit['retained_claims'],
                      'subtle_cases': len(new_cases),
                      'test_subtle_c': audit['targets']['test_contradicted_from_subtle_conflict']},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
