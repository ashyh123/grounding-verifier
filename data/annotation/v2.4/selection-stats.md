# v2.4 矛盾样本抽样统计

种子 20261020；每例含上游 Conflict；未调用起草或证据模型。

| 任务 | split | 生成模型 | 上游 Conflict 片段数/例 | 案例数 |
|---|---|---|---:|---:|
| Data2txt | dev | gpt-3.5-turbo-0613 | 1 | 1 |
| Data2txt | dev | gpt-3.5-turbo-0613 | 2 | 1 |
| Data2txt | test | gpt-3.5-turbo-0613 | 1 | 1 |
| Data2txt | test | gpt-4-0613 | 1 | 1 |
| Data2txt | test | llama-2-70b-chat | 1 | 1 |
| Data2txt | test | llama-2-70b-chat | 2 | 1 |
| Data2txt | test | mistral-7B-instruct | 1 | 1 |
| Data2txt | test | mistral-7B-instruct | 2 | 1 |
| QA | dev | llama-2-70b-chat | 1 | 1 |
| QA | test | llama-2-70b-chat | 1 | 2 |
| QA | test | mistral-7B-instruct | 1 | 1 |
| Summary | dev | llama-2-70b-chat | 1 | 1 |
| Summary | dev | mistral-7B-instruct | 2 | 1 |
| Summary | test | llama-2-70b-chat | 1 | 2 |
| Summary | test | mistral-7B-instruct | 1 | 4 |
