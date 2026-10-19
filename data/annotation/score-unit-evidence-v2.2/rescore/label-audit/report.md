Split: `all`, cases: 46, oracle claims: True
Approved scoring-unit registry SHA256: `3d630ebe43a0471a25527995b6a69a33bcad150f3ef653162c6d82a532824f5b`


| Metric | minimal | optimized |
|---|---|---|
| Answer-level hallucination F1 | 1.000 | 1.000 |
| Claim accuracy (all gold claims) | 0.980 | 0.993 |
| Claim accuracy (matched only) | 0.980 | 0.993 |
| Macro-F1 (3 verdicts) | 0.974 | 0.994 |
| F1 SUPPORTED | 0.989 | 0.995 |
| F1 CONTRADICTED | 0.965 | 0.988 |
| F1 UNSUPPORTED | 0.968 | 1.000 |
| Decomposition recall | 1.000 | 1.000 |
| Decomposition precision | 1.000 | 1.000 |
| Guard-rejected candidate pairs | 0.000 | 0.000 |
| Missed gold claims | 0.000 | 0.000 |
| Used predicted claims | 150 | 150 |
| Extra predicted claims | 0.000 | 0.000 |
| Duplicate predicted claims | 0.000 | 0.000 |
| Added predicted claims | 0.000 | 0.000 |
| Answer sentence coverage | 0.975 | 0.975 |
| Fused claims (claim spans >1 sentence) | 0.027 | 0.027 |
| Citation precision | 0.971 | 0.894 |
| Citation recall | 0.993 | 0.978 |
| Scored citations | 138 | 151 |
| Gold evidence spans | 136 | 137 |
| Invalid scored citations | 0.000 | 0.000 |
| Citation precision (right passage) | 0.978 | 0.960 |
| Citation recall (right passage) | 0.993 | 0.993 |
| Raw citation invalid rate (before repair) | 0.000 | 0.007 |
| Latency p50 (ms) | 3769 | 2876 |
| Latency p95 (ms) | 5471 | 4414 |
| LLM calls / case | 1.000 | 3.174 |
| Cost / case (USD) | 0.002 | 0.006 |
| Errored cases | 0.000 | 0.000 |

Grouped claim metrics: `context_length_words`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| 0-399 | minimal | 45 | 150 | 150 | 0.980 | 0.974 | 1.000 |
| 0-399 | optimized | 45 | 150 | 150 | 0.993 | 0.994 | 1.000 |

Grouped claim metrics: `difficulty`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| unknown | minimal | 45 | 150 | 150 | 0.980 | 0.974 | 1.000 |
| unknown | optimized | 45 | 150 | 150 | 0.993 | 0.994 | 1.000 |

Grouped claim metrics: `multi_passage`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| false | minimal | 45 | 140 | 140 | 0.986 | 0.979 | 1.000 |
| true | minimal | 10 | 10 | 10.000 | 0.900 | 0.316 | 1.000 |
| false | optimized | 45 | 140 | 140 | 0.993 | 0.994 | 1.000 |
| true | optimized | 10 | 10 | 10.000 | 1.000 | 0.667 | 1.000 |

Grouped claim metrics: `task`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| unknown | minimal | 45 | 150 | 150 | 0.980 | 0.974 | 1.000 |
| unknown | optimized | 45 | 150 | 150 | 0.993 | 0.994 | 1.000 |
