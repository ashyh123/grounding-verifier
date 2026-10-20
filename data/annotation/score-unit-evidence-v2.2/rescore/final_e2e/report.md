Split: `test`, cases: 20, oracle claims: False
Approved scoring-unit registry SHA256: `3d630ebe43a0471a25527995b6a69a33bcad150f3ef653162c6d82a532824f5b`


| Metric | baseline | minimal | optimized |
|---|---|---|---|
| Answer-level hallucination F1 | 0.889 | 1.000 ± 0.000 | 1.000 ± 0.000 |
| Claim accuracy (all gold claims) | 0.590 | 0.984 ± 0.000 | 0.984 ± 0.000 |
| Claim accuracy (matched only) | 0.735 | 0.984 ± 0.000 | 0.984 ± 0.000 |
| Macro-F1 (3 verdicts) | 0.536 | 0.983 ± 0.000 | 0.970 ± 0.000 |
| F1 SUPPORTED | 0.778 | 0.988 ± 0.000 | 0.988 ± 0.000 |
| F1 CONTRADICTED | 0.353 | 0.960 ± 0.000 | 1.000 ± 0.000 |
| F1 UNSUPPORTED | 0.476 | 1.000 ± 0.000 | 0.923 ± 0.000 |
| Decomposition recall | 0.803 | 1.000 ± 0.000 | 1.000 ± 0.000 |
| Decomposition precision | 0.961 | 0.899 ± 0.000 | 0.816 ± 0.000 |
| Guard-rejected candidate pairs | 14.000 | 13.000 ± 0.000 | 15.000 ± 0.000 |
| Missed gold claims | 12.000 | 0.000 ± 0.000 | 0.000 ± 0.000 |
| Used predicted claims | 49.000 | 62.000 ± 0.000 | 62.000 ± 0.000 |
| Extra predicted claims | 2.000 | 7.000 ± 0.000 | 14.000 ± 0.000 |
| Duplicate predicted claims | 0.000 | 6.000 ± 0.000 | 11.000 ± 0.000 |
| Added predicted claims | 2.000 | 1.000 ± 0.000 | 3.000 ± 0.000 |
| Answer sentence coverage | 1.000 | 1.000 ± 0.000 | 1.000 ± 0.000 |
| Fused claims (claim spans >1 sentence) | 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 |
| Citation precision | 0.968 | 0.964 ± 0.000 | 0.927 ± 0.008 |
| Citation recall | 0.968 | 0.946 ± 0.000 | 0.976 ± 0.008 |
| Scored citations | 31.000 | 55.000 ± 0.000 | 59.000 ± 0.000 |
| Gold evidence spans | 31.000 | 56.000 ± 0.000 | 56.000 ± 0.000 |
| Invalid scored citations | 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 |
| Citation precision (right passage) | 0.968 | 1.000 ± 0.000 | 0.983 ± 0.000 |
| Citation recall (right passage) | 0.968 | 0.982 ± 0.000 | 0.982 ± 0.000 |
| Raw citation invalid rate (before repair) | 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 |
| Latency p50 (ms) | 0.150 | 3520.950 ± 174.973 | 4790.583 ± 186.363 |
| Latency p95 (ms) | 0.189 | 4648.900 ± 906.337 | 7956.147 ± 608.414 |
| LLM calls / case | 0.000 | 1.000 ± 0.000 | 4.700 ± 0.000 |
| Cost / case (USD) | 0.000 | 0.002 ± 0.000 | 0.008 ± 0.000 |
| Errored cases | 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 |

Grouped claim metrics: `context_length_words`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| 0-399 | baseline | 20 | 61 | 49.000 | 0.590 | 0.536 | 0.803 |
| 0-399 | minimal | 20 | 61 | 61.000 ± 0.000 | 0.984 ± 0.000 | 0.983 ± 0.000 | 1.000 ± 0.000 |
| 0-399 | optimized | 20 | 61 | 61.000 ± 0.000 | 0.984 ± 0.000 | 0.970 ± 0.000 | 1.000 ± 0.000 |

Grouped claim metrics: `difficulty`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| unknown | baseline | 20 | 61 | 49.000 | 0.590 | 0.536 | 0.803 |
| unknown | minimal | 20 | 61 | 61.000 ± 0.000 | 0.984 ± 0.000 | 0.983 ± 0.000 | 1.000 ± 0.000 |
| unknown | optimized | 20 | 61 | 61.000 ± 0.000 | 0.984 ± 0.000 | 0.970 ± 0.000 | 1.000 ± 0.000 |

Grouped claim metrics: `multi_passage`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| false | baseline | 20 | 57 | 46.000 | 0.579 | 0.533 | 0.807 |
| true | baseline | 4 | 4 | 3.000 | 0.750 | 0.286 | 0.750 |
| false | minimal | 20 | 57 | 57.000 ± 0.000 | 0.982 ± 0.000 | 0.982 ± 0.000 | 1.000 ± 0.000 |
| true | minimal | 4 | 4 | 4.000 ± 0.000 | 1.000 ± 0.000 | 0.333 ± 0.000 | 1.000 ± 0.000 |
| false | optimized | 20 | 57 | 57.000 ± 0.000 | 0.982 ± 0.000 | 0.970 ± 0.000 | 1.000 ± 0.000 |
| true | optimized | 4 | 4 | 4.000 ± 0.000 | 1.000 ± 0.000 | 0.333 ± 0.000 | 1.000 ± 0.000 |

Grouped claim metrics: `task`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| unknown | baseline | 20 | 61 | 49.000 | 0.590 | 0.536 | 0.803 |
| unknown | minimal | 20 | 61 | 61.000 ± 0.000 | 0.984 ± 0.000 | 0.983 ± 0.000 | 1.000 ± 0.000 |
| unknown | optimized | 20 | 61 | 61.000 ± 0.000 | 0.984 ± 0.000 | 0.970 ± 0.000 | 1.000 ± 0.000 |
