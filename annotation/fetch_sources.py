"""T0 — snapshot the upstream data and verify it is the data we think it is.

    uv run python -m annotation.fetch_sources             # download + verify + manifest + licenses
    uv run python -m annotation.fetch_sources --check     # offline: re-verify what is on disk
    uv run python -m annotation.fetch_sources --wiki      # fetch the Wikipedia revisions to annotate

Nothing here writes into `data/annotation/`: this step only fills `data/sources/v2/` (raw files
are git-ignored, the manifest and licence copies are committed). Field names are checked against
the spec's T0 table and a mismatch stops the run instead of being guessed around.
"""
from __future__ import annotations

import argparse
import hashlib
import html as html_mod
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import sources as S

MANIFEST = S.SOURCES_V2 / "manifest.json"
LICENSES = S.SOURCES_V2 / "licenses"
WIKI_REQUESTS = S.ANNOTATION_DIR / "wiki_requests.json"

RAGTRUTH_BASE = "https://raw.githubusercontent.com/ParticleMedia/RAGTruth/main/dataset"
HALEVAL_SUMMARIZATION = "https://raw.githubusercontent.com/RUCAIBox/HaluEval/main/data/summarization_data.json"
# FActScore's human annotations, released as one Google Drive file (`data.zip`, holds
# data/labeled/{InstructGPT,ChatGPT,PerplexityAI}.jsonl). Id from factscore/download_data.py.
FACTSCORE_DRIVE_ID = "155exEdKs7R21gZF4G-x54-XN3qswBcPo"
FACTSCORE_ZIP = "https://drive.google.com/uc?export=download&id=" + FACTSCORE_DRIVE_ID

LICENSE_URLS = {
    "RAGTruth-LICENSE.txt": "https://raw.githubusercontent.com/ParticleMedia/RAGTruth/main/LICENSE",
    "FActScore-LICENSE.txt": "https://raw.githubusercontent.com/shmsw25/FActScore/main/LICENSE",
    "HaluEval-LICENSE.txt": "https://raw.githubusercontent.com/RUCAIBox/HaluEval/main/LICENSE",
}

