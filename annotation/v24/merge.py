"""Replay v2.4 annotation journals, merge a separate dataset, emit statistics/audit.

Rejects changed historical artifacts, source fields, mapping, requests, labels, quotes,
missing/extra journals and output overwrite. No verifier or provider calls.
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
from . import evidence
from .complete import OUT, prepare_supplement, prepare_recovered, materialize


def check_protected(root: Path):
    for name, sha in json.loads((root / 'protected-v2.3-sha256.json').read_text()).items():
        if digest(S.ROOT / name) != sha:
            raise ValueError(f'protected historical artifact changed: {name}')


def verify_natural(root: Path) -> list[dict]:
    original = read_jsonl(S.ROOT / 'data/eval_hard.jsonl')
    old_calls = [r for d in ('pilot5-dev-v2.3', 'full-v2.3')
                 for r in read_jsonl(S.ANNOTATION_DIR / d / 'evidence_calls.jsonl')]
    repaired, events = evidence.offline(original, old_calls)
    if repaired != read_jsonl(root / 'natural.offline.jsonl') or events != read_jsonl(root / 'offline_evidence.jsonl'):
        raise ValueError('natural offline evidence differs from original quote replay')
    jobs = []
    for c in original:
        claims = [copy.deepcopy(g) for g in c['gold_claims'] if g['verdict'] != 'UNSUPPORTED' and g['evidence_status'] == 'none']
        if claims:
            jobs.append({**copy.deepcopy(c), 'gold_claims':claims})
    calls = read_jsonl(root / 'evidence_reruns.jsonl')
    located = materialize(jobs, calls)
    by_key = {(c['id'], g['claim_id']):g for c in located for g in c['gold_claims']}
    for case in repaired:
        for claim in case['gold_claims']:
            found = by_key.get((case['id'], claim['claim_id']))
            if found is None:
                continue
            if found['evidence']:
                for ref in found['evidence']:
                    if not any(all(ref[k] == old[k] for k in ('index','quote','start_char','end_char')) for old in claim['evidence']):
                        claim['evidence'].append(ref)
                claim['evidence_status'] = 'exact'
                if claim['evidence_origin'] == 'none':
                    claim['evidence_origin'] = 'new_prompt_rerun'
            claim['v2.4_evidence_provenance'] = found['evidence_provenance']
    if repaired != read_jsonl(root / 'natural.evidenced.jsonl'):
        raise ValueError('natural final evidence differs from offline/new-prompt union')
    return repaired


def evidence_stats(cases):
    gold = [g for c in cases for g in c['gold_claims'] if g['verdict'] != 'UNSUPPORTED']
    exact = sum(g['evidence_status'] == 'exact' for g in gold)
    return {'exact':exact, 'eligible_sc':len(gold), 'coverage':exact/len(gold) if gold else None}


def statistics(cases):
    gold = [g for c in cases for g in c['gold_claims']]
    words = [c['context_words'] for c in cases]
    return {'cases':len(cases), 'claims':len(gold),
            'labels':{lab:sum(g['verdict'] == lab for g in gold) for lab in S.VERDICTS},
            'evidence':evidence_stats(cases),
            'context_words':distribution(words),
            'answer_words':distribution([len(c['generated_answer'].split()) for c in cases]),
            'claims_per_case':distribution([len(c['gold_claims']) for c in cases]),
            'context_length_buckets':{name:sum(lo <= n < hi for n in words) for name,lo,hi in
                                     [('0-399',0,400),('400-799',400,800),('800+',800,float('inf'))]}}


def append_recoveries(natural, recovered):
    """Do not score an identical recovery of an already represented answer occurrence twice.

    Text and human label must be identical, and literal answer spans must overlap. Repeated
    assertions elsewhere in the answer remain separate; no semantic/fuzzy deduplication.
    """
    by_id = unique(natural, 'id')
    duplicates = []
    for row in recovered:
        target = by_id[row['id']]['gold_claims']
        for child in row['gold_claims']:
            existing = [g for g in target if g['claim_text'] == child['claim_text']
                        and g['verdict'] == child['verdict'] and any(a['start'] < b['end'] and b['start'] < a['end']
                            for a in g['answer_spans'] for b in child['answer_spans'])]
            if existing:
                original = existing[0]
                original.setdefault('merged_derivations', []).append({k:copy.deepcopy(child[k])
                    for k in ('claim_id','derived_from','answer_spans','split_provenance')})
                duplicates.append({'case_id':row['id'], 'claim':child,
                                   'represented_by':original['claim_id'], 'reason':'already_represented_same_answer_span'})
            else:
                target.append(child)
    return duplicates


def assemble(root: Path):
    check_protected(root)
    selection = json.loads((root/'selection.json').read_text())
    if (selection['rules_sha256'] != digest(root/'sampling_rules.json')
        or selection['natural_sha256'] != digest(S.ROOT/'data/eval_hard.jsonl')
        or selection['selected_ids'] != [c['id'] for c in read_jsonl(root/'supplement_candidates.jsonl')]):
        raise ValueError('sampling rules, original dataset or selected IDs changed')
    natural = verify_natural(root)
    supplement, exclusions = prepare_supplement(root)
    recovered, still_partial = prepare_recovered(root)
    journals = {}
    for name, baseline in [('supplement',supplement),('recovered',recovered)]:
        rows = read_jsonl(root / name / 'evidence_reruns.jsonl')
        final = materialize(baseline, rows)
        if final != read_jsonl(root / name / 'evidenced.jsonl'):
            raise ValueError(f'{name}: evidence output changed')
        if [r for r in rows if r['doubt']] != read_jsonl(root / name / 'model_doubts.jsonl'):
            raise ValueError('doubt log differs from evidence journal')
        journals[name] = rows
        if name == 'supplement':
            supplement = final
        else:
            recovered = final
    duplicate_recoveries = append_recoveries(natural, recovered)
    for row in natural:
        row['provenance']['design_version'] = '2.4'
    result = sorted([*natural, *supplement], key=lambda c:c['id'])
    errors = validate([EvalCase.model_validate(c) for c in result])
    for c in result:
        gold = c['gold_claims']
        unique(gold, 'claim_id')
        for g in gold:
            if g['label_source'] != 'ragtruth_human':
                raise ValueError('nonhuman fixed label')
            for e in g['evidence']:
                if c['context_passages'][e['index']][e['start_char']:e['end_char']] != e['quote']:
                    raise ValueError('nonliteral evidence offsets')
    if errors:
        raise ValueError('; '.join(errors))
    selected = [*read_jsonl(root / 'natural_cases.jsonl'), *read_jsonl(root / 'supplement_candidates.jsonl')]
    metadata = unique(selected, 'id')
    dispositions = list(duplicate_recoveries)
    for item in still_partial:
        dispositions.append({'case_id':item['case_id'], 'claim':item['claim'], 'reason':'partial_overlap'})
    for item in exclusions:
        if item.get('claim'):
            dispositions.append(item)
    mapped = read_jsonl(root / 'supplement/mapped.jsonl')
    excluded_cases = []
    for c in mapped:
        if c['label_mapping']['status'] == 'excluded':
            excluded_cases.append({'id':c['id'], 'reason':c['label_mapping']['exclusion_reason']})
            dispositions.extend({'case_id':c['id'], 'claim':g, 'reason':c['label_mapping']['exclusion_reason']} for g in c['claims'])
    retained_counts, excluded_counts = Counter(), Counter()
    for c in result:
        for g in c['gold_claims']:
            retained_counts[(c['split'],c['source'],c['subset'],g['verdict'])] += 1
    for r in dispositions:
        c = metadata[r['case_id']]
        excluded_counts[(c['split'],c['source'],c['subset'],r['claim']['verdict'])] += 1
    # Original removed parents are retired representations, not additional exclusions:
    # the 19 replacement children have their own 15 retained / 4 excluded dispositions.
    joint = [{'split':s,'source':t,'subset':sub,'label':lab,
              'retained':retained_counts[(s,t,sub,lab)], 'excluded':excluded_counts[(s,t,sub,lab)]}
             for s,t,sub,lab in sorted(retained_counts.keys() | excluded_counts.keys())]
    calls = [r for d in ('pilot5-dev-v2.3','full-v2.3')
             for r in read_jsonl(S.ANNOTATION_DIR / d / 'evidence_calls.jsonl')]
    calls += read_jsonl(root / 'evidence_reruns.jsonl') + journals['supplement'] + journals['recovered']
    doubts = [r for r in calls if r['doubt']]
    unannotated = {c['id'] for c in result if not c['source_labels']['labels']}
    unannotated_doubts = [r for r in doubts if r['case_id'] in unannotated]
    split_subset = [{'split':s,'subset':sub, **statistics([c for c in result
                      if (s=='all' or c['split']==s) and (sub=='all' or c['subset']==sub)])}
                    for s in ('dev','test','all') for sub in ('all','natural','conflict_supplement')]
    by_task = {task:evidence_stats([c for c in result if c['source']==task]) for task in sorted({c['source'] for c in result})}
    offline_report = json.loads((root / 'offline_report.json').read_text())
    rerun_report = json.loads((root / 'rerun_report.json').read_text())
    original_calls = read_jsonl(root / 'evidence_reruns.jsonl')
    offline_cases = read_jsonl(root / 'natural.offline.jsonl')
    additional = sum(g['evidence_status']=='none' and any(r['case_id']==c['id'] and r['claim_id']==g['claim_id'] and r['evidence_status']=='exact' for r in original_calls)
                     for c in offline_cases for g in c['gold_claims'])
    if (offline_report['recovered_claims'] != sum(r['original_status']=='none' and r['evidence_status']=='exact' for r in read_jsonl(root/'offline_evidence.jsonl'))
        or rerun_report['new_prompt_additional_claims_after_offline'] != additional):
        raise ValueError('evidence summary differs from journal')
    test_c = sum(g['verdict']=='CONTRADICTED' for c in result if c['split']=='test' for g in c['gold_claims'])
    audit = {'design_version':'2.4', 'historical_freeze_commit':'c78d411', 'hard_test_verifier_run':False,
             'label_source':'ragtruth_human', 'secondary_human_review':False,
             'selected_cases':len(selected), 'retained_cases':len(result),
             'retained_claims':sum(len(c['gold_claims']) for c in result), 'excluded_claims':len(dispositions),
             'excluded_cases':excluded_cases, 'by_split_task_subset_label':joint, 'splits_subsets':split_subset,
             'excluded_claim_details':[{'case_id':r['case_id'], 'claim_id':r['claim']['claim_id'],
                                        'label':r['claim']['verdict'], 'reason':r['reason']} for r in dispositions],
             'evidence':{'overall':evidence_stats(result), 'by_task':by_task, 'offline_repair':offline_report,
                         'original_none_new_prompt':rerun_report,
                         'initial_supplement_and_recovery':{name:{'calls':len(rows),
                            'exact':sum(r['evidence_status']=='exact' for r in rows),
                            'protocol_errors':sum(bool(r.get('protocol_error')) for r in rows)} for name,rows in journals.items()},
                         'index_corrected_quotes_offline':offline_report['index_corrected_quotes'],
                         'index_corrected_quotes_new_calls':sum(bool(e.get('index_corrected')) for r in
                             original_calls+journals['supplement']+journals['recovered'] for e in r['evidence'])},
             'partial_recovery':json.loads((root/'partial_report.json').read_text()),
             'recovered_representations':{'new_unique_gold':sum(len(c['gold_claims']) for c in recovered)-len(duplicate_recoveries),
                 'duplicates_not_scored_twice':[{'case_id':r['case_id'], 'claim_id':r['claim']['claim_id'],
                     'represented_by':r['represented_by'],'reason':r['reason']} for r in duplicate_recoveries]},
             'model_doubts':{'records':len(doubts), 'unique_claims':len({(r['case_id'],r['claim_id']) for r in doubts}),
                             'protocol_diagnostics':sum(bool(r.get('protocol_error')) for r in doubts),
                             'semantic_doubts_or_not_found':sum(not r.get('protocol_error') for r in doubts)},
             'upstream_unannotated_answers':{'display_name':'上游无标注回答', 'cases':len(unannotated),
                 'cases_with_model_doubts':len({r['case_id'] for r in unannotated_doubts}),
                 'model_doubts_records':len(unannotated_doubts),
                 'case_ids_with_doubts':sorted({r['case_id'] for r in unannotated_doubts})},
             'targets':{'test_contradicted':{'observed':test_c,'minimum':15,'met':test_c>=15},
                        'data2txt_evidence':{'observed':by_task['ragtruth_data2txt']['coverage'],'minimum':.7,
                                            'met':by_task['ragtruth_data2txt']['coverage']>=.7}},
             'sampling_exception':'User approved removing GPT minimum only for conflict_supplement; other rules unchanged.',
             'limitations':['Upstream annotations may omit facts or contain errors; no second human review.',
                            'Exact quotation proves textual presence, not semantic sufficiency.',
                            'The targeted supplement changes label prevalence; natural results must accompany all results.',
                            'Retired parent claims are not double-counted as excluded replacement children.']}
    # Pin every annotation artifact used by replay, including failed/retired attempts for audit.
    inputs = [p for p in root.rglob('*') if p.is_file() and p.name not in ('audit.json','freeze.json','final_report.md')]
    inputs += [S.ANNOTATION_DIR/'candidates.jsonl', S.ROOT/'data/eval_hard.jsonl']
    inputs += [S.ANNOTATION_DIR/d/n for d in ('pilot5-dev-v2.3','full-v2.3')
               for n in ('excluded.jsonl','evidence_calls.jsonl')]
    audit['input_files'] = {S.rel(p.resolve()):digest(p) for p in sorted(set(inputs))}
    return result, audit


def render(audit: dict) -> str:
    lines = ['# v2.4 合并统计（数据诊断，无被测方案成绩）', '',
             '| split | subset | 案例 | 主张 | S | C | U | S/C 精确证据 |',
             '|---|---|---:|---:|---:|---:|---:|---:|']
    for r in audit['splits_subsets']:
        labs, ev = r['labels'], r['evidence']
        lines.append(f"| {r['split']} | {r['subset']} | {r['cases']} | {r['claims']} | {labs['SUPPORTED']} | {labs['CONTRADICTED']} | {labs['UNSUPPORTED']} | {ev['exact']}/{ev['eligible_sc']} |")
    lines += ['', '| 任务 | S/C 精确证据 | 覆盖率 |', '|---|---:|---:|']
    for task, ev in audit['evidence']['by_task'].items():
        lines.append(f"| {task} | {ev['exact']}/{ev['eligible_sc']} | {ev['coverage']:.1%} |")
    lines += ['', '| split / subset | context words min / median / mean / max | answer words min / median / mean / max |', '|---|---|---|']
    for r in audit['splits_subsets']:
        values = [' / '.join(str(round(r[k][n],1)) if r[k][n] is not None else '-' for n in ('min','median','mean','max')) for k in ('context_words','answer_words')]
        lines.append(f"| {r['split']} / {r['subset']} | {values[0]} | {values[1]} |")
    lines += ['', '## 审计摘要', '', f"- 剔除主张 {audit['excluded_claims']}；整例剔除 {len(audit['excluded_cases'])}。旧 10 条父主张退休，替代子主张保留 15、仍剔除 4，分别记账。",
              f"- 拆分产生的 15 条保留候选中，{audit['recovered_representations']['new_unique_gold']} 条成为新增 gold；{len(audit['recovered_representations']['duplicates_not_scored_twice'])} 条与已有相同标签、文本、重叠回答跨度的 gold 合并溯源，避免重复计分。",
              '- 证据兜底和新 prompt 统计、model_doubts、上游无标注回答及目标达成情况：',
              '```json', json.dumps({k:audit[k] for k in ('evidence','model_doubts','upstream_unannotated_answers','targets')},ensure_ascii=False,indent=2), '```',
              '', '本轮修改仅依据标签分布和证据流水线诊断；未运行任何 hard-test 被测方案。',
              '所有标签来自 RAGTruth 人工跨度映射；引文精确存在不保证语义充分，无二次人工确认。',
              '新增集 GPT 下限已按用户授权取消，其余固定配额、长度和去重规则不变。']
    return '\n'.join(lines)+'\n'


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root',type=Path,default=OUT)
    ap.add_argument('--out',type=Path,default=S.ROOT/'data/eval_hard.v2.4.jsonl')
    ap.add_argument('--check',action='store_true')
    args = ap.parse_args()
    audit_path = args.root/'audit.json'
    if not args.check and (args.out.exists() or audit_path.exists()):
        raise SystemExit('STOP: dataset/audit exists; use --check to replay without overwrite')
    cases, audit = assemble(args.root)
    if args.check:
        audit['dataset_sha256'] = digest(args.out)
        if cases != read_jsonl(args.out) or audit != json.loads(audit_path.read_text()):
            raise ValueError('dataset/audit differs from replay')
        print('v2.4 dataset, labels, evidence and audit replay verified'); return
    args.out.parent.mkdir(parents=True,exist_ok=True)
    write_new(args.out,cases)
    audit['dataset_sha256'] = digest(args.out)
    with audit_path.open('x') as stream:
        json.dump(audit,stream,ensure_ascii=False,indent=2); stream.write('\n')
    report = render(audit)
    with (args.root/'final_report.md').open('x') as stream:
        stream.write(report)
    print(report)


if __name__ == '__main__':
    main()
