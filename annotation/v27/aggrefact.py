"""Build the v2.7 LLM-AggreFact oracle track (track A).

    uv run --with pyarrow python -m annotation.v27.aggrefact --split test --target 100 --stats
    uv run --with pyarrow python -m annotation.v27.aggrefact --split test --target 100 --write

One document is one case; its claims are given to the verifier (oracle mode, no decomposition).
The source parquet is gated and local-only; the generated JSONL is also git-ignored. The committed
manifest is data/annotation/v2.7/aggrefact-selection.json.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import random
import re
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / 'data' / 'sources' / 'v2.7' / 'raw'
RULES = ROOT / 'data' / 'annotation' / 'v2.7' / 'rules.json'
SEED = 20261024
MAX_DOC_WORDS = 4000
MAX_PASSAGE_CHARS = 20000
TARGET_WORDS = 150
EXCLUDED_SUBSET = 'RAGTruth'
SUBSETS = ('AggreFact-CNN', 'AggreFact-XSum', 'ClaimVerify', 'ExpertQA', 'FactCheck-GPT',
           'Lfqa', 'Reveal', 'TofuEval-MediaS', 'TofuEval-MeetB', 'Wice')


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _sentences(text: str) -> list[tuple[int, int]]:
    spans = []
    for match in re.finditer(r'[^.!?]+(?:[.!?]+|$)', text):
        start, end = _trim(text, match.start(), match.end())
        if start < end:
            spans.append((start, end))
    return spans


def _paragraphs(text: str) -> list[tuple[int, int]]:
    spans, start = [], 0
    for match in re.finditer(r'\n\s*\n', text):
        s, e = _trim(text, start, match.start())
        if s < e:
            spans.append((s, e))
        start = match.end()
    s, e = _trim(text, start, len(text))
    if s < e:
        spans.append((s, e))
    return spans


def _hard_split(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """Last resort for a single unit over the passage char limit."""
    out = []
    while start < end:
        stop = min(end, start + MAX_PASSAGE_CHARS)
        if stop < end:
            cut = text.rfind(' ', start, stop)
            if cut > start:
                stop = cut
        s, e = _trim(text, start, stop)
        if s < e:
            out.append((s, e))
        start = stop
    return out


def _units(text: str) -> list[tuple[int, int]]:
    """Paragraph units; overlong paragraphs are split into sentences or hard chunks."""
    out = []
    for start, end in _paragraphs(text) or [(0, len(text))]:
        segment = text[start:end]
        if len(segment) <= MAX_PASSAGE_CHARS and len(segment.split()) <= TARGET_WORDS:
            out.append((start, end))
            continue
        for s, e in _sentences(segment):
            s, e = start + s, start + e
            if len(text[s:e]) > MAX_PASSAGE_CHARS:
                out.extend(_hard_split(text, s, e))
            else:
                out.append((s, e))
    return out


def split_document(text: str, target_words: int = TARGET_WORDS,
                   max_chars: int = MAX_PASSAGE_CHARS) -> tuple[list[str], list[dict]]:
    """Pack paragraph/sentence units into verbatim passages of about `target_words` words."""
    passages: list[str] = []
    mapping: list[dict] = []
    current_start = current_end = None
    current_words = 0
    for start, end in _units(text):
        if not re.search(r'\w', text[start:end]):
            continue
        words = len(text[start:end].split())
        if current_start is not None:
            candidate = text[current_start:end]
            if len(candidate) > max_chars or current_words + words > target_words + 30:
                passages.append(text[current_start:current_end])
                mapping.append({'index': len(passages) - 1, 'start_char': current_start,
                                'end_char': current_end})
                current_start = current_end = None
                current_words = 0
        if current_start is None:
            current_start, current_end, current_words = start, end, words
        else:
            current_end = end
            current_words += words
        if current_words >= target_words:
            passages.append(text[current_start:current_end])
            mapping.append({'index': len(passages) - 1, 'start_char': current_start,
                            'end_char': current_end})
            current_start = current_end = None
            current_words = 0
    if current_start is not None:
        passages.append(text[current_start:current_end])
        mapping.append({'index': len(passages) - 1, 'start_char': current_start,
                        'end_char': current_end})
    for passage, entry in zip(passages, mapping):
        if text[entry['start_char']:entry['end_char']] != passage:
            raise AssertionError('passage is not a verbatim substring')
        if not passage or len(passage) > max_chars:
            raise AssertionError('passage violates the service limit')
    if len(passages) > 50:
        raise AssertionError(f'too many passages: {len(passages)}')
    return passages, mapping


def load_parquet(split: str) -> dict:
    try:
        import pyarrow.parquet as pq
    except ImportError as e:
        raise SystemExit('pyarrow is required: rerun with `uv run --with pyarrow ...`') from e
    path = RAW / f'aggrefact-data-{split}-00000-of-00001.parquet'
    if not path.is_file():
        raise SystemExit(f'STOP: missing {path}; run annotation.v27.fetch --dataset aggrefact')
    return pq.read_table(path).to_pydict()


def _group(split: str) -> tuple[dict[str, dict[str, list[tuple[str, int]]]], dict]:
    data = load_parquet(split)
    grouped: dict[str, dict[str, list[tuple[str, int]]]] = collections.defaultdict(
        lambda: collections.defaultdict(list))
    for subset, doc, claim, label in zip(data['dataset'], data['doc'], data['claim'],
                                         data['label']):
        if subset == EXCLUDED_SUBSET:
            continue
        grouped[subset][doc].append((claim, int(label)))
    if set(grouped) != set(SUBSETS):
        raise SystemExit(f'STOP: subsets differ: {sorted(grouped)}')
    return grouped, {}


def _doc_rank(doc: str) -> tuple[float, str]:
    digest = hashlib.sha256(doc.encode('utf-8')).hexdigest()
    return random.Random(f'{SEED}:doc:{digest}').random(), digest


def select(split: str, target: int) -> tuple[list[dict], dict]:
    grouped, _ = _group(split)
    rows, stats = [], {'split': split, 'target_claims_per_subset': target, 'subsets': {}}
    for subset in SUBSETS:
        docs = grouped[subset]
        kept = {doc: claims for doc, claims in docs.items()
                if len(doc.split()) <= MAX_DOC_WORDS}
        excluded_docs = len(docs) - len(kept)
        excluded_claims = sum(len(c) for d, c in docs.items() if d not in kept)
        ordered = sorted(((rank, digest, doc, claims)
                          for doc, claims in kept.items()
                          for rank, digest in [_doc_rank(doc)]), key=lambda x: (x[0], x[1]))
        chosen, n = [], 0
        for _, digest, doc, claims in ordered:
            chosen.append((doc, claims, digest))
            n += len(claims)
            if n >= target:
                break
        if n < target:
            raise SystemExit(f'STOP: subset {subset} has only {n} claims after the cap')
        for doc, claims, digest in chosen:
            passages, mapping = split_document(doc)
            rows.append({
                'id': f'aggrefact-{subset}-{digest[:12]}',
                'split': split,
                'subset': subset,
                'context_passages': passages,
                'passage_map': mapping,
                'claims': [c for c, _ in claims],
                'labels': [l for _, l in claims],
                'gold_claims': [{'claim_text': c, 'label': l} for c, l in claims],
                'provenance': {
                    'dataset': 'LLM-AggreFact',
                    'subset': subset,
                    'doc_sha256': digest,
                    'doc_words': len(doc.split()),
                    'claims': len(claims),
                    'passages': len(passages),
                    'selection': {'seed': SEED, 'rank': _doc_rank(doc)[0]},
                    'source_revision': json.loads(
                        (ROOT / 'data' / 'annotation' / 'v2.7' / 'sources.json')
                        .read_text(encoding='utf-8'))['datasets']['aggrefact']['revision'],
                },
            })
        stats['subsets'][subset] = {
            'docs_total': len(docs),
            'claims_total': sum(len(c) for c in docs.values()),
            'excluded_docs_over_4000_words': excluded_docs,
            'excluded_claims_over_4000_words': excluded_claims,
            'selected_docs': len(chosen),
            'selected_claims': n,
            'selected_positives': sum(l for _, claims, _ in chosen for _, l in claims),
            'selected_doc_words_min_median_max': [
                min(len(d.split()) for d, _, _ in chosen),
                statistics.median(len(d.split()) for d, _, _ in chosen),
                max(len(d.split()) for d, _, _ in chosen),
            ],
        }
    rows.sort(key=lambda r: r['id'])
    stats['totals'] = {
        'docs': len(rows),
        'claims': sum(len(r['claims']) for r in rows),
        'positives': sum(sum(r['labels']) for r in rows),
        'selected_positives_rate': sum(sum(r['labels']) for r in rows) / max(
            1, sum(len(r['claims']) for r in rows)),
    }
    return rows, stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--split', choices=['test', 'dev'], default='test')
    ap.add_argument('--target', type=int, default=None)
    ap.add_argument('--stats', action='store_true')
    ap.add_argument('--write', action='store_true')
    args = ap.parse_args()
    target = args.target if args.target is not None else (100 if args.split == 'test' else 10)
    rows, stats = select(args.split, target)
    if args.stats or not args.write:
        print(json.dumps(stats, indent=2, ensure_ascii=False))
        return
    out = ROOT / 'data' / f'eval_aggrefact.v2.7.{args.split}.jsonl'
    selection = ROOT / 'data' / 'annotation' / 'v2.7' / f'aggrefact-selection-{args.split}.json'
    with out.open('x', encoding='utf-8') as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')
    selection.write_text(json.dumps(stats, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'wrote {out} ({len(rows)} docs, {stats["totals"]["claims"]} claims)')


if __name__ == '__main__':
    main()
