# v2.6 response-level report (180 cases, 62 gold-positive)
- prediction rule: predicted hallucinated iff the verifier output has at least one CONTRADICTED or UNSUPPORTED claim
- failures: main result: a failed case is always wrong (gold positive -> missed, gold negative -> false alarm); `excluding_failures` drops failed cases (paired comparisons then use the cases both methods completed)
- wording: "A is better than B" may be written only if the 95% interval of the paired difference excludes 0; otherwise write "no evidence of a difference" and give the interval. Never write "equally good".

| method | failures | precision | recall | F1 [95% CI] | balanced acc | sentence F1 | localized | valid citations | raw citations | cost/case |
|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|
| baseline | 0 | 0.352 | 1.000 | 0.521 [0.442, 0.594] | 0.517 | 0.164 | 1.00 | 1.000 | 1.000 | $0.0000 |
| minimal | 0 | 0.578 | 0.952 | 0.720 [0.638, 0.791] | 0.794 | 0.498 | 0.98 | 1.000 | 0.953 | $0.0052 |
| optimized | 1 | 0.444 | 0.968 | 0.609 [0.524, 0.685] | 0.666 | 0.338 | 0.99 | 1.000 | 0.962 | $0.0342 |

- [main] F1: minimal is better than optimized (paired difference optimized minus minimal -0.110, 95% CI [-0.163, -0.060])
- [main] F1: minimal is better than baseline (paired difference minimal minus baseline +0.199, 95% CI [+0.144, +0.256])
- [main] F1: optimized is better than baseline (paired difference optimized minus baseline +0.088, 95% CI [+0.051, +0.126])
- [excluding_failures] F1: minimal is better than optimized (paired difference optimized minus minimal -0.104, 95% CI [-0.156, -0.054])
- [excluding_failures] F1: minimal is better than baseline (paired difference minimal minus baseline +0.199, 95% CI [+0.144, +0.256])
- [excluding_failures] F1: optimized is better than baseline (paired difference optimized minus baseline +0.095, 95% CI [+0.061, +0.132])