# Expected key/value fields, from the spec's T0 table. Extra fields are reported, never a failure.
EXPECTED = {
    "source_info.jsonl": {"type": "jsonl", "keys": ("source_id", "task_type", "source_info")},
    "response.jsonl": {
        "type": "jsonl",
        "keys": ("id", "source_id", "model", "response", "labels", "split"),
        "label_keys": ("start", "end", "text", "label_type"),
    },
    "InstructGPT.jsonl": {"type": "jsonl", "keys": ("topic", "output", "annotations"),
                          "fact_keys": ("text", "label")},
    "ChatGPT.jsonl": {"type": "jsonl", "keys": ("topic", "output", "annotations"),
                      "fact_keys": ("text", "label")},
    "PerplexityAI.jsonl": {"type": "jsonl", "keys": ("topic", "output", "annotations"),
                           "fact_keys": ("text", "label")},
    "summarization_data.json": {"type": "jsonl", "keys": ("document", "right_summary",
                                                          "hallucinated_summary")},
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _get(url: str, timeout: float = 120.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "grounding-verifier-annotation/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https urls
        return resp.read()


def download(url: str, dest: Path, force: bool = False) -> bool:
    """Fetch `url` into `dest`. Returns True when the file was (re)written."""
    if dest.exists() and not force and dest.stat().st_size > 0:
        print(f"  [have] {dest.name} ({dest.stat().st_size:,} bytes)")
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  [get ] {url}")
    data = _get(url)
    dest.write_bytes(data)
    print(f"         -> {dest.name} ({len(data):,} bytes)")
    return True


def fetch_datasets(force: bool = False) -> None:
    print("RAGTruth (MIT)")
    download(f"{RAGTRUTH_BASE}/source_info.jsonl", S.RAW / "source_info.jsonl", force)
    download(f"{RAGTRUTH_BASE}/response.jsonl", S.RAW / "response.jsonl", force)
    print("HaluEval (MIT) — summarization subset")
    download(HALEVAL_SUMMARIZATION, S.RAW / "summarization_data.json", force)
    print("FActScore (MIT) — human annotations from the paper's data release")
    zip_path = S.RAW / "factscore_data.zip"
    download(FACTSCORE_ZIP, zip_path, force)
    _extract_factscore(zip_path)


def _extract_factscore(zip_path: Path) -> None:
    import zipfile
    with zipfile.ZipFile(zip_path) as zf:
        wanted = {n: n.rsplit("/", 1)[-1] for n in zf.namelist()
                  if n.startswith("data/labeled/") and n.endswith(".jsonl")}
        missing = {n for n in ("InstructGPT.jsonl", "ChatGPT.jsonl", "PerplexityAI.jsonl")
                   if not any(v == n for v in wanted.values())}
        if missing:
            raise SystemExit(f"STOP: FActScore archive is missing {sorted(missing)}; "
                             f"found {sorted(wanted.values())}. Report this instead of guessing.")
        for member, dest_name in wanted.items():
            dest = S.RAW / dest_name
            if dest.exists() and dest.stat().st_size > 0:
                print(f"  [have] {dest_name} ({dest.stat().st_size:,} bytes)")
                continue
            dest.write_bytes(zf.read(member))
            print(f"  [unzip] {dest_name} ({dest.stat().st_size:,} bytes)")


def verify_fields(check_offline: bool = False) -> dict[str, Any]:
    """Print the first records of every file and check the expected fields are present."""
    problems: list[str] = []
    report: dict[str, Any] = {}
    for name, spec in EXPECTED.items():
        path = S.RAW / name
        if not path.is_file():
            if check_offline:
                problems.append(f"{name}: missing")
                continue
            problems.append(f"{name}: missing after download")
            continue
        head = [json.loads(line) for _, line in zip(range(2), path.open(encoding="utf-8"))
                if line.strip()] if spec["type"] == "jsonl" else []
        if not head:
            problems.append(f"{name}: no records")
            continue
        missing = [k for k in spec["keys"] if k not in head[0]]
        if missing:
            problems.append(f"{name}: missing expected field(s) {missing}; "
                            f"actual keys {sorted(head[0])}")
        found: dict[str, Any] = {"keys": sorted(head[0]), "records_checked": len(head)}
        if "label_keys" in spec:
            # Out-of-sample rows are often unlabelled, so look a little further for a labelled one.
            labelled = next((r for r in S.load_ragtruth_responses() if r.get("labels")), None)
            if labelled is None:
                problems.append(f"{name}: no labelled record found to check "
                                f"{spec['label_keys']} against")
            else:
                actual = sorted(labelled["labels"][0])
                found["label_keys"] = actual
                miss = [k for k in spec["label_keys"] if k not in actual]
                if miss:
                    problems.append(f"{name}: labels[] missing {miss}; actual {actual}")
        if "fact_keys" in spec:
            with path.open(encoding="utf-8") as fh:
                rec = next((r for r in (json.loads(x) for x in fh if x.strip())
                            if S.factscore_facts(r)), None)
            if rec is None:
                problems.append(f"{name}: no record carrying human-atomic-facts")
            else:
                fact = S.factscore_facts(rec)[0]
                found["fact_keys"] = sorted(fact)
                miss = [k for k in spec["fact_keys"] if k not in fact]
                if miss:
                    problems.append(f"{name}: human-atomic-facts[] missing {miss}; "
                                    f"actual {sorted(fact)}")
        report[name] = found
        print(f"\n--- {name}  ({found['records_checked']} record(s) printed from the head)")
        print(f"    keys: {found['keys']}")
        if "label_keys" in found:
            print(f"    labels[0] keys: {found['label_keys']}")
        if "fact_keys" in found:
            print(f"    human-atomic-facts[0] keys: {found['fact_keys']}")
        sample = json.dumps(head[0], ensure_ascii=False)
        print(f"    record[0]: {sample[:400]}{'...' if len(sample) > 400 else ''}")
    if problems:
        print("\nSTOP: upstream fields do not match the spec's T0 table:")
        for p in problems:
            print(f"  - {p}")
        sys.exit(2)
    print("\nT0 field check: all expected fields present.")
    return report


def fetch_licenses(force: bool = False) -> dict[str, Any]:
    LICENSES.mkdir(parents=True, exist_ok=True)
    out: dict[str, Any] = {}
    for name, url in LICENSE_URLS.items():
        dest = LICENSES / name
        download(url, dest, force)
        text = dest.read_text(encoding="utf-8", errors="replace")
        spdx = "MIT" if re.search(r"\bMIT\b", text[:400]) else "UNKNOWN"
        out[name] = {"url": url, "sha256": sha256(dest), "spdx": spdx}
        print(f"    {name}: {spdx}")
    return out


# --------------------------------------------------------------------------- manifest

def write_manifest(field_report: dict[str, Any], licenses: dict[str, Any]) -> dict[str, Any]:
    previous = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.is_file() else {}
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    files: dict[str, Any] = {}
    for name in ("source_info.jsonl", "response.jsonl", "summarization_data.json", "InstructGPT.jsonl",
                 "ChatGPT.jsonl", "PerplexityAI.jsonl", "factscore_data.zip"):
        path = S.RAW / name
        if not path.is_file():
            continue
        files[name] = {
            "sha256": sha256(path), "bytes": path.stat().st_size,
            "license": "MIT", "fields": field_report.get(name, {}),
        }
    files["source_info.jsonl"]["url"] = f"{RAGTRUTH_BASE}/source_info.jsonl"
    files["response.jsonl"]["url"] = f"{RAGTRUTH_BASE}/response.jsonl"
    files["summarization_data.json"]["url"] = HALEVAL_SUMMARIZATION
    for name in ("InstructGPT.jsonl", "ChatGPT.jsonl", "PerplexityAI.jsonl"):
        if name in files:
            files[name]["url"] = f"{FACTSCORE_ZIP} (data.zip -> data/labeled/{name})"
    if "factscore_data.zip" in files:
        files["factscore_data.zip"]["url"] = FACTSCORE_ZIP
    manifest = {
        "schema": 1,
        "updated_at": now,
        "created_at": previous.get("created_at", now),
        "purpose": "Snapshots for the v2 hard evaluation set (annotation pipeline T0-T7)",
        "ragtruth_upstream_split": S.RAGTRUTH_SPLIT,
        "ragtruth_upstream_split_note": (
            "Every RAGTruth case is drawn from one upstream split only (the spec's T1 rule), so a "
            "source group can never straddle it; recorded here because the choice is part of the "
            "sampling provenance."),
        "ragtruth_legacy_response_ids": sorted(S.LEGACY_RESPONSE_IDS),
        "files": files,
        "licenses": licenses,
        "wikipedia": {
            "api": "https://en.wikipedia.org/w/api.php (action=query prop=revisions, action=parse)",
            "as_of": "2023-04-01",
            "license": "CC BY-SA 4.0 - article text is used with attribution and revision id",
            "entities": previous.get("wikipedia", {}).get("entities", {}),
        },
        "notes": [
            "Raw upstream files live in data/sources/v2/raw/ and are git-ignored; only this "
            "manifest and the licence copies are committed.",
            "HaluEval's summarization_data.json is JSONL (one JSON object per line).",
            "FActScore human annotations: data/labeled/{InstructGPT,ChatGPT,PerplexityAI}.jsonl "
            "inside the paper's data.zip release.",
        ],
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nmanifest -> {S.rel(MANIFEST)}")
    return manifest


def update_manifest_wikipedia(entities: dict[str, Any]) -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["wikipedia"]["entities"].update(entities)
    manifest["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- wikipedia

WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKI_DELAY_S = 1.5  # Wikimedia asks for a modest request rate; a run fetches a few dozen pages


def _wiki(params: dict[str, str], retries: int = 5) -> dict[str, Any]:
    url = WIKI_API + "?" + urllib.parse.urlencode({**params, "format": "json", "formatversion": "2"})
    for attempt in range(retries):
        time.sleep(WIKI_DELAY_S)  # on every call, retries included: one request at a time, slowly
        try:
            return json.loads(_get(url, timeout=60.0))
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < retries - 1:
                wait = min(3 * 2 ** attempt, 30)
                print(f"    [{e.code}] rate limited, retrying in {wait}s")
                time.sleep(wait)
                continue
            raise
    raise RuntimeError("unreachable")


HEADING_MARK = "\x00"


def html_to_text(markup: str) -> str:
    """Plain text of a rendered article: prose paragraphs, one blank line between them.

    Tables (infoboxes, navboxes, filmographies, discographies), scripts, styles, figures and
    reference markers are dropped. A heading is attached to the block that follows it, and a run of
    consecutive list items becomes one paragraph: a filmography rendered as 200 one-line `<li>`s, or
    60 one-word headings, would otherwise eat the whole 50-passage budget and push the prose that a
    biography's facts come from outside the context.

    Templates are already expanded by the parse API, so no wikitext syntax survives this.
    """
    markup = re.sub(r"(?is)<(script|style|table|figure|audio|video|sup|math)\b[^>]*>.*?</\1>", " ", markup)
    markup = re.sub(r"(?s)<!--.*?-->", " ", markup)
    markup = re.sub(r"(?i)<li\b[^>]*>", "\n* ", markup)          # one list item per line
    markup = re.sub(r"(?i)</li\s*>", "", markup)
    markup = re.sub(r"(?i)<h[1-6]\b[^>]*>", "\n" + HEADING_MARK, markup)
    markup = re.sub(r"(?i)</(p|div|h[1-6]|dd|dt|blockquote|ul|ol)\s*>", "\n\n", markup)
    markup = re.sub(r"(?i)<br\s*/?>", "\n", markup)
    markup = re.sub(r"(?s)<[^>]+>", "", markup)
    text = html_mod.unescape(markup)
    text = text.replace("\u00a0", " ").replace("\u200b", "")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.split("\n")]

    blocks: list[list[str]] = []      # each block becomes one paragraph
    headings: list[str] = []          # headings waiting for the block they introduce
    for ln in lines:
        if not ln:
            continue
        if ln.startswith(HEADING_MARK):
            headings.append(ln[len(HEADING_MARK):].strip())
            continue
        is_item = ln.startswith("* ")
        if headings:                  # a heading always starts a new block
            blocks.append(["list" if is_item else "prose", [*headings, ln]])
            headings = []
        elif blocks and is_item and blocks[-1][0] == "list":
            blocks[-1][1].append(ln)
        else:
            blocks.append(["list" if is_item else "prose", [ln]])
    if headings:                      # trailing headings with no body
        blocks.append(["prose", headings])
    return "\n\n".join("\n".join(body) for _kind, body in blocks).strip()


def fetch_wikipedia(entity: str, as_of: str = "2023-04-01", refresh: bool = False) -> dict[str, Any]:
    """Revision of `entity`'s article as of (and not after) `as_of`, plus its plain text."""
    cache = S.WIKI_CACHE / f"{S.slug(entity)}.json"
    if cache.is_file() and not refresh:
        return json.loads(cache.read_text(encoding="utf-8"))
    rev = _wiki({
        "action": "query", "prop": "revisions", "titles": entity, "redirects": "1",
        "rvlimit": "1", "rvstart": f"{as_of}T23:59:59Z", "rvdir": "older",
        "rvprop": "ids|timestamp", "rvslots": "main",
    })
    pages = rev.get("query", {}).get("pages", [])
    if not pages or pages[0].get("missing") or "revisions" not in pages[0]:
        raise LookupError(f"Wikipedia has no revision of {entity!r} at or before {as_of}")
    page = pages[0]
    revision = page["revisions"][0]
    revid = revision["revid"]
    parsed = _wiki({"action": "parse", "oldid": str(revid), "prop": "text",
                    "disableeditsection": "1", "disablelimitreport": "1"})
    if "parse" not in parsed:
        raise LookupError(f"Wikipedia could not render revision {revid} of {page['title']!r}")
    record = {
        "requested_title": entity,
        "title": page["title"],
        "revid": revid,
        "timestamp": revision["timestamp"],
        "as_of": as_of,
        "text": html_to_text(parsed["parse"]["text"]),
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": f"https://en.wikipedia.org/w/index.php?oldid={revid}",
    }
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    return record


def fetch_wiki_requests(refresh: bool = False) -> None:
    if not WIKI_REQUESTS.is_file():
        print(f"no {S.rel(WIKI_REQUESTS)} - run annotation.select_cases first")
        return
    requests = json.loads(WIKI_REQUESTS.read_text(encoding="utf-8"))
    entities = requests.get("entities", [])
    print(f"Wikipedia revisions as of {requests.get('as_of')} for {len(entities)} entities")
    done: dict[str, Any] = {}
    failed: list[str] = []
    for entity in entities:
        try:
            rec = fetch_wikipedia(entity, requests.get("as_of", "2023-04-01"), refresh)
        except (LookupError, urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            failed.append(f"{entity}: {e}")
            print(f"  [FAIL] {entity}: {e}")
            continue
        done[entity] = {"revid": rec["revid"], "timestamp": rec["timestamp"], "title": rec["title"],
                        "verified": True}
        print(f"  [ok  ] {entity}: revid {rec['revid']} ({rec['timestamp']}) "
              f"{len(rec['text']):,} chars")
    if done:
        update_manifest_wikipedia(done)
    if failed:
        print(f"\n{len(failed)} entity/entities could not be fetched:")
        for f in failed:
            print(f"  - {f}")
        print("FActScore cases will be skipped for these entities (spec T0: report, then skip).")


def main() -> None:
    ap = argparse.ArgumentParser(description="T0: snapshot and verify the upstream sources")
    ap.add_argument("--check", action="store_true", help="verify fields of what is already on disk")
    ap.add_argument("--wiki", action="store_true", help="fetch the requested Wikipedia revisions")
    ap.add_argument("--refresh", action="store_true", help="re-download / re-fetch even if present")
    args = ap.parse_args()

    S.RAW.mkdir(parents=True, exist_ok=True)
    if args.wiki:
        fetch_wiki_requests(args.refresh)
        return

    licenses: dict[str, Any] = {}
    if not args.check:
        fetch_datasets(args.refresh)
        print("\nlicences")
        licenses = fetch_licenses(args.refresh)
    report = verify_fields(check_offline=args.check)
    if not args.check:
        if not licenses and MANIFEST.is_file():
            licenses = json.loads(MANIFEST.read_text(encoding="utf-8")).get("licenses", {})
        write_manifest(report, licenses)

    print("\nUpstream summary (T0 report):")
    for name, info in sorted(report.items()):
        print(f"  {name}: {info['keys']}")
    if not args.check:
        print(f"  licences: " + ", ".join(f"{k.split('-')[0]}={v['spdx']}"
                                         for k, v in sorted(licenses.items())))
        print(f"  RAGTruth upstream split used for sampling: {S.RAGTRUTH_SPLIT!r}")
    print("\nNext: uv run python -m annotation.select_cases")


if __name__ == "__main__":
    main()
