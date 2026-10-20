"""v2.6 sampling: natural-distribution RAGTruth responses for response-level evaluation.

    uv run python -m annotation.v26.select

Offline and model-free. Sampling never reads upstream labels: the pool is built from sources, answers
and lengths only, and labels are attached to the selected cases afterwards. Rules are frozen in
data/annotation/v2.6/sampling_rules.json (committed before this script is run).
Failure modes (stop, no relaxation): infeasible quotas, changed rules hash, existing outputs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from annotation import select_cases as original
from annotation import sources as S
from annotation.map_labels import read_jsonl, write_new
from annotation.v25.select import segments
from annotation.v26.sentences import RULES_VERSION, gold_sentences

OUT = S.ANNOTATION_DIR / 'v2.6'
RULES = OUT / 'sampling_rules.json'
EXISTING = S.ROOT / 'data/eval_hard.v2.5.jsonl'
EXISTING_V24 = S.ROOT / 'data/eval_hard.v2.4.jsonl'
EXISTING_SYNTHETIC = S.ROOT / 'data/eval.jsonl'
DATASET = S.ROOT / 'data/eval_ragtruth_resp.v2.6.jsonl'
TASKS = ('Summary', 'QA', 'Data2txt')


def source_rank(seed: int, source_id: str) -> float:
    return random.Random(f'{seed}:source:{source_id}').random()


def response_rank(seed: int, response_id: str) -> float:
    return random.Random(f'{seed}:response:{response_id}').random()


def build_pool(rules: dict, responses: list[dict], sources: dict[str, dict],
               existing: list[dict], synthetic: list[dict]) -> tuple[list[dict], dict]:
    """Eligible candidate responses. Does not touch `labels`."""
    caps = rules['technical_caps']
    limits = caps['service_limits']
    existing_response_ids = {row['provenance']['response_id'] for row in existing}
    existing_source_ids = {row['provenance']['source_id'] for row in existing}
    legacy_sources = {sources[r['source_id']]['source_id'] for r in responses
                      if r['id'] in S.LEGACY_RESPONSE_IDS and r['source_id'] in sources}
    excluded: Counter = Counter()
    stage = []
    for response in responses:
        if response['split'] not in rules['upstream_splits'] or response['quality'] != rules['quality']:
            continue
        source = sources.get(response['source_id'])
        if source is None:
            excluded['missing_source'] += 1
            continue
        if response['id'] in S.LEGACY_RESPONSE_IDS or source['source_id'] in legacy_sources:
            excluded['legacy_project'] += 1
            continue
        if response['id'] in existing_response_ids or source['source_id'] in existing_source_ids:
            excluded['already_in_v2x'] += 1
            continue
        stage.append((response, source))
    # near-duplicate components over candidate sources, all v2.x cases, old synthetic data, legacy sources
    documents = {f"pool-{source['source_id']}": original.source_context(source) for _r, source in stage}
    blocked_keys = []
    for row in existing:
        key = f"existing-{row['id']}"
        documents[key] = original.source_context(sources[row['provenance']['source_id']])
        blocked_keys.append(key)
    for row in synthetic:
        key = f"synthetic-{row['id']}"
        documents[key] = '\n\n'.join(row['context_passages'])
        blocked_keys.append(key)
    for source_id in sorted(legacy_sources):
        key = f'legacy-{source_id}'
        documents[key] = original.source_context(sources[source_id])
        blocked_keys.append(key)
    groups = original.duplicate_groups(documents)
    blocked = {groups[key] for key in blocked_keys}
    passages_cache: dict[str, list[str]] = {}
    pool = []
    for response, source in stage:
        sid = source['source_id']
        group = groups[f'pool-{sid}']
        if group in blocked:
            excluded['near_duplicate_of_used'] += 1
            continue
        task, answer = source['task_type'], response['response']
        if sid not in passages_cache:
            passages_cache[sid] = segments(source, task)[0]
        passages = passages_cache[sid]
        context_words, answer_words = S.words(' '.join(passages)), S.words(answer)
        if context_words > caps['max_context_words']:
            excluded['context_too_long'] += 1
            continue
        if answer_words > caps['max_answer_words']:
            excluded['answer_too_long'] += 1
            continue
        if (len(passages) > limits['max_passages'] or len(answer) > limits['max_answer_chars']
                or any(len(p) > limits['max_passage_chars'] for p in passages)):
            excluded['service_limits'] += 1
            continue
        pool.append({'response_id': response['id'], 'source_id': sid, 'task': task,
                     'model': response['model'], 'group': group,
                     'context_words': context_words, 'answer_words': answer_words})
    summary = {
        'eligible_responses': len(pool),
        'eligible_sources': len({p['source_id'] for p in pool}),
        'eligible_groups': len({p['group'] for p in pool}),
        'excluded_responses': dict(sorted(excluded.items())),
        'eligible_by_task': dict(sorted(Counter(p['task'] for p in pool).items())),
        'eligible_by_task_model': {f'{t}/{m}': n for (t, m), n in sorted(
            Counter((p['task'], p['model']) for p in pool).items())},
    }
    return pool, summary


def draw(pool: list[dict], rules: dict) -> list[tuple[dict, str]]:
    """Seeded source draw then seeded response draw, per task; group-consistent split assignment."""
    seed = rules['seed']
    by_task: dict[str, dict[str, list[dict]]] = {t: defaultdict(list) for t in TASKS}
    for item in pool:
        by_task[item['task']][item['source_id']].append(item)
    group_split: dict[str, str] = {}
    chosen: list[tuple[dict, str]] = []
    for task in TASKS:
        quota = dict(rules['quotas'][task])
        filled = Counter()
        for sid in sorted(by_task[task], key=lambda s: (source_rank(seed, s), s)):
            if all(filled[sp] >= quota[sp] for sp in quota):
                break
            item = min(by_task[task][sid], key=lambda i: (response_rank(seed, i['response_id']), i['response_id']))
            fixed = group_split.get(item['group'])
            if fixed is not None:
                if filled[fixed] >= quota[fixed]:
                    continue
                split = fixed
            else:
                split = next((sp for sp in ('dev', 'test') if filled[sp] < quota[sp]), None)
                if split is None:
                    continue
                group_split[item['group']] = split
            filled[split] += 1
            chosen.append((item, split))
        if any(filled[sp] != quota[sp] for sp in quota):
            raise SystemExit(f'STOP: quotas infeasible for {task}: {dict(filled)} vs {quota}; no relaxation')
    return chosen


def build_row(item: dict, split: str, response: dict, source: dict, rules: dict) -> dict:
    cand = original._ragtruth_candidate(
        {'record': response, 'source': source, 'context_words': item['context_words'],
         'group': item['group'], 'is_gpt': False}, split, item['task'], 'natural').to_json()
    labels = response['labels']
    provenance = dict(cand['provenance'])
    provenance.update(
        annotation_origin='ragtruth_human', source_group=item['group'],
        context_words=cand['context_words'], answer_words=item['answer_words'],
        selection={'seed': rules['seed'], 'rules': 'data/annotation/v2.6/sampling_rules.json',
                   'sentence_rules': RULES_VERSION},
        passage_transforms=['remove passage N: structure markers', 'trim passage edge whitespace'])
    return {'id': cand['id'], 'split': split, 'task': item['task'],
            'generator_model': response['model'],
            'context_passages': cand['context_passages'], 'passage_map': cand['passage_map'],
            'generated_answer': response['response'],
            'source_labels': cand['source_labels'],
            'gold_response': bool(labels),
            'gold_sentences': gold_sentences(response['response'], labels),
            'provenance': provenance}


def _dist(values: list[int]) -> str:
    if not values:
        return '-'
    return f'{min(values)} / {statistics.median(values):.0f} / {max(values)}'


def stats_markdown(rows: list[dict], registry: dict) -> str:
    text = ['# v2.6 抽样统计\n\n', f'种子 {registry["seed"]}；抽样时未读取标签，未调用任何模型。\n\n',
            '## 任务 x split x 生成模型 x 是否有幻觉\n\n',
            '| 任务 | split | 生成模型 | 有幻觉 | 无幻觉 | 合计 |\n|---|---|---|---:|---:|---:|\n']
    cells = Counter((r['task'], r['split'], r['generator_model'], r['gold_response']) for r in rows)
    keys = sorted({k[:3] for k in cells})
    for task, split, model in keys:
        bad, good = cells[(task, split, model, True)], cells[(task, split, model, False)]
        text.append(f'| {task} | {split} | {model} | {bad} | {good} | {bad + good} |\n')
    text += ['\n## 任务 x split 合计\n\n| 任务 | split | 案例数 | 有幻觉 |\n|---|---|---:|---:|\n']
    for task in TASKS:
        for split in ('dev', 'test'):
            part = [r for r in rows if r['task'] == task and r['split'] == split]
            text.append(f'| {task} | {split} | {len(part)} | {sum(r["gold_response"] for r in part)} |\n')
    text += ['\n## 长度分布（最小 / 中位数 / 最大）\n\n',
             '| 任务 | split | 上下文词数 | 回答词数 | 句子数 |\n|---|---|---|---|---|\n']
    for task in TASKS:
        for split in ('dev', 'test'):
            part = [r for r in rows if r['task'] == task and r['split'] == split]
            text.append(f'| {task} | {split} | '
                        f'{_dist([r["provenance"]["context_words"] for r in part])} | '
                        f'{_dist([r["provenance"]["answer_words"] for r in part])} | '
                        f'{_dist([len(r["gold_sentences"]) for r in part])} |\n')
    pool = registry['pool']
    text += ['\n## 候选池与排除\n\n',
             f'- 合格回答 {pool["eligible_responses"]} 条，来自 {pool["eligible_sources"]} 个 source、'
             f'{pool["eligible_groups"]} 个近重复组。\n',
             f'- 合格回答按任务：{pool["eligible_by_task"]}\n',
             '- 排除（回答条数，按规则顺序，先命中者计数）：\n']
    text += [f'  - {name}: {count}\n' for name, count in pool['excluded_responses'].items()]
    caps = registry['technical_caps']
    text.append(f'- 技术上限：上下文 <= {caps["max_context_words"]} 词，回答 <= {caps["max_answer_words"]} 词'
                f'（取自 v2.5 数据实际最大值）；因超长被排除：上下文 '
                f'{pool["excluded_responses"].get("context_too_long", 0)} 条，回答 '
                f'{pool["excluded_responses"].get("answer_too_long", 0)} 条。\n')
    return ''.join(text)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out-dir', type=Path, default=OUT)
    ap.add_argument('--dataset', type=Path, default=DATASET)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    paths = [args.dataset, args.out_dir / 'selection.json', args.out_dir / 'selection-stats.md']
    if any(p.exists() for p in paths):
        raise SystemExit('STOP: outputs exist; archive before rerunning')
    rules = json.loads(RULES.read_text(encoding='utf-8'))
    responses, sources = S.load_ragtruth_responses(), S.load_ragtruth_sources()
    existing, synthetic = read_jsonl(EXISTING), read_jsonl(EXISTING_SYNTHETIC)
    if not {r['id'] for r in read_jsonl(EXISTING_V24)} <= {r['id'] for r in existing}:
        raise SystemExit('STOP: v2.5 data does not contain every v2.4 case')
    # Sampling sees no labels: strip them from the records it can reach.
    unlabeled = [{k: v for k, v in r.items() if k != 'labels'} for r in responses]
    pool, pool_summary = build_pool(rules, unlabeled, sources, existing, synthetic)
    chosen = draw(pool, rules)
    by_id = {r['id']: r for r in responses}
    rows = [build_row(item, split, by_id[item['response_id']], sources[item['source_id']], rules)
            for item, split in sorted(chosen, key=lambda p: p[0]['response_id'])]
    manifest = json.loads((S.ROOT / 'data/sources/v2/manifest.json').read_text(encoding='utf-8'))
    registry = {
        'version': '2.6', 'seed': rules['seed'],
        'rules_sha256': hashlib.sha256(RULES.read_bytes()).hexdigest(),
        'existing_sha256': hashlib.sha256(EXISTING.read_bytes()).hexdigest(),
        'upstream_response_sha256': manifest['files'].get('response.jsonl', {}).get('sha256'),
        'upstream_source_info_sha256': manifest['files'].get('source_info.jsonl', {}).get('sha256'),
        'sentence_rules': RULES_VERSION,
        'technical_caps': rules['technical_caps'],
        'counts': {f'{t}/{s}': sum(r['task'] == t and r['split'] == s for r in rows)
                   for t in TASKS for s in ('dev', 'test')},
        'pool': pool_summary,
        'selected': [{'id': r['id'], 'split': r['split'], 'task': r['task'],
                      'source_id': r['provenance']['source_id'],
                      'group': r['provenance']['source_group'],
                      'generator_model': r['generator_model']} for r in rows],
    }
    write_new(paths[0], rows)
    paths[1].write_text(json.dumps(registry, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    paths[2].write_text(stats_markdown(rows, registry), encoding='utf-8')
    print(paths[2].read_text(encoding='utf-8'))


if __name__ == '__main__':
    main()
