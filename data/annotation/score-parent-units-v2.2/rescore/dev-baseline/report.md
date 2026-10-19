Split: `dev`, cases: 26, oracle claims: False
Approved scoring-unit registry SHA256: `d1652fc887f500603e7b8a993a522be018b76a237654969e7e5fbeb844f00432`


| Metric | baseline |
|---|---|
| Answer-level hallucination F1 | 0.980 |
| Claim accuracy (all gold claims) | 0.382 |
| Claim accuracy (matched only) | 0.515 |
| Macro-F1 (3 verdicts) | 0.417 |
| F1 SUPPORTED | 0.551 |
| F1 CONTRADICTED | 0.368 |
| F1 UNSUPPORTED | 0.333 |
| Decomposition recall | 0.742 |
| Decomposition precision | 0.930 |
| Guard-rejected candidate pairs | 20.000 |
| Missed gold claims | 23.000 |
| Used predicted claims | 66.000 |
| Extra predicted claims | 5.000 |
| Duplicate predicted claims | 0.000 |
| Added predicted claims | 5.000 |
| Answer sentence coverage | 1.000 |
| Fused claims (claim spans >1 sentence) | 0.000 |
| Citation precision | 0.885 |
| Citation recall | 0.885 |
| Citation precision (right passage) | 1.000 |
| Citation recall (right passage) | 1.000 |
| Raw citation invalid rate (before repair) | 0.000 |
| Latency p50 (ms) | 0.144 |
| Latency p95 (ms) | 0.300 |
| LLM calls / case | 0.000 |
| Cost / case (USD) | 0.000 |
| Errored cases | 0.000 |

Grouped claim metrics: `context_length_words`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| 0-399 | baseline | 25 | 89 | 66.000 | 0.382 | 0.417 | 0.742 |

Grouped claim metrics: `difficulty`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| unknown | baseline | 25 | 89 | 66.000 | 0.382 | 0.417 | 0.742 |

Grouped claim metrics: `multi_passage`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| false | baseline | 25 | 83 | 63.000 | 0.410 | 0.443 | 0.759 |
| true | baseline | 6 | 6 | 3.000 | 0.000 | 0.000 | 0.500 |

Grouped claim metrics: `task`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| unknown | baseline | 25 | 89 | 66.000 | 0.382 | 0.417 | 0.742 |
