Split: `dev`, cases: 26, oracle claims: False

| Metric | optimized |
|---|---|
| Answer-level hallucination F1 | 0.980 ± 0.000 |
| Claim accuracy (all gold claims) | 0.974 ± 0.005 |
| Claim accuracy (matched only) | 0.996 ± 0.005 |
| Macro-F1 (3 verdicts) | 0.986 ± 0.010 |
| F1 SUPPORTED | 0.979 ± 0.000 |
| F1 CONTRADICTED | 0.994 ± 0.008 |
| F1 UNSUPPORTED | 0.984 ± 0.022 |
| Decomposition recall | 0.978 ± 0.000 |
| Decomposition precision | 0.935 ± 0.000 |
| Guard-rejected candidate pairs | 23.000 ± 0.000 |
| Missed gold claims | 2.000 ± 0.000 |
| Extra predicted claims | 6.000 ± 0.000 |
| Duplicate predicted claims | 3.000 ± 0.000 |
| Added predicted claims | 3.000 ± 0.000 |
| Answer sentence coverage | 0.986 ± 0.000 |
| Fused claims (claim spans >1 sentence) | 0.022 ± 0.000 |
| Citation precision | 0.858 ± 0.013 |
| Citation recall | 0.962 ± 0.000 |
| Citation precision (right passage) | 0.949 ± 0.013 |
| Citation recall (right passage) | 1.000 ± 0.000 |
| Raw citation invalid rate (before repair) | 0.010 ± 0.000 |
| Latency p50 (ms) | 5749.303 ± 146.211 |
| Latency p95 (ms) | 7541.264 ± 1009.508 |
| LLM calls / case | 4.500 ± 0.000 |
| Cost / case (USD) | 0.009 ± 0.000 |
| Errored cases | 0.000 ± 0.000 |

Grouped claim metrics: `context_length_words`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| 0-399 | optimized | 25 | 89 | 87.000 ± 0.000 | 0.974 ± 0.005 | 0.986 ± 0.010 | 0.978 ± 0.000 |

Grouped claim metrics: `difficulty`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| unknown | optimized | 25 | 89 | 87.000 ± 0.000 | 0.974 ± 0.005 | 0.986 ± 0.010 | 0.978 ± 0.000 |

Grouped claim metrics: `multi_passage`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| false | optimized | 25 | 83 | 81.000 ± 0.000 | 0.972 ± 0.006 | 0.985 ± 0.010 | 0.976 ± 0.000 |
| true | optimized | 6 | 6 | 6.000 ± 0.000 | 1.000 ± 0.000 | 0.667 ± 0.000 | 1.000 ± 0.000 |

Grouped claim metrics: `task`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| unknown | optimized | 25 | 89 | 87.000 ± 0.000 | 0.974 ± 0.005 | 0.986 ± 0.010 | 0.978 ± 0.000 |
