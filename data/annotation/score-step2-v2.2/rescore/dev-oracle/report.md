Split: `dev`, cases: 26, oracle claims: True

| Metric | baseline | minimal | optimized |
|---|---|---|---|
| Answer-level hallucination F1 | 0.980 | 1.000 | 1.000 |
| Claim accuracy (all gold claims) | 0.494 | 1.000 | 1.000 |
| Claim accuracy (matched only) | 0.494 | 1.000 | 1.000 |
| Macro-F1 (3 verdicts) | 0.454 | 1.000 | 1.000 |
| F1 SUPPORTED | 0.683 | 1.000 | 1.000 |
| F1 CONTRADICTED | 0.368 | 1.000 | 1.000 |
| F1 UNSUPPORTED | 0.310 | 1.000 | 1.000 |
| Decomposition recall | 1.000 | 1.000 | 1.000 |
| Decomposition precision | 1.000 | 1.000 | 1.000 |
| Guard-rejected candidate pairs | 0.000 | 0.000 | 0.000 |
| Missed gold claims | 0.000 | 0.000 | 0.000 |
| Extra predicted claims | 0.000 | 0.000 | 0.000 |
| Duplicate predicted claims | 0.000 | 0.000 | 0.000 |
| Added predicted claims | 0.000 | 0.000 | 0.000 |
| Answer sentence coverage | 0.972 | 0.972 | 0.972 |
| Fused claims (claim spans >1 sentence) | 0.045 | 0.045 | 0.045 |
| Citation precision | 0.943 | 0.953 | 0.871 |
| Citation recall | 0.943 | 1.000 | 0.975 |
| Citation precision (right passage) | 1.000 | 0.965 | 0.946 |
| Citation recall (right passage) | 1.000 | 1.000 | 1.000 |
| Raw citation invalid rate (before repair) | 0.000 | 0.000 | 0.011 |
| Latency p50 (ms) | 0.187 | 3966 | 2747 |
| Latency p95 (ms) | 0.479 | 6176 | 3807 |
| LLM calls / case | 0.000 | 1.000 | 3.346 |
| Cost / case (USD) | 0.000 | 0.002 | 0.006 |
| Errored cases | 0.000 | 0.000 | 0.000 |

Grouped claim metrics: `context_length_words`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| 0-399 | baseline | 25 | 89 | 89.000 | 0.494 | 0.454 | 1.000 |
| 0-399 | minimal | 25 | 89 | 89.000 | 1.000 | 1.000 | 1.000 |
| 0-399 | optimized | 25 | 89 | 89.000 | 1.000 | 1.000 | 1.000 |

Grouped claim metrics: `difficulty`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| unknown | baseline | 25 | 89 | 89.000 | 0.494 | 0.454 | 1.000 |
| unknown | minimal | 25 | 89 | 89.000 | 1.000 | 1.000 | 1.000 |
| unknown | optimized | 25 | 89 | 89.000 | 1.000 | 1.000 | 1.000 |

Grouped claim metrics: `multi_passage`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| false | baseline | 25 | 83 | 83.000 | 0.518 | 0.476 | 1.000 |
| true | baseline | 6 | 6 | 6.000 | 0.167 | 0.111 | 1.000 |
| false | minimal | 25 | 83 | 83.000 | 1.000 | 1.000 | 1.000 |
| true | minimal | 6 | 6 | 6.000 | 1.000 | 0.667 | 1.000 |
| false | optimized | 25 | 83 | 83.000 | 1.000 | 1.000 | 1.000 |
| true | optimized | 6 | 6 | 6.000 | 1.000 | 0.667 | 1.000 |

Grouped claim metrics: `task`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| unknown | baseline | 25 | 89 | 89.000 | 0.494 | 0.454 | 1.000 |
| unknown | minimal | 25 | 89 | 89.000 | 1.000 | 1.000 | 1.000 |
| unknown | optimized | 25 | 89 | 89.000 | 1.000 | 1.000 | 1.000 |
