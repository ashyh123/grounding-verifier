Split: `test`, cases: 20, oracle claims: False

| Metric | baseline | minimal | optimized |
|---|---|---|---|
| Answer-level hallucination F1 | 0.889 | 1.000 ± 0.000 | 1.000 ± 0.000 |
| Claim accuracy (all gold claims) | 0.590 | 0.967 ± 0.000 | 0.967 ± 0.000 |
| Claim accuracy (matched only) | 0.735 | 0.983 ± 0.000 | 0.983 ± 0.000 |
| Macro-F1 (3 verdicts) | 0.536 | 0.979 ± 0.000 | 0.966 ± 0.000 |
| F1 SUPPORTED | 0.778 | 0.976 ± 0.000 | 0.976 ± 0.000 |
| F1 CONTRADICTED | 0.353 | 0.960 ± 0.000 | 1.000 ± 0.000 |
| F1 UNSUPPORTED | 0.476 | 1.000 ± 0.000 | 0.923 ± 0.000 |
| Decomposition recall | 0.803 | 0.984 ± 0.000 | 0.984 ± 0.000 |
| Decomposition precision | 0.961 | 0.870 ± 0.000 | 0.789 ± 0.000 |
| Guard-rejected candidate pairs | 14.000 | 13.000 ± 0.000 | 15.000 ± 0.000 |
| Missed gold claims | 12.000 | 1.000 ± 0.000 | 1.000 ± 0.000 |
| Extra predicted claims | 2.000 | 9.000 ± 0.000 | 16.000 ± 0.000 |
| Duplicate predicted claims | 0.000 | 6.000 ± 0.000 | 11.000 ± 0.000 |
| Added predicted claims | 2.000 | 3.000 ± 0.000 | 5.000 ± 0.000 |
| Answer sentence coverage | 1.000 | 1.000 ± 0.000 | 1.000 ± 0.000 |
| Fused claims (claim spans >1 sentence) | 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 |
| Citation precision | 0.968 | 0.962 ± 0.000 | 0.924 ± 0.008 |
| Citation recall | 0.968 | 0.944 ± 0.000 | 0.975 ± 0.009 |
| Citation precision (right passage) | 0.968 | 1.000 ± 0.000 | 0.982 ± 0.000 |
| Citation recall (right passage) | 0.968 | 0.981 ± 0.000 | 0.981 ± 0.000 |
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
| 0-399 | minimal | 20 | 61 | 60.000 ± 0.000 | 0.967 ± 0.000 | 0.979 ± 0.000 | 0.984 ± 0.000 |
| 0-399 | optimized | 20 | 61 | 60.000 ± 0.000 | 0.967 ± 0.000 | 0.966 ± 0.000 | 0.984 ± 0.000 |

Grouped claim metrics: `difficulty`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| unknown | baseline | 20 | 61 | 49.000 | 0.590 | 0.536 | 0.803 |
| unknown | minimal | 20 | 61 | 60.000 ± 0.000 | 0.967 ± 0.000 | 0.979 ± 0.000 | 0.984 ± 0.000 |
| unknown | optimized | 20 | 61 | 60.000 ± 0.000 | 0.967 ± 0.000 | 0.966 ± 0.000 | 0.984 ± 0.000 |

Grouped claim metrics: `multi_passage`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| false | baseline | 20 | 57 | 46.000 | 0.579 | 0.533 | 0.807 |
| true | baseline | 4 | 4 | 3.000 | 0.750 | 0.286 | 0.750 |
| false | minimal | 20 | 57 | 56.000 ± 0.000 | 0.965 ± 0.000 | 0.978 ± 0.000 | 0.982 ± 0.000 |
| true | minimal | 4 | 4 | 4.000 ± 0.000 | 1.000 ± 0.000 | 0.333 ± 0.000 | 1.000 ± 0.000 |
| false | optimized | 20 | 57 | 56.000 ± 0.000 | 0.965 ± 0.000 | 0.965 ± 0.000 | 0.982 ± 0.000 |
| true | optimized | 4 | 4 | 4.000 ± 0.000 | 1.000 ± 0.000 | 0.333 ± 0.000 | 1.000 ± 0.000 |

Grouped claim metrics: `task`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| unknown | baseline | 20 | 61 | 49.000 | 0.590 | 0.536 | 0.803 |
| unknown | minimal | 20 | 61 | 60.000 ± 0.000 | 0.967 ± 0.000 | 0.979 ± 0.000 | 0.984 ± 0.000 |
| unknown | optimized | 20 | 61 | 60.000 ± 0.000 | 0.967 ± 0.000 | 0.966 ± 0.000 | 0.984 ± 0.000 |
