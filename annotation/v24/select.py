"""Select the pre-registered conflict supplement offline; never invoke annotation models.

Failure modes: infeasible quotas, changed rules, duplicate sources/near groups, natural overlap,
input ordering, source text alteration, existing output. No quota or length relaxation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix

from annotation import sources as S
from annotation import select_cases as original
from annotation.map_labels import read_jsonl, write_new

OUT = S.ANNOTATION_DIR / 'v2.4'
RULES = OUT / 'sampling_rules.json'


def select(pool: list[dict], natural: list[dict], rules: dict) -> list[dict]:
    documents = {f"source-{c['source_id']}": original.source_context(c['source']) for c in pool}
    documents.update({f"natural-{c['id']}": '\n\n'.join(c['context_passages']) for c in natural})
    groups = original.duplicate_groups(documents)
    blocked = {groups[f"natural-{c['id']}"] for c in natural}
    natural_sources = {c['provenance']['source_id'] for c in natural}
    eligible = []
    for item in pool:
        if (item['source_id'] in natural_sources or groups[f"source-{item['source_id']}"] in blocked
                or not any('Conflict' in lab['label_type'] for lab in item['record']['labels'])):
            continue
        eligible.append({**item, 'group': groups[f"source-{item['source_id']}"]})
    choices = [(c, split) for c in sorted(eligible, key=lambda c: c['response_id']) for split in ('dev','test')]
    if not choices:
        raise ValueError('no eligible conflict cases; constraints not relaxed')
    constraints = []
    for task, quotas in rules['quotas'].items():
        for split, n in quotas.items():
            constraints.append(([i for i,(c,s) in enumerate(choices) if c['task']==task and s==split],n,n))
    for split,n in rules['gpt_minimum_per_split'].items():
        maximum = sum(q[split] for q in rules['quotas'].values())
        constraints.append(([i for i,(c,s) in enumerate(choices) if c['is_gpt'] and s==split],n,maximum))
    components = defaultdict(list)
    for i,(c,s) in enumerate(choices):
        components[c['group']].append(i)
    constraints.extend((indices,0,1) for indices in components.values())
    matrix = lil_matrix((len(constraints),len(choices)))
    for row,(indices,lo,hi) in enumerate(constraints):
        matrix[row,indices]=1
    rank = lambda key: random.Random(f"{rules['seed']}:{key}").random()
    solved = milp(c=np.array([rank(f"{c['response_id']}:{s}") for c,s in choices]),
                  integrality=np.ones(len(choices)),bounds=Bounds(0,1),
                  constraints=LinearConstraint(matrix.tocsr(),[r[1] for r in constraints],[r[2] for r in constraints]),
                  options={'mip_rel_gap':0.0})
    if not solved.success:
        raise ValueError('declared supplement constraints infeasible; no relaxation: '+solved.message)
    rows=[]
    for (c,split),chosen in zip(choices,solved.x):
        if chosen<=.5:
            continue
        row=original._ragtruth_candidate(c,split,c['task'],c['stratum']).to_json()
        row['subset']='conflict_supplement'
        row['selection'].update(seed=rules['seed'], rules='data/annotation/v2.4/sampling_rules.json',
                                upstream_conflict_spans=sum('Conflict' in l['label_type'] for l in c['record']['labels']))
        rows.append(row)
    return rows


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out-dir',type=Path,default=OUT)
    args=ap.parse_args()
    args.out_dir.mkdir(parents=True,exist_ok=True)
    paths=[args.out_dir/name for name in ['supplement_candidates.jsonl','natural_cases.jsonl','selection.json','selection-stats.md']]
    if any(p.exists() for p in paths):
        raise SystemExit('STOP: outputs exist; archive before rerunning')
    rules=json.loads(RULES.read_text())
    natural=read_jsonl(S.ROOT/'data/eval_hard.jsonl')
    pool=original.ragtruth_pool()
    rows=select(pool,natural,rules)
    if rows!=select(list(reversed(pool)),natural,rules):
        raise SystemExit('STOP: input ordering changed selection')
    summary=Counter((r['provenance']['task_type'],r['split'],r['generator_model'],
                     r['selection']['upstream_conflict_spans']) for r in rows)
    registry={'version':'2.4','rules_sha256':hashlib.sha256(RULES.read_bytes()).hexdigest(),
              'natural_sha256':hashlib.sha256((S.ROOT/'data/eval_hard.jsonl').read_bytes()).hexdigest(),
              'seed':rules['seed'],'counts':dict(Counter(r['split'] for r in rows)),
              'gpt_counts':dict(Counter(r['split'] for r in rows if r['selection']['generator_class']=='gpt')),
              'rows':[{'task':t,'split':s,'generator_model':m,'upstream_conflict_spans':n,'cases':count}
                      for (t,s,m,n),count in sorted(summary.items())],
              'selected_ids':[r['id'] for r in rows]}
    write_new(paths[0],rows)
    write_new(paths[1],[{**c,'subset':'natural'} for c in natural])
    paths[2].write_text(json.dumps(registry,ensure_ascii=False,indent=2)+'\n')
    text=['# v2.4 矛盾样本抽样统计\n\n','种子 20261020；每例含上游 Conflict；未调用起草或证据模型。\n\n',
          '| 任务 | split | 生成模型 | 上游 Conflict 片段数/例 | 案例数 |\n|---|---|---|---:|---:|\n']
    text += [f'| {t} | {s} | {m} | {n} | {count} |\n' for (t,s,m,n),count in sorted(summary.items())]
    paths[3].write_text(''.join(text))
    print(json.dumps(registry,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
