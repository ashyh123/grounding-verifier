"""T1+T2 — sample 30 RAGTruth candidates by objective rules alone, then segment them.

    uv run python -m annotation.select_cases                 # select + segment -> candidates.jsonl
    uv run python -m annotation.select_cases --offline       # never touch the network (wiki cache only)

Rules that matter (spec T1/T2):

* Only rules a script can check are used: upstream split, answer/context length, the upstream
  label stratum, and the generator model. No model prediction, no per-case hand-picking: the
  whole sample is one seeded draw, so re-running the script reproduces it exactly.
* One response per source group (`source_id` and near-duplicate text for RAGTruth), and a group
  never straddles dev and test.
* Nothing is rewritten: segmentation only cuts text and inserts separators, and every case is
  checked for that before it is written.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import urllib.error
from collections import Counter, defaultdict
from typing import Any

from . import sources as S

SEED = 20261019
CANDIDATES = S.ANNOTATION_DIR / "candidates.jsonl"
SELECTION = S.ANNOTATION_DIR / "selection.json"
WIKI_REQUESTS = S.ANNOTATION_DIR / "wiki_requests.json"

# v2.2: 30 RAGTruth cases, 10 dev / 20 test. Other dataset helpers remain unused.
QUOTAS: dict[str, dict[str, int]] = {
    "ragtruth_summary": {"dev": 6, "test": 12},
    "ragtruth_qa": {"dev": 3, "test": 5},
    "ragtruth_data2txt": {"dev": 1, "test": 3},
}
STRATA = {"dev": {"subtle": 5, "evident_only": 3, "clean": 2},
          "test": {"subtle": 10, "evident_only": 5, "clean": 5}}
GPT_QUOTAS = {"dev": 7, "test": 14}
NEAR_DUPLICATE_THRESHOLD = 0.8

# FActScore generators, spread across the 8 cases (the spec fixes no quota, only "one generator
# per entity"; this keeps all three human-annotation files in play).
FACTSCORE_TARGETS = {"dev": ("InstructGPT", "ChatGPT", "PerplexityAI"),
                     "test": ("InstructGPT", "InstructGPT", "ChatGPT", "ChatGPT", "PerplexityAI")}
FACTSCORE_MIN_FACTS, FACTSCORE_MAX_FACTS = 8, 25

MIN_WORDS = {"Summary": 80, "QA": 60, "Data2txt": 100}
MIN_CONTEXT_WORDS = 400  # RAGTruth Summary and HaluEval documents
TASK_SOURCE = {"Summary": "ragtruth_summary", "QA": "ragtruth_qa", "Data2txt": "ragtruth_data2txt"}


def seeded_rank(key: str) -> float:
    """Stable pseudo-random rank for a key: same seed -> same order, whatever the iteration order."""
    return random.Random(f"{SEED}:{key}").random()


# --------------------------------------------------------------------------- RAGTruth

def source_context(source: dict[str, Any]) -> str:
    info = source["source_info"]
    if source["task_type"] == "QA":
        return "\n\n".join(S.split_qa_passages(info["passages"]))
    if source["task_type"] == "Data2txt":
        return json.dumps(info, ensure_ascii=False, indent=1)
    return info


def duplicate_groups(documents: dict[str, str]) -> dict[str, str]:
    """Connected components of word-5-gram Jaccard >= .8, with an inverted index.

    Normalisation here is only for duplicate detection, never for the saved context or evidence.
    """
    parent = {key: key for key in documents}

    def root(key: str) -> str:
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    grams: dict[str, set[tuple[str, ...]]] = {}
    index: dict[tuple[str, ...], set[str]] = defaultdict(set)
    for key, text in sorted(documents.items()):
        tokens = re.findall(r"\w+", text.lower())
        current = {tuple(tokens[i:i + 5]) for i in range(max(1, len(tokens) - 4))}
        possible: set[str] = set()
        for gram in current:
            possible.update(index[gram])
        for other in sorted(possible):
            previous = grams[other]
            if min(len(current), len(previous)) < NEAR_DUPLICATE_THRESHOLD * max(len(current), len(previous)):
                continue
            score = len(current & previous) / max(1, len(current | previous))
            if score >= NEAR_DUPLICATE_THRESHOLD:
                a, b = sorted((root(key), root(other)))
                parent[b] = a
        grams[key] = current
        for gram in current:
            index[gram].add(key)
    return {key: root(key) for key in documents}


def ragtruth_pool() -> list[dict[str, Any]]:
    """Every RAGTruth response in the chosen upstream split that passes the objective rules."""
    src = S.load_ragtruth_sources()
    responses = S.load_ragtruth_responses()
    # The previous project's responses, and every source group they came from, are off limits.
    legacy_sources = {src[r["source_id"]]["source_id"] for r in responses
                      if r["id"] in S.LEGACY_RESPONSE_IDS and r["source_id"] in src}
    out: list[dict[str, Any]] = []
    for r in responses:
        if r["split"] != S.RAGTRUTH_SPLIT or r["quality"] != "good":
            continue
        if r["model"] not in S.RAGTRUTH_MODELS:
            continue
        source = src.get(r["source_id"])
        if source is None:
            continue
        if r["id"] in S.LEGACY_RESPONSE_IDS or source["source_id"] in legacy_sources:
            continue  # already used by the previous project, or sharing a source with it
        task = source["task_type"]
        answer = r["response"]
        if len(answer) > S.MAX_ANSWER_CHARS or S.words(answer) < MIN_WORDS[task]:
            continue
        if task == "QA":
            passages = S.split_qa_passages(source["source_info"]["passages"])
            if len(passages) != 3 or not all(p.strip() for p in passages):
                continue
            context = " ".join(passages)
        elif task == "Data2txt":
            context = json.dumps(source["source_info"], ensure_ascii=False)
        else:
            context = source["source_info"]
            if S.words(context) < MIN_CONTEXT_WORDS:
                continue
        labels = r["labels"]
        if any(label["label_type"].startswith("Subtle") for label in labels):
            stratum = "subtle"
        elif labels:
            stratum = "evident_only"
        else:
            stratum = "clean"
        out.append({
            "response_id": r["id"], "source_id": source["source_id"], "task": task,
            "model": r["model"], "stratum": stratum, "answer": answer,
            "context_words": S.words(context), "group": f"ragtruth-{source['source_id']}",
            "is_gpt": r["model"] in S.GPT_MODELS,
            "rank": seeded_rank(f"ragtruth-{r['id']}"),
            "record": r, "source": source,
        })
    documents = {item["group"]: source_context(item["source"]) for item in out}
    blocked = {f"ragtruth-{key}": source_context(src[key]) for key in legacy_sources}
    for old in S.read_jsonl(S.ROOT / "data" / "eval.jsonl"):
        blocked[f"legacy-eval-{old['id']}"] = "\n\n".join(old["context_passages"])
    groups = duplicate_groups(documents | blocked)
    excluded_groups = {groups[key] for key in blocked}
    out = [item for item in out if groups[item["group"]] not in excluded_groups]
    for item in out:
        item["group"] = groups[item["group"]]
    print(f"RAGTruth: {len(out)} eligible responses in upstream split {S.RAGTRUTH_SPLIT!r} "
          f"({len(S.LEGACY_RESPONSE_IDS)} legacy response ids and {len(legacy_sources)} source "
          f"groups excluded)")
    return out


def select_ragtruth(pool: list[dict[str, Any]]) -> list[S.Candidate]:
    import numpy as np
    from scipy.optimize import Bounds, LinearConstraint, milp
    from scipy.sparse import lil_matrix

    # Solve the declared margins together. Greedy cell filling can spend a rare source group
    # needed by another cell, despite a feasible global sample. SciPy is already a dependency.
    choices = [(item, split) for item in sorted(pool, key=lambda c: c["response_id"])
               for split in ("dev", "test")]
    constraints = []
    for task, source in TASK_SOURCE.items():
        for split, count in QUOTAS[source].items():
            constraints.append(([i for i, (c, s) in enumerate(choices)
                                 if c["task"] == task and s == split], count, count))
    for split, strata in STRATA.items():
        for stratum, count in strata.items():
            constraints.append(([i for i, (c, s) in enumerate(choices)
                                 if c["stratum"] == stratum and s == split], count, count))
        constraints.append(([i for i, (c, s) in enumerate(choices)
                             if c["is_gpt"] and s == split], GPT_QUOTAS[split], GPT_QUOTAS[split]))
    groups: dict[str, list[int]] = defaultdict(list)
    for i, (item, _split) in enumerate(choices):
        groups[item["group"]].append(i)
    constraints.extend((indices, 0, 1) for indices in groups.values())
    matrix = lil_matrix((len(constraints), len(choices)))
    for row, (indices, _lo, _hi) in enumerate(constraints):
        matrix[row, indices] = 1
    result = milp(
        c=np.array([seeded_rank(f"{c['response_id']}:{split}") for c, split in choices]),
        integrality=np.ones(len(choices)), bounds=Bounds(0, 1),
        constraints=LinearConstraint(matrix.tocsr(), [c[1] for c in constraints],
                                     [c[2] for c in constraints]),
        options={"mip_rel_gap": 0.0})
    if not result.success:
        raise SystemExit(f"STOP: declared sampling constraints are infeasible: {result.message}")
    return [_ragtruth_candidate(c, split, c["task"], c["stratum"])
            for (c, split), chosen in zip(choices, result.x) if chosen > 0.5]


def _ragtruth_candidate(item: dict[str, Any], split: str, task: str, stratum: str) -> S.Candidate:
    r, source = item["record"], item["source"]
    labels = r["labels"]
    for label in labels:  # upstream offsets are relative to the untouched answer
        assert r["response"][label["start"]:label["end"]] == label["text"], \
            f"upstream label offsets do not match the answer for response {r['id']}"
    if task == "QA":
        passages = S.split_qa_passages(source["source_info"]["passages"])
        original = source["source_info"]["passages"]
        prefixes = S.qa_prefixes(original)
    elif task == "Data2txt":
        passages = S.split_data2txt(source["source_info"])
        original, prefixes = json.dumps(source["source_info"], ensure_ascii=False, indent=1), []
    else:
        passages = S.split_paragraphs(source["source_info"])
        original, prefixes = source["source_info"], []
    if len(passages) > S.MAX_PASSAGES or any(len(p) > S.MAX_PASSAGE_CHARS for p in passages):
        raise SystemExit(f"STOP: response {r['id']} exceeds context limits; truncation forbidden.")
    passage_map = passage_mapping(original, passages, prefixes)
    truncated = False
    check = S.check_segmentation(f"ragtruth-{r['id']}", passages, original, prefixes)
    assert check.ok, check.detail
    source_labels: dict[str, Any] = {"labels": labels}
    if task == "QA":
        source_labels["question"] = source["source_info"]["question"]
    tags = sorted(_ragtruth_tags(labels, item["context_words"]))
    return S.Candidate(
        id=f"ragtruth-{r['id']}", source=TASK_SOURCE[task], split=split,
        context_passages=passages, generated_answer=r["response"],
        generator_model=r["model"], context_words=S.words(" ".join(passages)),
        source_group_id=item["group"], source_labels=source_labels, difficulty_tags=tags,
        truncated=truncated,
        provenance={
            "dataset": "RAGTruth",
            "response_id": r["id"], "source_id": source["source_id"],
            "task_type": task, "upstream_split": r["split"], "upstream_quality": r["quality"],
            "upstream_title": source.get("source"),
            "snapshot": "data/sources/v2/manifest.json",
            "context_sha256": hashlib.sha256(original.encode("utf-8")).hexdigest(),
            "passage_map_basis": {"snapshot": "data/sources/v2/raw/source_info.jsonl",
                                  "source_id": source["source_id"],
                                  "field": "source_info.passages" if task == "QA" else "source_info",
                                  "serialization": "json.dumps(ensure_ascii=False, indent=1)"
                                                   if task == "Data2txt" else "original string",
                                  "offset_unit": "Unicode characters"},
            "segmentation": {
                "Summary": "natural paragraphs (blank lines)",
                "QA": "split on the 'passage N:' prefixes, prefixes dropped, outer whitespace trimmed",
                "Data2txt": "one passage per JSON field group, content kept as the original JSON text",
            }[task],
        },
        passage_map=passage_map,
        selection={"seed": SEED, "stratum": stratum, "cell": f"{task}/{split}/{stratum}",
                   "generator_class": "gpt" if item["is_gpt"] else "other"},
    )


def passage_mapping(original: str, passages: list[str], prefixes: list[str]) -> list[dict[str, Any]]:
    """Map exact slices and all removed whitespace/QA markers back to the source snapshot."""
    mapping = []
    cursor = 0
    for index, passage in enumerate(passages):
        start = original.find(passage, cursor)
        if start < 0:
            raise ValueError("context passage is not an exact slice of the snapshot")
        gap = original[cursor:start]
        marker_free = S.QA_PREFIX.sub("", gap) if prefixes else gap
        if marker_free.strip():
            raise ValueError("segmentation removed non-whitespace source content")
        end = start + len(passage)
        mapping.append({"index": index, "start_char": start, "end_char": end,
                        "removed_before": gap, "removed_after": "",
                        "removed_markers": S.qa_prefixes(gap) if prefixes else []})
        cursor = end
    tail = original[cursor:]
    if tail.strip():
        raise ValueError("segmentation removed non-whitespace source tail")
    if mapping:
        mapping[-1]["removed_after"] = tail
    return mapping


def _ragtruth_tags(labels: list[dict[str, Any]], context_words: int) -> set[str]:
    tags: set[str] = set()
    kinds = {lab["label_type"] for lab in labels}
    if not kinds:
        tags.add("clean")
    if any(k.startswith("Subtle") for k in kinds):
        tags.add("subtle")
    if any(k.startswith("Evident") for k in kinds):
        tags.add("evident")
    if any("Conflict" in k for k in kinds):
        tags.add("conflict")
    if any("Baseless" in k for k in kinds):
        tags.add("baseless")
    if any(re.search(r"\d", lab["text"]) for lab in labels):
        tags.add("numeric")
    if context_words >= 800:
        tags.add("long_context")
    return tags


# --------------------------------------------------------------------------- FActScore

def factscore_pool() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for gen, record in S.load_factscore():
        non_ir = S.factscore_non_ir(record)
        if not (FACTSCORE_MIN_FACTS <= len(non_ir) <= FACTSCORE_MAX_FACTS):
            continue
        out.append({
            "generator": gen, "record": record, "non_ir": non_ir,
            "entity": record["topic"], "group": f"factscore-{S.slug(record['topic'])}",
            "rank": seeded_rank(f"factscore-{gen}-{record['topic']}"),
        })
    print(f"FActScore: {len(out)} (entity, generator) pairs with "
          f"{FACTSCORE_MIN_FACTS}-{FACTSCORE_MAX_FACTS} non-IR facts")
    return out


def prefetch_factscore_wikis(pool: list[dict[str, Any]], offline: bool,
                             per_generator: int = 12) -> list[str]:
    """Fetch the Wikipedia revisions of the best-ranked entities *before* anything is selected.

    Selection then only ever reads the cache, so a flaky request can change which entities are
    skipped but can never change the sample silently mid-run. Every generator is covered, because
    the sample spreads its eight cases across all three annotation files. Failures are returned for
    the report (spec T0: report, then skip FActScore rather than invent a context).
    """
    from .fetch_sources import fetch_wikipedia
    failures: list[str] = []
    tried = 0
    for generator in ("InstructGPT", "ChatGPT", "PerplexityAI"):
        ordered = sorted((c for c in pool if c["generator"] == generator),
                         key=lambda c: c["rank"])[:per_generator]
        for item in ordered:
            entity = item["entity"]
            tried += 1
            try:
                item["wiki"] = _wikipedia(entity, offline, fetch_wikipedia)
            except (LookupError, OSError, TimeoutError, urllib.error.URLError,
                    urllib.error.HTTPError, json.JSONDecodeError) as e:
                failures.append(f"{generator} / {entity}: {e}")
    print(f"FActScore: Wikipedia revisions available for {tried - len(failures)}/{tried} "
          f"prefetched (entity, generator) pairs")
    return failures


def select_factscore(pool: list[dict[str, Any]]) -> tuple[list[S.Candidate], list[str]]:
    """Pick one generator per entity, balancing the three generators across dev and test."""
    want = {split: Counter({g: FACTSCORE_TARGETS[split].count(g) for g in set(FACTSCORE_TARGETS[split])})
            for split in ("dev", "test")}
    ordered = sorted(pool, key=lambda c: c["rank"])
    used_entities: set[str] = set()
    chosen: list[tuple[dict[str, Any], str]] = []
    failures: list[str] = []
    for split in ("dev", "test"):
        for generator in FACTSCORE_TARGETS[split]:
            if want[split][generator] <= 0:
                continue
            for item in ordered:
                if item["generator"] != generator or item["entity"] in used_entities:
                    continue
                if "wiki" not in item:  # no revision cached: skipped and reported by the prefetch
                    continue
                used_entities.add(item["entity"])
                want[split][generator] -= 1
                chosen.append((item, split))
                break
            else:
                failures.append(f"no unused {generator} entity with a Wikipedia revision for "
                                f"the {split} quota")
    return [_factscore_candidate(item, split) for item, split in chosen], failures


def _wikipedia(entity: str, offline: bool, fetcher=None) -> dict[str, Any]:
    """Cached revision of `entity`; `fetcher` is injectable so tests never touch the network."""
    if offline:
        cache = S.WIKI_CACHE / f"{S.slug(entity)}.json"
        if not cache.is_file():
            raise LookupError("no cached Wikipedia revision and --offline was given")
        return json.loads(cache.read_text(encoding="utf-8"))
    if fetcher is None:
        from .fetch_sources import fetch_wikipedia
        fetcher = fetch_wikipedia
    return fetcher(entity)


def _factscore_candidate(item: dict[str, Any], split: str) -> S.Candidate:
    record, wiki = item["record"], item["wiki"]
    passages, truncated = S.split_wikipedia(wiki["text"])
    check = S.check_segmentation(
        item["group"], passages, wiki["text"], allow_prefix=truncated)
    assert check.ok, check.detail
    facts = S.factscore_facts(record)
    tags = set()
    if item["non_ir"]:
        tags.add("dense_facts")
    if any(re.search(r"\d", f["text"]) for f in item["non_ir"]):
        tags.add("numeric")
    if S.words(" ".join(passages)) >= 800:
        tags.add("long_context")
    return S.Candidate(
        id=f"factscore-{item['generator'].lower()}-{S.slug(record['topic'])}",
        source=f"factscore_{item['generator'].lower()}", split=split,
        context_passages=passages, generated_answer=record["output"],
        generator_model=item["generator"], context_words=S.words(" ".join(passages)),
        source_group_id=item["group"],
        source_labels={"human_atomic_facts": facts,
                       "non_ir_count": len(item["non_ir"]),
                       "ir_count": len(facts) - len(item["non_ir"])},
        difficulty_tags=sorted(tags), truncated=truncated,
        provenance={
            "dataset": "FActScore",
            "entity": record["topic"], "generator": item["generator"],
            "prompt": record.get("input"), "category": record.get("cat"),
            "snapshot": "data/sources/v2/manifest.json",
            "wikipedia": {"revid": wiki["revid"], "timestamp": wiki["timestamp"],
                          "title": wiki["title"], "source": wiki["source"],
                          "as_of": wiki["as_of"]},
            "segmentation": "Wikipedia revision text split on paragraph breaks"
                            + (", first 50 passages kept (truncated)" if truncated else ""),
        },
        selection={"seed": SEED, "stratum": None, "cell": f"FActScore/{split}",
                   "generator_class": item["generator"]},
    )


# --------------------------------------------------------------------------- HaluEval

def halueval_pool() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line_no, record in enumerate(S.load_halueval(), start=1):
        if S.words(record["document"]) < MIN_CONTEXT_WORDS:
            continue
        out.append({"line": line_no, "record": record,
                    "rank": seeded_rank(f"halueval-{line_no}")})
    print(f"HaluEval: {len(out)} documents with >= {MIN_CONTEXT_WORDS} words")
    return out


def select_halueval(pool: list[dict[str, Any]]) -> list[S.Candidate]:
    ordered = sorted(pool, key=lambda c: c["rank"])
    wanted = [("dev", 1), ("test", 3)]
    picked: list[S.Candidate] = []
    used: set[int] = set()
    for split, count in wanted:
        for item in ordered:
            if item["line"] in used:
                continue
            used.add(item["line"])
            picked.append(_halueval_candidate(item, split))
            count -= 1
            if count == 0:
                break
    return picked


def _halueval_candidate(item: dict[str, Any], split: str) -> S.Candidate:
    record = item["record"]
    passages = S.split_paragraphs(record["document"])
    passages, truncated = S.enforce_limits(passages)
    check = S.check_segmentation(f"halueval-{item['line']}", passages, record["document"],
                                 allow_prefix=truncated)
    assert check.ok, check.detail
    tags = {"hallucinated_source"}
    if S.words(" ".join(passages)) >= 800:
        tags.add("long_context")
    return S.Candidate(
        id=f"halueval-{item['line']}", source="halueval_summary", split=split,
        context_passages=passages, generated_answer=record["hallucinated_summary"],
        generator_model="ChatGPT", context_words=S.words(" ".join(passages)),
        source_group_id=f"halueval-{item['line']}",
        source_labels={"right_summary": record["right_summary"]},
        difficulty_tags=sorted(tags), truncated=truncated,
        provenance={
            "dataset": "HaluEval",
            "subset": "summarization",
            "line": item["line"],
            "snapshot": "data/sources/v2/manifest.json",
            "segmentation": "document split on natural paragraph breaks",
            "note": "answer is the upstream 'hallucinated_summary' (spec T1); right_summary kept "
                    "in source_labels for the reviewer to compare against",
        },
        selection={"seed": SEED, "stratum": None, "cell": f"HaluEval/{split}",
                   "generator_class": "ChatGPT"},
    )


# --------------------------------------------------------------------------- report

def family(source: str) -> str:
    """Quota bucket of a case source: `factscore_chatgpt` -> `factscore`."""
    return "factscore" if source.startswith("factscore") else source


def stats_table(cases: list[S.Candidate]) -> None:
    """The T1 acceptance table: source x split x label stratum x generator model."""
    print("\nSelection (source x split x stratum x model):")
    rows = Counter((c.source, c.split, c.selection.get("stratum") or "-", c.generator_model)
                   for c in cases)
    header = f"  {'source':<24}{'split':<7}{'stratum':<14}{'model':<22}count"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for key in sorted(rows):
        print(f"  {key[0]:<24}{key[1]:<7}{key[2]:<14}{key[3]:<22}{rows[key]}")
    print("\n  quotas:")
    for source, quota in QUOTAS.items():
        for split, want in quota.items():
            got = sum(1 for c in cases if family(c.source) == source and c.split == split)
            flag = "ok" if got == want else "MISMATCH"
            print(f"    {source:<20}{split:<7}want {want:<3}got {got:<3}{flag}")
    print("  strata (RAGTruth only, per split):")
    for split, want in STRATA.items():
        got = Counter(c.selection.get("stratum") for c in cases
                      if c.source.startswith("ragtruth") and c.split == split)
        print(f"    {split:<7}" + "  ".join(f"{k}={got.get(k, 0)}/{v}" for k, v in want.items()))
        clean = got.get("clean", 0)
        if split == "test":
            print(f"    test clean answers: {clean} (spec: at least 4)")
    rag = [c for c in cases if c.source.startswith("ragtruth")]
    gpt = sum(1 for c in rag if c.selection["generator_class"] == "gpt")
    print(f"  RAGTruth generator mix: {gpt}/{len(rag)} GPT-4/GPT-3.5 "
          f"= {gpt / max(len(rag), 1):.0%} (spec: about 70%)")
    split_counts = Counter(c.split for c in cases)
    print(f"  totals: dev={split_counts['dev']} test={split_counts['test']} "
          f"all={len(cases)} (spec: 10 / 20 / 30)")


def to_rows(cases: list[S.Candidate]) -> list[dict[str, Any]]:
    return [c.to_json() for c in cases]


def digest(rows: list[dict[str, Any]]) -> str:
    blob = json.dumps(rows, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def build(rag_pool: list[dict[str, Any]]) -> list[S.Candidate]:
    """Only RAGTruth enters v2.2, including when optional source snapshots exist locally."""
    return select_ragtruth(rag_pool)


def main() -> None:
    ap = argparse.ArgumentParser(description="v2.2: sample 30 RAGTruth cases without model calls")
    ap.add_argument("--offline", action="store_true", help="selection is always offline")
    ap.parse_args()
    pool = ragtruth_pool()
    cases = build(pool)
    rows = to_rows(cases)
    if rows != to_rows(build(list(reversed(pool)))):
        raise SystemExit("STOP: selection is not deterministic; no output written.")
    sha = digest(rows)
    S.write_jsonl(CANDIDATES, rows)
    stats_table(cases)
    table = Counter((c.provenance["task_type"], c.split, c.selection["stratum"], c.generator_model)
                    for c in cases)
    summary = [{"task": k[0], "split": k[1], "stratum": k[2], "generator_model": k[3], "count": n}
               for k, n in sorted(table.items())]
    SELECTION.write_text(json.dumps({
        "design_version": "2.2", "seed": SEED, "created_by": "annotation.select_cases",
        "candidates_sha256": sha, "quotas": QUOTAS, "strata": STRATA,
        "gpt_quotas": GPT_QUOTAS,
        "selection_method": "seeded minimum-cost integer allocation over fixed margins",
        "counts": {"total": len(rows), **dict(Counter(c.split for c in cases))},
        "ragtruth_upstream_split": S.RAGTRUTH_SPLIT,
        "ragtruth_generator_mix": dict(Counter(c.selection["generator_class"] for c in cases)),
        "near_duplicate_rule": {"word_ngram": 5, "jaccard_threshold": NEAR_DUPLICATE_THRESHOLD,
                                "normalization": "lowercase Unicode word tokens; grouping only",
                                "grouping": "connected components; one response per component",
                                "legacy_contexts_excluded": True},
        "statistics": summary,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = ["# v2.2 抽样统计（2026-10-19）", "",
              "仅 RAGTruth：30 例，10 dev / 20 test；GPT 21/30（70%）。",
              "", "| 任务 | split | 标签层 | 生成模型 | 案例数 |",
              "|---|---|---|---|---:|"]
    report.extend(f"| {r['task']} | {r['split']} | {r['stratum']} | {r['generator_model']} | {r['count']} |"
                  for r in summary)
    report.extend(["", "标签层：dev subtle/evident_only/clean = 5/3/2；test = 10/5/5。",
                   "test 的 5 个 clean 案例目前仅为上游 clean，仍待人工确认。",
                   "近重复：小写词 5-gram Jaccard ≥ 0.8 的连通组仅选一条回答；排除旧数据重合组。",
                   "回答逐字保留；每段精确切片及去掉的结构标记和空白均记录在 passage_map。",
                   "无起草、盲审或翻译调用；未生成金标，未运行 hard test。",
                   f"候选 SHA256：`{sha}`。"])
    (S.ANNOTATION_DIR / "selection-stats.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"\nsegmentation: all {len(cases)} cases have exact passage maps; answers untouched")
    print(f"determinism: forward/reversed pool agree (sha256 {sha})")
    print(f"candidates -> {S.rel(CANDIDATES)}; selection -> {S.rel(SELECTION)}")


if __name__ == "__main__":
    main()
