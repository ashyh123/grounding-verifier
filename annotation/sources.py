"""Upstream sources for the v2 annotation pipeline: loading, segmentation, ids.

Segmentation here is deliberately mechanical. It only ever *cuts* upstream text and inserts
separators; it never rewrites words, fixes typos or removes spaces inside a segment. Every case
built from this module is checked against that promise (`check_segmentation`), so a quote taken
from `context_passages` is always a verbatim substring of the upstream text.

Reads only files under `data/sources/v2/raw/` (git-ignored); writes nothing.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "sources" / "v2" / "raw"
SOURCES_V2 = ROOT / "data" / "sources" / "v2"
ANNOTATION_DIR = ROOT / "data" / "annotation"
WIKI_CACHE = RAW / "wiki"

# Service limits (unchanged by this pipeline; see verifier/api.py and docs/EVALUATION.md).
MAX_PASSAGES = 50
MAX_PASSAGE_CHARS = 20_000
MAX_ANSWER_CHARS = 10_000

RAGTRUTH_SPLIT = "test"  # the single upstream split every RAGTruth case is drawn from
# RAGTruth generators allowed by the design doc: GPT-4/GPT-3.5 for >=70% of cases, and
# llama-2-70B / Mistral for the rest. Llama-2-7B/13B are excluded: their hallucinations are
# obvious, so they add length without adding difficulty.
RAGTRUTH_MODELS = ("gpt-4-0613", "gpt-3.5-turbo-0613", "llama-2-70b-chat", "mistral-7B-instruct")
GPT_MODELS = ("gpt-4-0613", "gpt-3.5-turbo-0613")

# RAGTruth ids already used by the previous project (`data/sources/manifest.json` of the old
# repository, key `selected_response_ids`): their source groups must not be sampled again.
LEGACY_RESPONSE_IDS = frozenset({
    "13687", "14785", "15997", "16049", "13500", "14006", "15379", "16530", "17502", "16681",
    "16021", "16262", "14131",
})

QA_PREFIX = re.compile(r"passage \d+:")


def words(text: str) -> int:
    """Word count used by every length rule in the spec: whitespace-separated tokens."""
    return len(text.split())


def ws(text: str) -> str:
    """Text with all whitespace removed, for the 'segmentation only cut text' checks."""
    return re.sub(r"\s+", "", text)


def slug(text: str) -> str:
    """Lowercase ASCII id fragment: 'Doug Sheehan' -> 'doug-sheehan'."""
    norm = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", norm.lower()).strip("-")


# Draft labels use two extra pseudo-verdicts for "this is the upstream's candidate, a human has to
# confirm it". Everything downstream compares real verdicts, so they are normalised in one place:
# a human agreeing with SUPPORTED_CANDIDATE has decided SUPPORTED.
PSEUDO_VERDICTS = {"SUPPORTED_CANDIDATE": "SUPPORTED", "NOT_SUPPORTED": "UNSUPPORTED"}
VERDICTS = ("SUPPORTED", "CONTRADICTED", "UNSUPPORTED")


def normalize_verdict(verdict: str | None) -> str | None:
    """Map a draft verdict onto a real one; leave real verdicts and None alone."""
    if verdict is None:
        return None
    return PSEUDO_VERDICTS.get(verdict.upper(), verdict.upper())


def require_annotation_model(model: str | None, setting: str) -> str:
    """All annotation roles require a user-selected model outside the DeepSeek family."""
    if not model or not model.strip():
        raise SystemExit(f"STOP: {setting} must be explicitly selected by the user; no default.")
    if "deepseek" in re.sub(r"[^a-z0-9]", "", model.lower()):
        raise SystemExit(f"STOP: {setting} cannot use the DeepSeek family (design v2.2).")
    return model


def rel(path: Path) -> str:
    """Path relative to the repo when it is inside it, absolute otherwise (for printing)."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


# --------------------------------------------------------------------------- loading

def _jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def load_ragtruth_sources() -> dict[str, dict[str, Any]]:
    """source_id -> source record (`source_info.jsonl`)."""
    return {r["source_id"]: r for r in _jsonl(RAW / "source_info.jsonl")}


def load_ragtruth_responses() -> list[dict[str, Any]]:
    return list(_jsonl(RAW / "response.jsonl"))


def load_factscore() -> list[tuple[str, dict[str, Any]]]:
    """[(generator, record)] for the three human-annotated files (183 entities each)."""
    out: list[tuple[str, dict[str, Any]]] = []
    for gen, name in (("InstructGPT", "InstructGPT.jsonl"), ("ChatGPT", "ChatGPT.jsonl"),
                      ("PerplexityAI", "PerplexityAI.jsonl")):
        out.extend((gen, r) for r in _jsonl(RAW / name))
    return out


def load_halueval() -> list[dict[str, Any]]:
    """`summarization_data.json` is JSONL despite the extension; line order is the record order."""
    return list(_jsonl(RAW / "summarization_data.json"))


