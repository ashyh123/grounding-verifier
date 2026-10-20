Split: `test`, cases: 20, oracle claims: True
Approved scoring-unit registry SHA256: `3d630ebe43a0471a25527995b6a69a33bcad150f3ef653162c6d82a532824f5b`


| Metric | baseline | minimal | optimized |
|---|---|---|---|
| Answer-level hallucination F1 | 0.741 | 1.000 ± 0.000 | 1.000 ± 0.000 |
| Claim accuracy (all gold claims) | 0.705 | 0.978 ± 0.008 | 1.000 ± 0.000 |
| Claim accuracy (matched only) | 0.705 | 0.978 ± 0.008 | 1.000 ± 0.000 |
| Macro-F1 (3 verdicts) | 0.569 | 0.969 ± 0.020 | 1.000 ± 0.000 |
| F1 SUPPORTED | 0.829 | 0.988 ± 0.000 | 1.000 ± 0.000 |
| F1 CONTRADICTED | 0.333 | 0.948 ± 0.017 | 1.000 ± 0.000 |
| F1 UNSUPPORTED | 0.545 | 0.970 ± 0.043 | 1.000 ± 0.000 |
| Decomposition recall | 1.000 | 1.000 ± 0.000 | 1.000 ± 0.000 |
| Decomposition precision | 1.000 | 1.000 ± 0.000 | 1.000 ± 0.000 |
| Guard-rejected candidate pairs | 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 |
| Missed gold claims | 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 |
| Used predicted claims | 61.000 | 61.000 ± 0.000 | 61.000 ± 0.000 |
| Extra predicted claims | 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 |
| Duplicate predicted claims | 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 |
| Added predicted claims | 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 |
| Answer sentence coverage | 0.980 | 0.980 ± 0.000 | 0.980 ± 0.000 |
| Fused claims (claim spans >1 sentence) | 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 |
| Citation precision | 1.000 | 0.994 ± 0.009 | 0.932 ± 0.000 |
| Citation recall | 1.000 | 0.982 ± 0.000 | 0.982 ± 0.000 |
| Scored citations | 37.000 | 54.333 ± 0.471 | 59.000 ± 0.000 |
| Gold evidence spans | 37.000 | 56.000 ± 0.000 | 57.000 ± 0.000 |
| Invalid scored citations | 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 |
| Citation precision (right passage) | 1.000 | 0.994 ± 0.009 | 1.000 ± 0.000 |
| Citation recall (right passage) | 1.000 | 0.982 ± 0.000 | 0.982 ± 0.000 |
| Raw citation invalid rate (before repair) | 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 |
| Latency p50 (ms) | 0.146 | 3443.443 ± 74.742 | 2769.058 ± 166.010 |
| Latency p95 (ms) | 0.198 | 4417.513 ± 444.308 | 4715.773 ± 253.344 |
| LLM calls / case | 0.000 | 1.000 ± 0.000 | 2.950 ± 0.000 |
| Cost / case (USD) | 0.000 | 0.002 ± 0.000 | 0.005 ± 0.000 |
| Errored cases | 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 |

Grouped claim metrics: `context_length_words`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| 0-399 | baseline | 20 | 61 | 61.000 | 0.705 | 0.569 | 1.000 |
| 0-399 | minimal | 20 | 61 | 61.000 ± 0.000 | 0.978 ± 0.008 | 0.969 ± 0.020 | 1.000 ± 0.000 |
| 0-399 | optimized | 20 | 61 | 61.000 ± 0.000 | 1.000 ± 0.000 | 1.000 ± 0.000 | 1.000 ± 0.000 |

Grouped claim metrics: `difficulty`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| unknown | baseline | 20 | 61 | 61.000 | 0.705 | 0.569 | 1.000 |
| unknown | minimal | 20 | 61 | 61.000 ± 0.000 | 0.978 ± 0.008 | 0.969 ± 0.020 | 1.000 ± 0.000 |
| unknown | optimized | 20 | 61 | 61.000 ± 0.000 | 1.000 ± 0.000 | 1.000 ± 0.000 | 1.000 ± 0.000 |

Grouped claim metrics: `multi_passage`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| false | baseline | 20 | 57 | 57.000 | 0.702 | 0.577 | 1.000 |
| true | baseline | 4 | 4 | 4.000 | 0.750 | 0.286 | 1.000 |
| false | minimal | 20 | 57 | 57.000 ± 0.000 | 0.977 ± 0.008 | 0.968 ± 0.020 | 1.000 ± 0.000 |
| true | minimal | 4 | 4 | 4.000 ± 0.000 | 1.000 ± 0.000 | 0.333 ± 0.000 | 1.000 ± 0.000 |
| false | optimized | 20 | 57 | 57.000 ± 0.000 | 1.000 ± 0.000 | 1.000 ± 0.000 | 1.000 ± 0.000 |
| true | optimized | 4 | 4 | 4.000 ± 0.000 | 1.000 ± 0.000 | 0.333 ± 0.000 | 1.000 ± 0.000 |

Grouped claim metrics: `task`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| unknown | baseline | 20 | 61 | 61.000 | 0.705 | 0.569 | 1.000 |
| unknown | minimal | 20 | 61 | 61.000 ± 0.000 | 0.978 ± 0.008 | 0.969 ± 0.020 | 1.000 ± 0.000 |
| unknown | optimized | 20 | 61 | 61.000 ± 0.000 | 1.000 ± 0.000 | 1.000 ± 0.000 | 1.000 ± 0.000 |
