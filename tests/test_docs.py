"""Documentation cannot drift: every artifact and link the docs point at must exist.

A doc set that references `results/foo` after a rename, or links a file that was never written, is
worse than no doc set — a reader loses trust in everything else it says. These checks are cheap and
they fail loudly.
"""
from __future__ import annotations

import re
from pathlib import Path

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