def factscore_facts(record: dict[str, Any]) -> list[dict[str, str]]:
    """Human atomic facts of one FActScore record, in order, IR included."""
    facts: list[dict[str, str]] = []
    for sentence in record.get("annotations") or []:
        facts.extend(sentence.get("human-atomic-facts") or [])
    return facts


def factscore_non_ir(record: dict[str, Any]) -> list[dict[str, str]]:
    return [f for f in factscore_facts(record) if f.get("label") != "IR"]


# --------------------------------------------------------------------------- segmentation

def split_qa_passages(passages_field: str) -> list[str]:
    """RAGTruth QA: cut on the `passage N:` prefixes, drop the prefixes and the outer whitespace.

    Same rule as the previous project's `evaluation/build_candidates.py`.
    """
    segments = QA_PREFIX.split(passages_field)[1:]
    return [s.strip() for s in segments]


# Sentence boundary: . ! ? (with an optional closing quote/bracket) followed by whitespace and
# then something that can start a sentence. `verifier.segment` uses the same shape, but it hands
# each sentence a trimmed range, which drops a closing quote that sits between a sentence and the
# following space. Here the boundary only decides *where to cut*: every character between the
# first and the last sentence of a chunk is carried into the passage untouched.
_BOUNDARY = re.compile(r"""(?<=[.!?])["')\]]?\s+(?=["'(\[A-Z0-9])""")


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    cursor = 0
    for m in _BOUNDARY.finditer(text):
        spans.append((cursor, m.end()))
        cursor = m.end()
    spans.append((cursor, len(text)))
    out: list[tuple[int, int]] = []
    for a, b in spans:
        while a < b and text[a].isspace():
            a += 1
        while b > a and text[b - 1].isspace():
            b -= 1
        if a < b:
            out.append((a, b))
    return out


def _sentence_chunks(text: str, target_words: int) -> list[str]:
    """Cut `text` at sentence ends into chunks of about `target_words` words.

    Slices are exact offsets into `text`, so nothing between the first and last sentence of a
    chunk is altered: the only characters not carried over are the separators between chunks.
    """
    spans = _sentence_spans(text)
    if not spans:
        return [text.strip()] if text.strip() else []
    chunks: list[tuple[int, int]] = []
    start, end = spans[0]
    count = words(text[start:end])
    for a, b in spans[1:]:
        if count >= target_words:
            chunks.append((start, end))
            start, end, count = a, b, words(text[a:b])
        else:
            end = b
            count += words(text[a:b])
    chunks.append((start, end))
    return [text[a:b] for a, b in chunks]


def split_paragraphs(text: str, target_words: int = 120) -> list[str]:
    """Natural paragraphs when the text has blank lines, else sentence chunks of ~120 words."""
    parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(parts) > 1:
        return parts
    return _sentence_chunks(text, target_words)


def _top_level_spans(dump: str) -> list[tuple[str, int, int, int]]:
    """(key, key_start, value_start, value_end) for the top-level keys of a JSON object dump."""
    dec = json.JSONDecoder()
    spans: list[tuple[str, int, int, int]] = []
    n = len(dump)
    i = dump.index("{") + 1
    while i < n:
        while i < n and dump[i] in " \n\t,":
            i += 1
        if i >= n or dump[i] == "}":
            break
        key_start = i
        key, j = dec.raw_decode(dump, i)
        while j < n and dump[j] in " \n\t":
            j += 1
        assert dump[j] == ":", f"malformed JSON dump at {j}"
        j += 1
        while j < n and dump[j] in " \n\t":
            j += 1
        _, end = dec.raw_decode(dump, j)
        spans.append((key, key_start, j, end))
        i = end
    return spans


def _list_element_spans(dump: str, start: int, end: int) -> list[tuple[int, int]]:
    """Spans of the elements of a top-level JSON array at dump[start:end]."""
    dec = json.JSONDecoder()
    spans: list[tuple[int, int]] = []
    i = start
    while i < end and dump[i] != "[":
        i += 1
    i += 1
    while i < end:
        while i < end and dump[i] in " \n\t,":
            i += 1
        if i >= end or dump[i] == "]":
            break
        _, e = dec.raw_decode(dump, i)
        spans.append((i, e))
        i = e
    return spans


