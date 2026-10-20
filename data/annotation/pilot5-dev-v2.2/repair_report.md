# Pilot metadata repair report

- 5 dev cases and 63 claim texts/IDs retained; all 63 answer spans now match the original answer exactly.
- Two user-authorized location repairs: 13105-c12 capitalization, 9775-c18 attribution prefix.
- Seven append-only journal entries: 2 locations, 3 specific gap waivers, 1 title-prefix partial-overlap waiver, 1 pending human-review hold.
- Character-coverage gaps are shown with offsets and original text, without declaring factual omissions; the 20-character threshold is unchanged.
- Active coverage-gap flags: 0. Three gap detections remain visible as human-waived history.
- Active partial-overlap flags: 2 (2426-c10 and 9775-c19); the title-prefix flag for 15677-c4 remains visible as human-waived history.
- 9775-c19 also has a pending human-adjudication flag; it and its derived claims cannot qualify for A merely through upstream/blind agreement.
- No labels changed. In particular, c19 retains its upstream UNSUPPORTED and c12 retains its previous null upstream field; the latter was not remapped merely because its answer location was repaired.
- Original raw model outputs, answer, context, upstream labels and model provenance retained. The original draft is archived as drafts.original-mimo-pilot.jsonl with its original SHA256.
- make test: 194 passed. No real model calls, gold decisions, measured-method runs, commits or pushes.
- 247 prior protected files plus the scoring registry verified unchanged.

## Remaining manual adjudication

9775-c19 still bundles location, lively atmosphere and friendly bartenders. Upstream says the location was absent from business info, while context_passages[0] contains "city": "Santa Barbara". The city field does not decide the entire "local business" phrase or the "known for" assertions. No split, label override or gold adjudication was performed.

2426-c10 still spans an upstream-marked Trump qualifier and unmarked poll content. The qualifier must not be deleted merely to remove a flag.

## Validation and implementation scope

Offline CLI tests cover exact repairs, metadata approval/source-hash checks, original/journal protection, prohibition of label edits and human-hold waivers, specific gap exemptions, preservation of new unlocated segments, descendant review holds, and review-page flag filtering.

An initial command selected the interpreter outside the project venv and failed before creating the derived output. Running the same offline command through .venv/bin/python succeeded; no journal entry was duplicated.

Working-tree line changes relative to HEAD (including earlier uncommitted drafting work):
- annotation/draft_claims.py: +199 / -89
- annotation/review_app.py: +14 / -11
- annotation/triage.py: +26 / -1
- tests/test_annotation.py: +10 / -9
- annotation/repair_drafts.py: +126 / -0
- tests/test_drafting_cli.py: +147 / -0
- tests/test_draft_repairs.py: +169 / -0

Read/review scope: the new repair CLI and tests in full; changed diagnostics, triage and review-page sections. Unrelated existing annotation tooling was not audited in this round.
