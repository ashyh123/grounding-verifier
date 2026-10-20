Split: `dev`, cases: 26, oracle claims: False
Approved scoring-unit registry SHA256: `3d630ebe43a0471a25527995b6a69a33bcad150f3ef653162c6d82a532824f5b`


| Metric | optimized |
|---|---|
| Answer-level hallucination F1 | 1.000 ± 0.000 |
| Claim accuracy (all gold claims) | 0.970 ± 0.005 |
| Claim accuracy (matched only) | 0.992 ± 0.005 |
| Macro-F1 (3 verdicts) | 0.987 ± 0.004 |
| F1 SUPPORTED | 0.972 ± 0.005 |
| F1 CONTRADICTED | 0.989 ± 0.008 |
| F1 UNSUPPORTED | 1.000 ± 0.000 |
| Decomposition recall | 0.978 ± 0.000 |
| Decomposition precision | 0.891 ± 0.019 |
| Guard-rejected candidate pairs | 26.333 ± 0.471 |
| Missed gold claims | 2.000 ± 0.000 |
| Used predicted claims | 87.000 ± 0.000 |
| Extra predicted claims | 10.667 ± 2.055 |
| Duplicate predicted claims | 7.333 ± 1.700 |
| Added predicted claims | 3.333 ± 0.471 |
| Answer sentence coverage | 0.972 ± 0.000 |
| Fused claims (claim spans >1 sentence) | 0.041 ± 0.001 |
| Citation precision | 0.874 ± 0.017 |
| Citation recall | 0.966 ± 0.006 |
| Scored citations | 89.667 ± 2.357 |
| Gold evidence spans | 78.333 ± 0.471 |
| Invalid scored citations | 0.000 ± 0.000 |
| Citation precision (right passage) | 0.948 ± 0.009 |
| Citation recall (right passage) | 1.000 ± 0.000 |
| Raw citation invalid rate (before repair) | 0.003 ± 0.005 |
| Latency p50 (ms) | 4814.481 ± 77.669 |
| Latency p95 (ms) | 5857.632 ± 261.164 |
| LLM calls / case | 4.679 ± 0.079 |
| Cost / case (USD) | 0.008 ± 0.000 |
| Errored cases | 0.000 ± 0.000 |

Grouped claim metrics: `context_length_words`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| 0-399 | optimized | 25 | 89 | 87.000 ± 0.000 | 0.970 ± 0.005 | 0.987 ± 0.004 | 0.978 ± 0.000 |

Grouped claim metrics: `difficulty`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| unknown | optimized | 25 | 89 | 87.000 ± 0.000 | 0.970 ± 0.005 | 0.987 ± 0.004 | 0.978 ± 0.000 |

Grouped claim metrics: `multi_passage`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| false | optimized | 25 | 83 | 81.000 ± 0.000 | 0.968 ± 0.006 | 0.986 ± 0.005 | 0.976 ± 0.000 |
| true | optimized | 6 | 6 | 6.000 ± 0.000 | 1.000 ± 0.000 | 0.667 ± 0.000 | 1.000 ± 0.000 |

Grouped claim metrics: `task`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| unknown | optimized | 25 | 89 | 87.000 ± 0.000 | 0.970 ± 0.005 | 0.987 ± 0.004 | 0.978 ± 0.000 |
