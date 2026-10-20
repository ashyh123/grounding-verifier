Split: `dev`, cases: 26, oracle claims: False
Approved scoring-unit registry SHA256: `d1652fc887f500603e7b8a993a522be018b76a237654969e7e5fbeb844f00432`


| Metric | minimal | optimized |
|---|---|---|
| Answer-level hallucination F1 | 0.980 | 0.980 |
| Claim accuracy (all gold claims) | 0.978 | 0.978 |
| Claim accuracy (matched only) | 0.989 | 0.989 |
| Macro-F1 (3 verdicts) | 0.975 | 0.988 |
| F1 SUPPORTED | 0.990 | 0.980 |
| F1 CONTRADICTED | 0.983 | 0.983 |
| F1 UNSUPPORTED | 0.952 | 1.000 |
| Decomposition recall | 0.989 | 0.989 |
| Decomposition precision | 0.946 | 0.889 |
| Guard-rejected candidate pairs | 19.000 | 27.000 |
| Missed gold claims | 1.000 | 1.000 |
| Used predicted claims | 88.000 | 88.000 |
| Extra predicted claims | 5.000 | 11.000 |
| Duplicate predicted claims | 3.000 | 8.000 |
| Added predicted claims | 2.000 | 3.000 |
| Answer sentence coverage | 0.986 | 0.986 |
| Fused claims (claim spans >1 sentence) | 0.000 | 0.040 |
| Citation precision | 0.963 | 0.849 |
| Citation recall | 1.000 | 0.987 |
| Citation precision (right passage) | 0.963 | 0.957 |
| Citation recall (right passage) | 1.000 | 1.000 |
| Raw citation invalid rate (before repair) | 0.000 | 0.009 |
| Latency p50 (ms) | 2071 | 3188 |
| Latency p95 (ms) | 3165 | 5532 |
| LLM calls / case | 1.000 | 4.769 |
| Cost / case (USD) | 0.002 | 0.008 |
| Errored cases | 0.000 | 0.000 |

Grouped claim metrics: `context_length_words`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| 0-399 | minimal | 25 | 89 | 88.000 | 0.978 | 0.975 | 0.989 |
| 0-399 | optimized | 25 | 89 | 88.000 | 0.978 | 0.988 | 0.989 |

Grouped claim metrics: `difficulty`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| unknown | minimal | 25 | 89 | 88.000 | 0.978 | 0.975 | 0.989 |
| unknown | optimized | 25 | 89 | 88.000 | 0.978 | 0.988 | 0.989 |

Grouped claim metrics: `multi_passage`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| false | minimal | 25 | 83 | 82.000 | 0.988 | 0.996 | 0.988 |
| true | minimal | 6 | 6 | 6.000 | 0.833 | 0.333 | 1.000 |
| false | optimized | 25 | 83 | 82.000 | 0.976 | 0.987 | 0.988 |
| true | optimized | 6 | 6 | 6.000 | 1.000 | 0.667 | 1.000 |

Grouped claim metrics: `task`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| unknown | minimal | 25 | 89 | 88.000 | 0.978 | 0.975 | 0.989 |
| unknown | optimized | 25 | 89 | 88.000 | 0.978 | 0.988 | 0.989 |