def split_data2txt(source_info: dict[str, Any]) -> list[str]:
    """Yelp JSON: one passage per field group, content kept as the original JSON text.

    Groups are contiguous runs of top-level keys (basic info, opening hours, attributes + stars,
    and one passage per review). Passages are exact slices of one `json.dumps` of the record, so
    concatenating them reproduces that JSON text character for character.
    """
    dump = json.dumps(source_info, ensure_ascii=False, indent=1)
    spans = _top_level_spans(dump)
    if not spans:
        return [dump]

    # Which passage each top-level key belongs to; unlisted keys form passages of their own.
    label_of = {k: k for k, _, _, _ in spans}
    for keys, label in ((["name", "address", "city", "state", "categories"], "基本信息"),
                        (["hours"], "营业时间"),
                        (["attributes", "business_stars"], "属性")):
        for k in keys:
            if k in label_of:
                label_of[k] = label

    items: list[tuple[str, int, int]] = []  # (group label, start, end) in document order
    for key, key_start, value_start, value_end in spans:
        if key == "review_info":
            for n, (a, b) in enumerate(_list_element_spans(dump, value_start, value_end)):
                # every review is its own passage; the first one carries the key and the bracket
                items.append((f"评论{n + 1}", key_start if n == 0 else a, b))
            continue
        label = label_of[key]
        if items and items[-1][0] == label:  # consecutive keys of one group merge
            items[-1] = (label, items[-1][1], value_end)
        else:
            items.append((label, key_start, value_end))

    # A passage runs from its group's first character to the next group's first character, so
    # concatenating the passages reproduces `dump` exactly (the first one also carries "{").
    return [dump[0 if n == 0 else start:(items[n + 1][1] if n + 1 < len(items) else len(dump))]
            for n, (_label, start, _end) in enumerate(items)]


def split_wikipedia(text: str) -> tuple[list[str], bool]:
    """Wikipedia article plain text: paragraphs, capped at MAX_PASSAGES.

    Returns (passages, truncated). Truncation is recorded on the case; T4 flags the FActScore
    facts whose evidence may have been cut off.
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    truncated = False
    if len(paragraphs) > MAX_PASSAGES:
        paragraphs, truncated = paragraphs[:MAX_PASSAGES], True
    kept: list[str] = []
    for p in paragraphs:
        if len(p) <= MAX_PASSAGE_CHARS:
            kept.append(p)
            continue
        # A single paragraph over the service limit: cut it at a sentence end and stop here, so
        # the case stays inside the limit and says so.
        chunks = _sentence_chunks(p, 1_000_000)
        size = 0
        for c in chunks:
            if size + len(c) > MAX_PASSAGE_CHARS:
                break
            kept.append(c)
            size += len(c)
        truncated = True
        break
    return kept, truncated


def enforce_limits(passages: list[str]) -> tuple[list[str], bool]:
    """Cap the passage count at the service limit. Returns (passages, truncated).

    Answers are never truncated: RAGTruth's label offsets are relative to the answer text, so a
    shortened answer would silently invalidate them. An over-long answer is dropped as a candidate
    during selection instead (`MAX_ANSWER_CHARS`).
    """
    if len(passages) > MAX_PASSAGES:
        return passages[:MAX_PASSAGES], True
    return passages, False


# --------------------------------------------------------------------------- checks

@dataclass
class SegmentationCheck:
    case_id: str
    ok: bool
    detail: str = ""


def check_segmentation(case_id: str, passages: list[str], original: str,
                       prefixes: list[str] | None = None,
                       allow_prefix: bool = False) -> SegmentationCheck:
    """`"".join(passages)` must equal `original` up to separator whitespace.

    `prefixes` lists markup removed on purpose (RAGTruth QA: `passage N:`), which is subtracted
    from the original before comparing. `allow_prefix` is for truncated cases (a Wikipedia
    article cut at the service limit): the passages must then reproduce an initial slice.
    """
    stripped = original
    for p in prefixes or []:
        stripped = stripped.replace(p, "")
    joined = ws("".join(passages))
    target = ws(stripped)
    if joined == target or (allow_prefix and target.startswith(joined)):
        return SegmentationCheck(case_id, True)
    return SegmentationCheck(
        case_id, False,
        f"concatenated passages differ from the upstream text beyond whitespace "
        f"({len(joined)} vs {len(target)} chars)")


def qa_prefixes(passages_field: str) -> list[str]:
    return QA_PREFIX.findall(passages_field)


# --------------------------------------------------------------------------- case records

@dataclass
class Candidate:
    """One sampled case before any model touches it (T1+T2 output)."""
    id: str
    source: str  # ragtruth_summary | ragtruth_qa | ragtruth_data2txt | factscore_<gen> | halueval_summary
    split: str
    context_passages: list[str]
    generated_answer: str
    generator_model: str
    context_words: int
    source_group_id: str
    source_labels: dict[str, Any] = field(default_factory=dict)
    difficulty_tags: list[str] = field(default_factory=list)
    truncated: bool = False
    provenance: dict[str, Any] = field(default_factory=dict)
    selection: dict[str, Any] = field(default_factory=dict)
    passage_map: list[dict[str, Any]] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "split": self.split,
            "context_passages": self.context_passages,
            "generated_answer": self.generated_answer,
            "generator_model": self.generator_model,
            "context_words": self.context_words,
            "source_group_id": self.source_group_id,
            "source_labels": self.source_labels,
            "difficulty_tags": self.difficulty_tags,
            "truncated": self.truncated,
            "provenance": self.provenance,
            "selection": self.selection,
            "passage_map": self.passage_map,
        }


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return list(_jsonl(path))
