from verifier.align import align_claims
from verifier.schemas import Verdict
from verifier.segment import render_numbered, split_passage
from verifier.validate import (DraftClaim, EnforceStats, RawCitation, check_response_invariants,
                               finalize_claim, find_span, resolve_all, resolve_citation)

P = [
    "Beginning with version 3.7.0, Write-Ahead Log (WAL) mode is available. Advantages include "
    "significantly faster performance in most scenarios and increased concurrency: readers do not "
    "block writers and writers do not block readers. However, WAL does not work over a network "
    "filesystem because it requires all processes to share a small amount of memory via shared "
    "memory files (-shm).",
    "When in active use, the state of a WAL mode database is described by three separate files: "
    "the main database file 'X', the write-ahead log file 'X-wal', and the wal-index shared-memory "
    "file 'X-shm'. Automatic checkpointing occurs by default when the WAL passes approximately "
    "1000 pages.",
]


def test_split_keeps_offsets_and_versions():
    s = split_passage(P[0], 0)
    assert len(s) == 3
    assert s[0].text.startswith("Beginning with version 3.7.0,")
    for x in s:
        assert P[0][x.start:x.end] == x.text
    assert "[P1.S1] Automatic checkpointing" in render_numbered(P)


def test_abbreviation_not_split():
    s = split_passage("Use a pragma, e.g. Journal mode. Then restart.", 0)
    assert [x.text for x in s] == ["Use a pragma, e.g. Journal mode.", "Then restart."]


def test_find_span_exact_normalized_fuzzy():
    assert find_span(P[1], "approximately 1000 pages")[2] == "exact"
    a, b, how = find_span(P[1], "the main  database file ‘X’")
    assert how == "normalized" and P[1][a:b] == "the main database file 'X'"
    a, b, how = find_span(P[0], "WAL does not work over a network file system because")
    assert how == "fuzzy" and "network" in P[0][a:b]
    assert find_span(P[0], "encrypted with AES-256") is None


def test_resolve_paths():
    r = resolve_citation(P, RawCitation(sentence_id="P1.S1"))
    assert r.how == "sentence" and r.citation.quote.startswith("Automatic checkpointing")
    r = resolve_citation(P, RawCitation(sentence_id="P1.S1", quote="approximately 1000 pages"))
    assert r.citation.quote == "approximately 1000 pages" and r.citation.index == 1
    r = resolve_citation(P, RawCitation(index=0, quote="approximately 1000 pages"))
    assert r.how == "relocated" and r.citation.index == 1
    assert resolve_citation(P, RawCitation(index=7, quote="nope nope nope")).citation is None
    assert resolve_citation(P, RawCitation(sentence_id="P9.S9")).how.startswith("invalid")


def test_finalize_invariants():
    st = EnforceStats()
    d = DraftClaim("WAL is encrypted", "SUPPORTED", "x",
                   [RawCitation(index=0, quote="AES-256 encryption at rest")])
    c = finalize_claim(d, resolve_all(P, d, st), st)
    assert c.verdict is Verdict.UNSUPPORTED and c.citations == [] and st.raw_invalid == 1
    d = DraftClaim("checkpoint at 1000 pages", "supported", "ok",
                   [RawCitation(sentence_id="P1.S1")])
    c = finalize_claim(d, resolve_all(P, d, st), st)
    assert c.verdict is Verdict.SUPPORTED and check_response_invariants(P, [c]) == []


def test_align():
    pairs = align_claims(["WAL checkpoints at about 1000 pages", "WAL is encrypted"],
                         ["WAL mode is encrypted with AES-256 by default",
                          "SQLite WAL mode automatically checkpoints at roughly 1,000 pages"])
    assert {(p, g) for p, g, _ in pairs.pairs} == {(0, 1)}
    assert pairs.guard_rejected_pairs >= 1  # AES-256 was dropped from the second claim
