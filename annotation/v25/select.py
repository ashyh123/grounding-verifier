"""Select the pre-registered subtle-conflict supplement offline; never call annotation models.

Failure modes: infeasible quotas, GPT floor below half, changed rules, used source/near-duplicate
groups, input ordering, source text alteration, existing output. No quota or requirement relaxation.
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

OUT = S.ANNOTATION_DIR / 'v2.5'
RULES = OUT / 'sampling_rules.json'
EXISTING = S.ROOT / 'data/eval_hard.v2.4.jsonl'
EXISTING_SYNTHETIC = S.ROOT / 'data/eval.jsonl'


def segments(source: dict, task: str) -> tuple[list[str], str, list[str]]:
    """Exact passages and the original serialization for one upstream source."""
    if task == 'QA':
        original_text = source['source_info']['passages']
        return S.split_qa_passages(original_text), original_text, S.qa_prefixes(original_text)
    if task == 'Data2txt':
        return (S.split_data2txt(source['source_info']),
                json.dumps(source['source_info'], ensure_ascii=False, indent=1), [])
    return S.split_paragraphs(source['source_info']), source['source_info'], []


def build_pool(rules: dict) -> tuple[list[dict], dict]:
    """Every unused upstream response with a Subtle Conflict and the declared length rules."""
    responses = S.load_ragtruth_responses()
    sources = S.load_ragtruth_sources()
    existing = read_jsonl(EXISTING)
    existing_response_ids = {row['provenance']['response_id'] for row in existing}
    existing_source_ids = {row['provenance']['source_id'] for row in existing}
    legacy_sources = {sources[r['source_id']]['source_id'] for r in responses
                      if r['id'] in S.LEGACY_RESPONSE_IDS and r['source_id'] in sources}
    minimum = rules['min_answer_words']
    pool, excluded = [], Counter()
    for response in responses:
        if response['split'] not in rules['upstream_splits']:
            continue
        if response['quality'] != rules['quality']:
            continue
        if response['model'] not in rules['allowed_generators']:
            continue
        source = sources.get(response['source_id'])
        if source is None:
            excluded['missing_source'] += 1
            continue
        if response['id'] in S.LEGACY_RESPONSE_IDS or source['source_id'] in legacy_sources:
            excluded['legacy_project'] += 1
            continue
        if response['id'] in existing_response_ids or source['source_id'] in existing_source_ids:
            excluded['already_in_v24'] += 1
            continue
        task, answer = source['task_type'], response['response']
        if len(answer) > rules['max_answer_chars'] or S.words(answer) < minimum[task]:
            excluded['answer_length'] += 1
            continue
        passages, original_text, prefixes = segments(source, task)
        if len(passages) > rules['max_passages'] or any(
                len(p) > rules['max_passage_chars'] for p in passages):
            excluded['context_limits'] += 1
            continue
        if task == 'QA' and (len(passages) != rules['qa_passages']
                             or not all(p.strip() for p in passages)):
            excluded['qa_passages'] += 1
            continue
        if task == 'Summary' and S.words(source['source_info']) < rules['min_summary_context_words']:
            excluded['summary_context'] += 1
            continue
        if not any('Subtle Conflict' in label['label_type'] for label in response['labels']):
            excluded['no_subtle_conflict'] += 1
            continue
        check = S.check_segmentation(f"ragtruth-{response['id']}", passages, original_text, prefixes)
        if not check.ok:
            raise ValueError(check.detail)
        pool.append({
            'response_id': response['id'], 'source_id': source['source_id'], 'task': task,
            'model': response['model'], 'upstream_split': response['split'],
            'is_gpt': response['model'] in S.GPT_MODELS, 'source': source,
            'record': response, 'stratum': 'subtle',
            'subtle_spans': sum('Subtle Conflict' in label['label_type']
                                for label in response['labels']),
            'context_words': S.words(' '.join(passages)),
            'group': f"ragtruth-{source['source_id']}",
        })
    documents = {f"pool-{item['response_id']}": original.source_context(item['source'])
                 for item in pool}
    documents.update({f"existing-{row['id']}": original.source_context(
                          sources[row['provenance']['source_id']]) for row in existing})
    documents.update({f"synthetic-{row['id']}": '\n\n'.join(row['context_passages'])
                      for row in read_jsonl(EXISTING_SYNTHETIC)})
    groups = original.duplicate_groups(documents)
    blocked = {groups[f"existing-{row['id']}"] for row in existing}
    blocked |= {groups[f"synthetic-{row['id']}"] for row in read_jsonl(EXISTING_SYNTHETIC)}
    eligible = []
    for item in pool:
        group = groups[f"pool-{item['response_id']}"]
        if group in blocked:
            excluded['existing_near_duplicate_group'] += 1
            continue
        eligible.append({**item, 'group': group})
    summary = {
        'eligible': len(eligible),
        'excluded': dict(sorted(excluded.items())),
        'by_upstream_split_task_model': {
            f'{split}/{task}/{model}': count
            for (split, task, model), count in sorted(Counter(
                (item['upstream_split'], item['task'], item['model']) for item in eligible).items())},
        'unique_groups': len({item['group'] for item in eligible}),
        'unique_source_ids': len({item['source_id'] for item in eligible}),
    }
    return eligible, summary


def _solver(choices: list[tuple[dict, str]], constraints: list[tuple[list[int], int, int]],
            cost: np.ndarray):
    matrix = lil_matrix((len(constraints), len(choices)))
    for row, (indices, _lo, _hi) in enumerate(constraints):
        matrix[row, indices] = 1
    return milp(c=np.asarray(cost, dtype=float), integrality=np.ones(len(choices)),
                bounds=Bounds(0, 1),
                constraints=LinearConstraint(matrix.tocsr(),
                                            [row[1] for row in constraints],
                                            [row[2] for row in constraints]),
                options={'mip_rel_gap': 0.0})


def choose(pool: list[dict], rules: dict) -> tuple[list[dict], dict]:
    """Exact task/split quotas, one per source/component, GPT floor, then seeded rank."""
    choices = [(item, split) for item in sorted(pool, key=lambda item: item['response_id'])
               for split in ('dev', 'test')]
    if not choices:
        raise ValueError('no eligible subtle-conflict candidates; constraints not relaxed')
    constraints = []
    for task, quotas in rules['quotas'].items():
        for split, count in quotas.items():
            indices = [i for i, (item, assigned) in enumerate(choices)
                       if item['task'] == task and assigned == split]
            constraints.append((indices, count, count))
    by_group, by_source = defaultdict(list), defaultdict(list)
    for index, (item, _split) in enumerate(choices):
        by_group[item['group']].append(index)
        by_source[item['source_id']].append(index)
    constraints.extend((indices, 0, 1) for indices in by_group.values())
    constraints.extend((indices, 0, 1) for indices in by_source.values())
    rank = np.array([random.Random(f"{rules['seed']}:{item['response_id']}:{split}").random()
                     for item, split in choices])

    # Diagnostic: how many GPT cases are feasible before applying the floor.
    gpt = np.array([0 if item['is_gpt'] else 1 for item, _split in choices])
    solved = _solver(choices, constraints, gpt)
    if not solved.success:
        raise SystemExit('STOP: declared subtle quotas infeasible; no relaxation: ' + solved.message)
    max_gpt = int(round(sum(item['is_gpt'] for (item, _split), chosen
                            in zip(choices, solved.x) if chosen > .5)))
    minimum = rules['generator_preference']['minimum_cases']
    if max_gpt < minimum:
        raise SystemExit(f'STOP: GPT target infeasible: maximum {max_gpt}/{rules["total_cases"]} '
                         f'GPT cases, minimum {minimum}; report to the user, do not relax')
    gpt_indices = [i for i, (item, _split) in enumerate(choices) if item['is_gpt']]
    constraints.append((gpt_indices, minimum, len(gpt_indices)))
    solved = _solver(choices, constraints, rank)
    if not solved.success:
        raise SystemExit('STOP: seeded allocation failed: ' + solved.message)
    selected = [(item, split) for (item, split), chosen in zip(choices, solved.x) if chosen > .5]
    counts = Counter((item['task'], split) for item, split in selected)
    expected = {(task, split): count for task, quotas in rules['quotas'].items()
                for split, count in quotas.items()}
    if dict(counts) != expected:
        raise SystemExit(f'STOP: selected quotas differ: {dict(counts)} != {expected}')
    if len({item['source_id'] for item, _split in selected}) != len(selected):
        raise SystemExit('STOP: duplicate source_id selected')
    if len({item['group'] for item, _split in selected}) != len(selected):
        raise SystemExit('STOP: duplicate near-duplicate group selected')
    gpt_cases = sum(item['is_gpt'] for item, _split in selected)
    if gpt_cases < minimum:
        raise SystemExit('STOP: selected GPT count below target')
    return selected, {'max_feasible_gpt_cases': max_gpt, 'gpt_cases': gpt_cases}


def select(pool: list[dict], rules: dict) -> tuple[list[dict], dict]:
    selected, diagnostics = choose(pool, rules)
    reversed_selected, _ = choose(list(reversed(pool)), rules)
    if sorted((item['response_id'], split) for item, split in selected) != sorted(
            (item['response_id'], split) for item, split in reversed_selected):
        raise SystemExit('STOP: input ordering changed selection')
    rows = []
    for item, split in sorted(selected, key=lambda pair: pair[0]['response_id']):
        row = original._ragtruth_candidate(item, split, item['task'], 'subtle').to_json()
        row['subset'] = rules['subset']
        row['selection'].update(
            seed=rules['seed'], rules='data/annotation/v2.5/sampling_rules.json',
            upstream_split=item['upstream_split'],
            upstream_subtle_conflict_spans=item['subtle_spans'],
            generator_class='gpt' if item['is_gpt'] else 'other',
            gpt_minimum_cases=rules['generator_preference']['minimum_cases'])
        rows.append(row)
    return rows, diagnostics


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out-dir', type=Path, default=OUT)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    paths = [args.out_dir / name for name in
             ('subtle_candidates.jsonl', 'selection.json', 'selection-stats.md')]
    if any(path.exists() for path in paths):
        raise SystemExit('STOP: outputs exist; archive before rerunning')
    rules = json.loads(RULES.read_text(encoding='utf-8'))
    existing_sha = hashlib.sha256(EXISTING.read_bytes()).hexdigest()
    pool, pool_summary = build_pool(rules)
    rows, diagnostics = select(pool, rules)
    summary = Counter((row['provenance']['task_type'], row['split'], row['generator_model'],
                       row['provenance']['upstream_split'],
                       row['selection']['upstream_subtle_conflict_spans']) for row in rows)
    registry = {
        'version': '2.5', 'rules_sha256': hashlib.sha256(RULES.read_bytes()).hexdigest(),
        'existing_sha256': existing_sha, 'seed': rules['seed'],
        'counts': dict(sorted(Counter(row['split'] for row in rows).items())),
        'gpt_counts': dict(sorted(Counter(row['split'] for row in rows
                                          if row['selection']['generator_class'] == 'gpt').items())),
        'gpt_minimum_cases': rules['generator_preference']['minimum_cases'],
        **diagnostics, 'pool': pool_summary,
        'rows': [{'task': task, 'split': split, 'generator_model': model,
                  'upstream_split': upstream, 'upstream_subtle_conflict_spans': spans,
                  'cases': count}
                 for (task, split, model, upstream, spans), count in sorted(summary.items())],
        'selected_ids': [row['id'] for row in rows],
    }
    write_new(paths[0], rows)
    paths[1].write_text(json.dumps(registry, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    text = ['# v2.5 Subtle 矛盾补充抽样统计\n\n',
            f'种子 {rules["seed"]}；未调用起草或证据模型。\n\n',
            '| 任务 | split | 生成模型 | 上游 split | Subtle Conflict 片段数/例 | 案例数 |\n',
            '|---|---|---|---|---:|---:|\n']
    text += [f'| {task} | {split} | {model} | {upstream} | {spans} | {count} |\n'
             for (task, split, model, upstream, spans), count in sorted(summary.items())]
    paths[2].write_text(''.join(text), encoding='utf-8')
    print(json.dumps(registry, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
