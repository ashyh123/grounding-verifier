"""Documentation cannot drift: every artifact and link the docs point at must exist.

A doc set that references `results/foo` after a rename, or links a file that was never written, is
worse than no doc set — a reader loses trust in everything else it says. These checks are cheap and
they fail loudly.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from statistics import mean, pstdev

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCS = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]

RESULTS_DIR_RE = re.compile(r"\bresults/([A-Za-z0-9_.-]+)")
MD_LINK_RE = re.compile(r"\]\(([^)#\s]+\.md)(#[^)\s]*)?\)")
ANCHOR_LINK_RE = re.compile(r"\]\(([^)\s#]+\.md)#([^)\s]+)\)")


def _slug(heading: str) -> str:
    """GitHub's heading anchor: lowercase, code spans and links unwrapped, punctuation dropped."""
    s = re.sub(r"`([^`]*)`", r"\1", heading.strip().lower())
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"[^\w\s-]", "", s)
    return re.sub(r"\s+", "-", s).strip("-")


def _docs() -> list[Path]:
    assert DOCS, "no markdown documents found"
    return DOCS


@pytest.mark.parametrize("doc", _docs(), ids=lambda p: p.name)
def test_referenced_result_dirs_exist(doc: Path):
    """Placeholders like results/<timestamp> are templates; concrete names must be on disk."""
    for match in RESULTS_DIR_RE.finditer(doc.read_text(encoding="utf-8")):
        name = match.group(1)
        if "<" in name or name in {"final", "final_"}:  # template wording, not a real directory
            continue
        assert (ROOT / "results" / name).is_dir(), f"{doc.name} references missing results/{name}"


@pytest.mark.parametrize("doc", _docs(), ids=lambda p: p.name)
def test_relative_markdown_links_resolve(doc: Path):
    for match in MD_LINK_RE.finditer(doc.read_text(encoding="utf-8")):
        target = (doc.parent / match.group(1)).resolve()
        assert target.is_file(), f"{doc.name} links missing file {match.group(1)}"


@pytest.mark.parametrize("doc", _docs(), ids=lambda p: p.name)
def test_cross_document_anchors_exist(doc: Path):
    """A link to file.md#section breaks silently when the heading is reworded."""
    for match in ANCHOR_LINK_RE.finditer(doc.read_text(encoding="utf-8")):
        target = (doc.parent / match.group(1)).resolve()
        slugs = {_slug(line.lstrip("#")) for line in target.read_text(encoding="utf-8").splitlines()
                 if line.startswith("#")}
        assert match.group(2) in slugs, \
            f"{doc.name} links {match.group(1)}#{match.group(2)}, which is not a heading there"


def test_docs_index_links_every_document():
    index = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")
    for doc in sorted((ROOT / "docs").glob("*.md")):
        if doc.name == "README.md":
            continue
        assert doc.name in index, f"docs/README.md does not list {doc.name}"


HISTORICAL = ("revision", "earlier", "used to", "superseded", "before the")

# The canonical ways the docs state the size of the benchmark. Incidental prose ("8 bundled gold
# claims across 7 cases") is deliberately not policed: prose has history in it, headlines do not.
HEADLINE_FORMS = (
    re.compile(r"(\d+) (?:hand-authored )?cases? / (\d+) (?:gold )?claims?"),
    re.compile(r"(\d+)-case / (\d+)-claim"),
    re.compile(r"(\d+) (?:hand-authored )?cases? \((\d+) dev, (\d+) test\), (\d+) (?:gold )?claims?"),
)


def test_dataset_statistics_quoted_in_docs_match_the_data():
    """Headline counts in every document must agree with the dataset on disk."""
    from eval.dataset import load

    cases = load(ROOT / "data" / "eval.jsonl")
    n_cases = len(cases)
    n_dev = sum(1 for c in cases if c.split == "dev")
    n_test = n_cases - n_dev
    n_claims = sum(len(c.gold_claims) for c in cases)
    n_claims_dev = sum(len(c.gold_claims) for c in cases if c.split == "dev")

    checked = 0
    for doc in _docs():
        for lineno, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), start=1):
            if any(marker in line.lower() for marker in HISTORICAL):
                continue
            for pattern in HEADLINE_FORMS:
                for m in pattern.finditer(line):
                    nums = tuple(int(g) for g in m.groups())
                    where = f"{doc.name}:{lineno}: {m.group(0)!r}"
                    if len(nums) == 2:
                        assert nums in ((n_cases, n_claims), (n_dev, n_claims_dev),
                                        (n_test, n_claims - n_claims_dev)), where
                    else:
                        assert nums == (n_cases, n_dev, n_test, n_claims), where
                    checked += 1
    assert checked >= 6, "expected the docs to state the benchmark size in canonical form"


def test_documented_default_prompt_version_matches_the_code():
    from verifier import prompts

    for doc in _docs():
        text = doc.read_text(encoding="utf-8")
        for m in re.finditer(r"default `(v\d)`", text):
            assert m.group(1) == prompts.DEFAULT_PROMPT_VERSION, \
                f"{doc.name} calls {m.group(1)} the default; the code says {prompts.DEFAULT_PROMPT_VERSION}"


