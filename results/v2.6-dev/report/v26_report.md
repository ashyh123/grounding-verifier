# v2.6 response-level report (30 cases, 9 gold-positive)
- prediction rule: predicted hallucinated iff the verifier output has at least one CONTRADICTED or UNSUPPORTED claim
- failures: main result: a failed case is always wrong (gold positive -> missed, gold negative -> false alarm); `excluding_failures` drops failed cases (paired comparisons then use the cases both methods completed)
- wording: "A is better than B" may be written only if the 95% interval of the paired difference excludes 0; otherwise write "no evidence of a difference" and give the interval. Never write "equally good".

| method | failures | precision | recall | F1 [95% CI] | balanced acc | sentence F1 | localized | valid citations | raw citations | cost/case |
|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|
| baseline | 0 | 0.310 | 1.000 | 0.474 [0.250, 0.651] | 0.524 | 0.149 | 1.00 | 1.000 | 1.000 | $0.0000 |
| minimal | 0 | 0.600 | 1.000 | 0.750 [0.500, 0.917] | 0.857 | 0.531 | 0.98 | 1.000 | 0.966 | $0.0053 |
| optimized | 0 | 0.360 | 1.000 | 0.529 [0.303, 0.714] | 0.619 | 0.308 | 0.98 | 1.000 | 0.973 | $0.0376 |

- [main] F1: minimal is better than optimized (paired difference optimized minus minimal -0.221, 95% CI [-0.371, -0.106])
- [main] F1: minimal is better than baseline (paired difference minimal minus baseline +0.276, 95% CI [+0.154, +0.426])
- [main] F1: no evidence of a difference between optimized and baseline (paired difference optimized minus baseline +0.056, 95% CI [+0.000, +0.127])
- [excluding_failures] F1: minimal is better than optimized (paired difference optimized minus minimal -0.221, 95% CI [-0.371, -0.106])
- [excluding_failures] F1: minimal is better than baseline (paired difference minimal minus baseline +0.276, 95% CI [+0.154, +0.426])
- [excluding_failures] F1: no evidence of a difference between optimized and baseline (paired difference optimized minus baseline +0.056, 95% CI [+0.000, +0.127])
