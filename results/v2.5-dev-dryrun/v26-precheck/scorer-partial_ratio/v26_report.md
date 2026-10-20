# v2.6 response-level report (18 cases, 16 gold-positive)
- prediction rule: predicted hallucinated iff the verifier output has at least one CONTRADICTED or UNSUPPORTED claim
- failures: main result: a failed case is always wrong (gold positive -> missed, gold negative -> false alarm); `excluding_failures` drops failed cases (paired comparisons then use the cases both methods completed)
- wording: "A is better than B" may be written only if the 95% interval of the paired difference excludes 0; otherwise write "no evidence of a difference" and give the interval. Never write "equally good".

| method | failures | precision | recall | F1 [95% CI] | balanced acc | sentence F1 | localized | valid citations | cost/case |
|---|---:|---:|---:|---|---:|---:|---:|---:|---:|
| baseline | 0 | 0.889 | 1.000 | 0.941 [0.839, 1.000] | 0.500 | 0.297 | 1.00 | 1.000 | $0.0000 |
| minimal | 0 | 1.000 | 0.750 | 0.857 [0.692, 0.970] | 0.875 | 0.609 | 1.00 | 1.000 | $0.0062 |
| optimized | 5 | 0.800 | 0.500 | 0.615 [0.364, 0.800] | 0.250 | 0.500 | 1.00 | 1.000 | $0.0249 |

- [main] F1: minimal is better than optimized (paired difference optimized minus minimal -0.242, 95% CI [-0.462, -0.080])
- [main] F1: no evidence of a difference between minimal and baseline (paired difference minimal minus baseline -0.084, 95% CI [-0.275, +0.078])
- [main] F1: baseline is better than optimized (paired difference optimized minus baseline -0.326, 95% CI [-0.578, -0.141])
- [excluding_failures] F1: no evidence of a difference between optimized and minimal (paired difference optimized minus minimal -0.080, 95% CI [-0.226, +0.000])
- [excluding_failures] F1: no evidence of a difference between minimal and baseline (paired difference minimal minus baseline -0.084, 95% CI [-0.275, +0.078])
- [excluding_failures] F1: no evidence of a difference between optimized and baseline (paired difference optimized minus baseline -0.155, 95% CI [-0.361, +0.000])