# --------------------------------------------------------------------------------------------------
# Quoted metric tables must match the summaries they were generated from.
#
# This guard exists because a metric change (the fused-claim detector) was applied to `results/` and to
# REPORT.md but not to the copy of the dev table in ITERATIONS.md, and that stale row shipped to a
# public repository. A table in a document is a claim about an artifact, so it is checked like one.

DEV_COLUMNS = [("dev-baseline", "baseline"), ("dev-minimal-x3", "minimal"), ("dev-v1-x3", "optimized"),
               ("dev-v2", "optimized"), ("dev-v3-x3", "optimized"), ("dev-v4-x3", "optimized")]
ORACLE_DEV = [("dev-oracle", "baseline"), ("dev-oracle", "minimal"), ("dev-oracle", "optimized")]
E2E_TEST = [("final_e2e", "baseline"), ("final_e2e", "minimal"), ("final_e2e", "optimized")]
ORACLE_TEST = [("final_oracle", "baseline"), ("final_oracle", "minimal"), ("final_oracle", "optimized")]

QUOTED_ROWS: dict[str, tuple] = {
    "Answer-level hallucination F1": (lambda m: m["answer_level"]["f1"], 3),
    "Claim accuracy (all gold claims)": (lambda m: m["claim_accuracy_all_gold"], 3),
    "Claim accuracy (matched only)": (lambda m: m["claim_accuracy_matched"], 3),
    "Macro-F1 (3 verdicts)": (lambda m: m["macro_f1"], 3),
    "F1 SUPPORTED": (lambda m: m["per_label"]["SUPPORTED"]["f1"], 3),
    "F1 CONTRADICTED": (lambda m: m["per_label"]["CONTRADICTED"]["f1"], 3),
    "F1 UNSUPPORTED": (lambda m: m["per_label"]["UNSUPPORTED"]["f1"], 3),
    "Decomposition recall": (lambda m: m["decomposition"]["recall"], 3),
    "Decomposition precision": (lambda m: m["decomposition"]["precision"], 3),
    "Answer sentence coverage": (lambda m: m["sentence_coverage"], 3),
    "Fused claims": (lambda m: m["fused_claim_rate"], 3),
    "Fused claims (claim spans >1 sentence)": (lambda m: m["fused_claim_rate"], 3),
    "Fused claims (claim carries distinctive words from ≥2 sentences)":
        (lambda m: m["fused_claim_rate"], 3),
    "Citation precision": (lambda m: m["citation_precision"], 3),
    "Citation recall": (lambda m: m["citation_recall"], 3),
    "Citation precision (right passage)": (lambda m: m["citation_passage_precision"], 3),
    "Citation recall (right passage)": (lambda m: m["citation_passage_recall"], 3),
    "Raw citation invalid rate": (lambda m: m["raw_citation_invalid_rate"], 3),
    "Raw citation invalid rate (before repair)": (lambda m: m["raw_citation_invalid_rate"], 3),
    "LLM calls / case": (lambda m: m["avg_llm_calls"], 2),
    "Cost / case (USD)": (lambda m: m["avg_cost_usd"], 4),
    "Errored cases": (lambda m: m["errors"], 0),
}
PAIRED_ROWS = {"Latency p50 / p95 (ms)": ("latency_ms_p50", "latency_ms_p95"),
               "Input / output tokens per case": ("avg_input_tokens", "avg_output_tokens")}
HISTORICAL_MARKERS = ("before the label audit", "pre-audit", "historical", "superseded")


def _runs(directory: str, method: str) -> list[dict]:
    summary = json.loads((ROOT / "results" / directory / "summary.json").read_text(encoding="utf-8"))
    return summary["methods"][method]


def _collect_tables(text: str) -> list[dict]:
    """Every markdown table with its heading path and the caption line directly above it."""
    headings: dict[int, str] = {}
    caption = ""
    tables: list[dict] = []
    current: dict | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            headings = {k: v for k, v in headings.items() if k < level}
            headings[level] = stripped.lstrip("# ").strip()
            caption, current = "", None
            continue
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip().replace("*", "") for c in stripped.strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells):  # separator row
                continue
            if current is None:
                current = {"context": (" / ".join(headings.values()) + " || " + caption).lower(),
                           "header": cells, "rows": []}
                tables.append(current)
            else:
                current["rows"].append(cells)
            continue
        current = None
        if stripped:
            caption = stripped
    return tables


