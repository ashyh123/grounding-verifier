Split: `dev`, cases: 26, oracle claims: False
Approved scoring-unit registry SHA256: `3d630ebe43a0471a25527995b6a69a33bcad150f3ef653162c6d82a532824f5b`


| Metric | minimal |
|---|---|
| Answer-level hallucination F1 | 0.987 ± 0.009 |
| Claim accuracy (all gold claims) | 0.978 ± 0.009 |
| Claim accuracy (matched only) | 0.989 ± 0.009 |
| Macro-F1 (3 verdicts) | 0.979 ± 0.013 |
| F1 SUPPORTED | 0.986 ± 0.005 |
| F1 CONTRADICTED | 0.983 ± 0.014 |
| F1 UNSUPPORTED | 0.968 ± 0.022 |
| Decomposition recall | 0.989 ± 0.000 |
| Decomposition precision | 0.923 ± 0.009 |
| Guard-rejected candidate pairs | 19.000 ± 0.000 |
| Missed gold claims | 1.000 ± 0.000 |
| Used predicted claims | 88.000 ± 0.000 |
| Extra predicted claims | 7.333 ± 0.943 |
| Duplicate predicted claims | 3.000 ± 0.000 |
| Added predicted claims | 4.333 ± 0.943 |
| Answer sentence coverage | 0.981 ± 0.007 |
| Fused claims (claim spans >1 sentence) | 0.000 ± 0.000 |
| Citation precision | 0.975 ± 0.010 |
| Citation recall | 0.996 ± 0.006 |
| Scored citations | 80.667 ± 1.700 |
| Gold evidence spans | 79.000 ± 0.816 |
| Invalid scored citations | 0.000 ± 0.000 |
| Citation precision (right passage) | 0.988 ± 0.000 |
| Citation recall (right passage) | 1.000 ± 0.000 |
| Raw citation invalid rate (before repair) | 0.008 ± 0.005 |
| Latency p50 (ms) | 3644.742 ± 22.018 |
| Latency p95 (ms) | 5353.386 ± 610.427 |
| LLM calls / case | 1.000 ± 0.000 |
| Cost / case (USD) | 0.002 ± 0.000 |
| Errored cases | 0.000 ± 0.000 |

Grouped claim metrics: `context_length_words`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| 0-399 | minimal | 25 | 89 | 88.000 ± 0.000 | 0.978 ± 0.009 | 0.979 ± 0.013 | 0.989 ± 0.000 |

Grouped claim metrics: `difficulty`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| unknown | minimal | 25 | 89 | 88.000 ± 0.000 | 0.978 ± 0.009 | 0.979 ± 0.013 | 0.989 ± 0.000 |

Grouped claim metrics: `multi_passage`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| false | minimal | 25 | 83 | 82.000 ± 0.000 | 0.980 ± 0.006 | 0.982 ± 0.010 | 0.988 ± 0.000 |
| true | minimal | 6 | 6 | 6.000 ± 0.000 | 0.944 ± 0.079 | 0.545 ± 0.171 | 1.000 ± 0.000 |

Grouped claim metrics: `task`

| Group | Method | Cases | Gold claims | Matched | Accuracy (all gold) | Macro-F1 | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| unknown | minimal | 25 | 89 | 88.000 ± 0.000 | 0.978 ± 0.009 | 0.979 ± 0.013 | 0.989 ± 0.000 |
