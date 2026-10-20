Split: `dev`, cases: 26, oracle claims: False
Approved scoring-unit registry SHA256: `d1652fc887f500603e7b8a993a522be018b76a237654969e7e5fbeb844f00432`


| Metric | optimized |
|---|---|
| Answer-level hallucination F1 | 1.000 |
| Claim accuracy (all gold claims) | 0.989 |
| Claim accuracy (matched only) | 1.000 |
| Macro-F1 (3 verdicts) | 0.997 |
| F1 SUPPORTED | 0.990 |
| F1 CONTRADICTED | 1.000 |
| F1 UNSUPPORTED | 1.000 |
| Decomposition recall | 0.989 |
| Decomposition precision | 0.936 |
| Guard-rejected candidate pairs | 24.000 |
| Missed gold claims | 1.000 |
| Used predicted claims | 88.000 |
| Extra predicted claims | 6.000 |
| Duplicate predicted claims | 5.000 |
| Added predicted claims | 1.000 |
| Answer sentence coverage | 0.972 |
| Fused claims (claim spans >1 sentence) | 0.043 |
| Citation precision | 0.860 |
| Citation recall | 0.963 |
| Citation precision (right passage) | 0.957 |
| Citation recall (right passage) | 1.000 |
| Raw citation invalid rate (before repair) | 0.000 |
| Latency p50 (ms) | 5227 |
| Latency p95 (ms) | 8746 |
| LLM calls / case | 4.538 |
| Cost / case (USD) | 0.008 |
| Errored cases | 0.000 |

Grouped claim metrics: `context_length_words`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| 0-399 | optimized | 25 | 89 | 88.000 | 0.989 | 0.997 | 0.989 |

Grouped claim metrics: `difficulty`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| unknown | optimized | 25 | 89 | 88.000 | 0.989 | 0.997 | 0.989 |

Grouped claim metrics: `multi_passage`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| false | optimized | 25 | 83 | 82.000 | 0.988 | 0.996 | 0.988 |
| true | optimized | 6 | 6 | 6.000 | 1.000 | 0.667 | 1.000 |

Grouped claim metrics: `task`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| unknown | optimized | 25 | 89 | 88.000 | 0.989 | 0.997 | 0.989 |