def _source_for(header: list[str], context: str):
    """Which run directory feeds each column of this table.

    `context` is the caption plus the *deepest* heading — not the whole heading stack, because a page
    title like "Hill-climbing log (dev split only)" would otherwise make every table on the page look
    like a dev table and silently rewrite test numbers with dev numbers.
    """
    if header == ["Metric", "baseline", "minimal", "opt v1", "opt v2", "opt v3", "opt v4"]:
        return DEV_COLUMNS
    if header in (["Metric", "baseline", "minimal", "optimized v3"],
                  ["Metric", "baseline", "minimal", "optimized"],
                  ["Metric", "baseline", "minimal", "optimized v3 (4.5 calls)"]):
        if "oracle" in context:
            return ORACLE_DEV if "dev" in context else ORACLE_TEST
        return E2E_TEST
    return None


def _metric_cells(cols, method_value, dp: int) -> list[str]:
    out = []
    for directory, method in cols:
        values = [method_value(r) for r in _runs(directory, method)]
        out.append(f"{values[0]:.{dp}f}" if len(values) == 1
                   else f"{mean(values):.{dp}f} ± {pstdev(values):.{dp}f}")
    return out


def _fmt(value: float, dp: int) -> str:
    """Sub-millisecond values keep two decimals, everything else uses the row's precision."""
    if dp == 0 and value < 1:
        return f"{value:.2f}"
    return f"{value:.{dp}f}"


def _paired_cells(cols, field_a: str, field_b: str, sub_unit_decimals: bool = False) -> list[str]:
    def one(value: float) -> str:
        if sub_unit_decimals and value < 1:
            return f"{value:.2f}"
        return f"{value:.0f}"
    return [" / ".join(one(mean(r[f] for r in _runs(d, m))) for f in (field_a, field_b))
            for d, m in cols]


def _expected_cells(label: str, cols) -> list[str] | None:
    if label in QUOTED_ROWS:
        method_value, dp = QUOTED_ROWS[label]
        out = []
        for directory, method in cols:
            values = [method_value(r) for r in _runs(directory, method)]
            out.append(f"{values[0]:.{dp}f}" if len(values) == 1
                       else f"{mean(values):.{dp}f} ± {pstdev(values):.{dp}f}")
        return out
    if label in PAIRED_ROWS:
        return _paired_cells(cols, *PAIRED_ROWS[label],
                             sub_unit_decimals=label.startswith("Latency"))
    return None


def test_quoted_metric_rows_match_the_summaries():
    """Also usable as a refresher: `DOCS_REFRESH=1 pytest tests/test_docs.py -k quoted` rewrites the
    stale cells in place from `results/*/summary.json`, so a metric change never has to be copied
    into the documents by hand."""
    import os
    refresh = bool(os.environ.get("DOCS_REFRESH"))
    checked, rewritten = 0, 0
    for doc in _docs():
        lines = doc.read_text(encoding="utf-8").splitlines()
        headings: dict[int, str] = {}
        caption = ""
        context = header = None
        cols = None
        touched = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("#"):
                level = len(stripped) - len(stripped.lstrip("#"))
                headings = {k: v for k, v in headings.items() if k < level}
                headings[level] = stripped.lstrip("# ").strip()
                caption, context, header, cols = "", None, None, None
                continue
            if stripped.startswith("|") and stripped.endswith("|"):
                cells = [c.strip().replace("*", "") for c in stripped.strip("|").split("|")]
                if all(set(c) <= set("-: ") for c in cells):
                    continue
                if header is None:  # this line is the header row of a new table
                    header = cells
                    # h1 is the page title ("Hill-climbing log (dev split only)") and would make
                    # every table on the page look like a dev table; sections below it carry the
                    # meaning ("Oracle runs", "Held-out final run").
                    sections = " / ".join(v for k, v in sorted(headings.items()) if k >= 2)
                    context = f"{sections} || {caption}".lower()
                    cols = None if any(m in context for m in HISTORICAL_MARKERS) else _source_for(header, context)
                    if cols is not None and len(header) != len(cols) + 1:
                        cols = None
                    continue
                if cols is None:
                    continue
                expected = _expected_cells(cells[0], cols)
                if expected is None:
                    # a renamed metric row must not silently drop out of this check
                    assert not cells[0].lower().startswith("fused claim"), \
                        f"{doc.name}: fused-claim row {cells[0]!r} is not mapped in QUOTED_ROWS"
                    continue
                checked += 1
                if cells[1:] != expected:
                    if refresh:
                        original = [c.strip() for c in line.strip().strip("|").split("|")][1:]
                        merged = [f"**{v}**" if i < len(original) and original[i].startswith("**") else v
                                  for i, v in enumerate(expected)]
                        lines[i] = "| " + " | ".join([cells[0], *merged]) + " |"
                        rewritten += 1
                        touched = True
                    else:
                        raise AssertionError(
                            f"{doc.name}: '{cells[0]}' does not match {[c[0] for c in cols]}\n"
                            f"  document: {cells[1:]}\n  results : {expected}")
                continue
            context, header, cols = None, None, None
            if stripped:
                caption = stripped
        if touched:
            doc.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert checked >= 30, f"expected to check the quoted tables, only {checked} rows were checked"
    if refresh:
        assert rewritten > 0, "nothing needed refreshing"
        print(f"refreshed {rewritten} table rows from results/*/summary.json")
