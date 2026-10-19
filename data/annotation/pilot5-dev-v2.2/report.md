# Dev pilot drafting report

Only drafting was run, with mimo-v2.6-pro. These are annotation candidates, not gold labels.

| Case | Task | Claims | Claim flags | Case flags |
|---|---|---:|---|---|
| ragtruth-13105 | ragtruth_qa | 14 | {"answer_span_not_exact": 1} | claim 12, answer_gap |
| ragtruth-15677 | ragtruth_qa | 7 | {"partial_overlap": 1} | answer_gap |
| ragtruth-2426 | ragtruth_summary | 10 | {"partial_overlap": 1} | answer_gap |
| ragtruth-66 | ragtruth_summary | 11 | {} |  |
| ragtruth-9775 | ragtruth_data2txt | 21 | {"partial_overlap": 1} | answer_gap |

Total: 5 dev cases, 63 claims. Usage: {"calls": 5, "input_tokens": 7630, "output_tokens": 5810, "retries": 0}.
247 protected files unchanged. make test: 185 passed.
No blind review, translation, triage, gold merge, held-out measurement, commit or push was run.

## Unresolved answer quotes

- ragtruth-13105-c12: `the passages do not mention how to make a line graph` (0 exact occurrences in the original answer; candidate only)
