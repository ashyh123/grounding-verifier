# v2.5 Subtle 矛盾补充抽样统计

种子 20261021；未调用起草或证据模型。

| 任务 | split | 生成模型 | 上游 split | Subtle Conflict 片段数/例 | 案例数 |
|---|---|---|---|---:|---:|
| Data2txt | dev | gpt-3.5-turbo-0613 | train | 1 | 1 |
| Data2txt | test | gpt-4-0613 | train | 1 | 1 |
| Data2txt | test | llama-2-70b-chat | train | 1 | 2 |
| QA | dev | gpt-4-0613 | train | 1 | 1 |
| QA | test | gpt-3.5-turbo-0613 | train | 1 | 2 |
| QA | test | mistral-7B-instruct | train | 1 | 1 |
| Summary | dev | gpt-4-0613 | train | 1 | 1 |
| Summary | test | gpt-4-0613 | train | 1 | 1 |
| Summary | test | mistral-7B-instruct | train | 1 | 3 |
