Split: `dev`, cases: 26, oracle claims: False
Approved scoring-unit registry SHA256: `d1652fc887f500603e7b8a993a522be018b76a237654969e7e5fbeb844f00432`


| Metric | optimized |
|---|---|
| Answer-level hallucination F1 | 1.000 |
| Claim accuracy (all gold claims) | 0.955 |
| Claim accuracy (matched only) | 0.977 |
| Macro-F1 (3 verdicts) | 0.951 |
| F1 SUPPORTED | 0.968 |
| F1 CONTRADICTED | 0.984 |
| F1 UNSUPPORTED | 0.900 |
| Decomposition recall | 0.978 |
| Decomposition precision | 0.916 |
| Guard-rejected candidate pairs | 25.000 |
| Missed gold claims | 2.000 |
| Used predicted claims | 87.000 |
| Extra predicted claims | 8.000 |
| Duplicate predicted claims | 6.000 |
| Added predicted claims | 2.000 |
| Answer sentence coverage | 0.972 |
| Fused claims (claim spans >1 sentence) | 0.042 |
| Citation precision | 0.897 |
| Citation recall | 0.962 |
| Citation precision (right passage) | 0.966 |
| Citation recall (right passage) | 1.000 |
| Raw citation invalid rate (before repair) | 0.000 |
| Latency p50 (ms) | 5154 |
| Latency p95 (ms) | 7295 |
| LLM calls / case | 4.577 |
| Cost / case (USD) | 0.009 |
| Errored cases | 0.000 |

Grouped claim metrics: `context_length_words`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| 0-399 | optimized | 25 | 89 | 87.000 | 0.955 | 0.951 | 0.978 |

Grouped claim metrics: `difficulty`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| unknown | optimized | 25 | 89 | 87.000 | 0.955 | 0.951 | 0.978 |

Grouped claim metrics: `multi_passage`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| false | optimized | 25 | 83 | 81.000 | 0.964 | 0.969 | 0.976 |
| true | optimized | 6 | 6 | 6.000 | 0.833 | 0.630 | 1.000 |

Grouped claim metrics: `task`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| unknown | optimized | 25 | 89 | 87.000 | 0.955 | 0.951 | 0.978 |
