# v2.6 response-level report (30 cases, 9 gold-positive)
- prediction rule: predicted hallucinated iff the verifier output has at least one CONTRADICTED or UNSUPPORTED claim
- failures: main result: a failed case is always wrong (gold positive -> missed, gold negative -> false alarm); `excluding_failures` drops failed cases (paired comparisons then use the cases both methods completed)
- wording: "A is better than B" may be written only if the 95% interval of the paired difference excludes 0; otherwise write "no evidence of a difference" and give the interval. Never write "equally good".

| method | failures | precision | recall | F1 [95% CI] | balanced acc | sentence F1 | localized | valid citations | cost/case |
|---|---:|---:|---:|---|---:|---:|---:|---:|---:|
| baseline | 0 | 0.310 | 1.000 | 0.474 [0.250, 0.651] | 0.524 | 0.149 | 1.00 | 1.000 | $0.0000 |

