# v2.6 抽样统计

种子 20261022；抽样时未读取标签，未调用任何模型。

## 任务 x split x 生成模型 x 是否有幻觉

| 任务 | split | 生成模型 | 有幻觉 | 无幻觉 | 合计 |
|---|---|---|---:|---:|---:|
| Data2txt | dev | gpt-3.5-turbo-0613 | 1 | 3 | 4 |
| Data2txt | dev | llama-2-13b-chat | 3 | 0 | 3 |
| Data2txt | dev | llama-2-70b-chat | 0 | 1 | 1 |
| Data2txt | dev | llama-2-7b-chat | 1 | 0 | 1 |
| Data2txt | dev | mistral-7B-instruct | 1 | 0 | 1 |
| Data2txt | test | gpt-3.5-turbo-0613 | 2 | 6 | 8 |
| Data2txt | test | gpt-4-0613 | 1 | 9 | 10 |
| Data2txt | test | llama-2-13b-chat | 14 | 0 | 14 |
| Data2txt | test | llama-2-70b-chat | 9 | 2 | 11 |
| Data2txt | test | llama-2-7b-chat | 5 | 3 | 8 |
| Data2txt | test | mistral-7B-instruct | 9 | 0 | 9 |
| QA | dev | gpt-3.5-turbo-0613 | 0 | 1 | 1 |
| QA | dev | gpt-4-0613 | 0 | 1 | 1 |
| QA | dev | llama-2-13b-chat | 0 | 1 | 1 |
| QA | dev | llama-2-70b-chat | 0 | 2 | 2 |
| QA | dev | llama-2-7b-chat | 1 | 2 | 3 |
| QA | dev | mistral-7B-instruct | 1 | 1 | 2 |
| QA | test | gpt-3.5-turbo-0613 | 0 | 15 | 15 |
| QA | test | gpt-4-0613 | 0 | 6 | 6 |
| QA | test | llama-2-13b-chat | 1 | 3 | 4 |
| QA | test | llama-2-70b-chat | 3 | 8 | 11 |
| QA | test | llama-2-7b-chat | 3 | 9 | 12 |
| QA | test | mistral-7B-instruct | 1 | 11 | 12 |
| Summary | dev | gpt-3.5-turbo-0613 | 0 | 2 | 2 |
| Summary | dev | gpt-4-0613 | 0 | 3 | 3 |
| Summary | dev | llama-2-70b-chat | 0 | 2 | 2 |
| Summary | dev | llama-2-7b-chat | 1 | 1 | 2 |
| Summary | dev | mistral-7B-instruct | 0 | 1 | 1 |
| Summary | test | gpt-3.5-turbo-0613 | 0 | 9 | 9 |
| Summary | test | gpt-4-0613 | 0 | 10 | 10 |
| Summary | test | llama-2-13b-chat | 3 | 10 | 13 |
| Summary | test | llama-2-70b-chat | 0 | 6 | 6 |
| Summary | test | llama-2-7b-chat | 5 | 3 | 8 |
| Summary | test | mistral-7B-instruct | 6 | 8 | 14 |

## 任务 x split 合计

| 任务 | split | 案例数 | 有幻觉 |
|---|---|---:|---:|
| Summary | dev | 10 | 1 |
| Summary | test | 60 | 14 |
| QA | dev | 10 | 2 |
| QA | test | 60 | 8 |
| Data2txt | dev | 10 | 6 |
| Data2txt | test | 60 | 40 |

## 长度分布（最小 / 中位数 / 最大）

| 任务 | split | 上下文词数 | 回答词数 | 句子数 |
|---|---|---|---|---|
| Summary | dev | 191 / 339 / 985 | 28 / 86 / 175 | 1 / 5 / 10 |
| Summary | test | 154 / 368 / 1420 | 23 / 92 / 257 | 1 / 5 / 12 |
| QA | dev | 125 / 170 / 415 | 42 / 148 / 200 | 1 / 8 / 12 |
| QA | test | 121 / 208 / 401 | 7 / 106 / 235 | 1 / 5 / 18 |
| Data2txt | dev | 273 / 343 / 554 | 119 / 190 / 251 | 5 / 12 / 15 |
| Data2txt | test | 197 / 344 / 974 | 77 / 135 / 304 | 4 / 8 / 17 |

## 候选池与排除

- 合格回答 2357 条，来自 398 个 source、398 个近重复组。
- 合格回答按任务：{'Data2txt': 826, 'QA': 787, 'Summary': 744}
- 排除（回答条数，按规则顺序，先命中者计数）：
  - already_in_v2x: 300
  - answer_too_long: 6
  - legacy_project: 12
- 技术上限：上下文 <= 1626 词，回答 <= 304 词（取自 v2.5 数据实际最大值）；因超长被排除：上下文 0 条，回答 6 条。
