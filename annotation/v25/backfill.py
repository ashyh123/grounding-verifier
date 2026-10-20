"""Backfill `overlapping_source_labels` on the frozen v2.4 dataset without model calls.

    uv run python -m annotation.v25.backfill
    uv run python -m annotation.v25.backfill --check

The output is an intermediate v2.5 artifact, not the final dataset. Labels are never changed:
a claim whose verdict does not replay from its overlaps stops the run.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from annotation import sources as S
from . import overlaps

OUT = S.ANNOTATION_DIR / 'v2.5'
DEFAULT_DATA = S.ROOT / 'data' / 'eval_hard.v2.4.jsonl'
DEFAULT_OUT = OUT / 'v24_with_overlaps.jsonl'
DEFAULT_REPORT = OUT / 'overlap_report.json'


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--data', type=Path, default=DEFAULT_DATA)
    ap.add_argument('--out', type=Path, default=DEFAULT_OUT)
    ap.add_argument('--report', type=Path, default=DEFAULT_REPORT)
    ap.add_argument('--check', action='store_true', help='verify existing output; write nothing')
    args = ap.parse_args()

    if args.check:
        rows = overlaps.read_jsonl(args.out)
        errors = [error for case in rows for error in overlaps.verify_case(case)]
        if errors:
            raise SystemExit('STOP: overlap replay failed:\n' + '\n'.join(errors[:20]))
        saved = json.loads(args.report.read_text(encoding='utf-8'))
        if saved['output_sha256'] != overlaps.digest(args.out):
            raise SystemExit('STOP: output hash differs from report')
        print(json.dumps({'checked': len(rows), 'errors': 0,
                          'sha256': saved['output_sha256']}, ensure_ascii=False, indent=2))
        return

    if args.out.exists() or args.report.exists():
        raise SystemExit('STOP: v2.5 overlap outputs exist; archive before rerunning')
    source = overlaps.read_jsonl(args.data)
    rows, errors = [], []
    for case in source:
        updated, case_errors = overlaps.backfill_case(case)
        rows.append(updated)
        errors.extend(case_errors)
    if errors:
        raise SystemExit('STOP: verdict cannot be replayed from overlaps:\n'
                         + '\n'.join(errors[:20]))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    overlaps.write_new(args.out, rows)
    summary = overlaps.report(rows, args.data, args.out)
    args.report.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n',
                           encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
