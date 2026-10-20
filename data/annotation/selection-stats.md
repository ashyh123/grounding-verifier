# v2.2 抽样统计（2026-10-19）

仅 RAGTruth：30 例，10 dev / 20 test；GPT 21/30（70%）。

| 任务 | split | 标签层 | 生成模型 | 案例数 |
|---|---|---|---|---:|
| Data2txt | dev | subtle | gpt-3.5-turbo-0613 | 1 |
| Data2txt | test | subtle | gpt-3.5-turbo-0613 | 2 |
| Data2txt | test | subtle | gpt-4-0613 | 1 |
| QA | dev | evident_only | gpt-3.5-turbo-0613 | 2 |
| QA | dev | subtle | llama-2-70b-chat | 1 |
| QA | test | subtle | gpt-3.5-turbo-0613 | 2 |
| QA | test | subtle | llama-2-70b-chat | 2 |
| QA | test | subtle | mistral-7B-instruct | 1 |
| Summary | dev | clean | gpt-3.5-turbo-0613 | 1 |
| Summary | dev | clean | gpt-4-0613 | 1 |
| Summary | dev | evident_only | gpt-4-0613 | 1 |
| Summary | dev | subtle | gpt-4-0613 | 1 |
| Summary | dev | subtle | mistral-7B-instruct | 2 |
| Summary | test | clean | gpt-3.5-turbo-0613 | 3 |
| Summary | test | clean | gpt-4-0613 | 2 |
| Summary | test | evident_only | gpt-3.5-turbo-0613 | 1 |
| Summary | test | evident_only | gpt-4-0613 | 3 |
| Summary | test | evident_only | mistral-7B-instruct | 1 |
| Summary | test | subtle | mistral-7B-instruct | 2 |

标签层：dev subtle/evident_only/clean = 5/3/2；test = 10/5/5。
test 的 5 个 clean 案例目前仅为上游 clean，仍待人工确认。
近重复：小写词 5-gram Jaccard ≥ 0.8 的连通组仅选一条回答；排除旧数据重合组。
回答逐字保留；每段精确切片及去掉的结构标记和空白均记录在 passage_map。
无起草、盲审或翻译调用；未生成金标，未运行 hard test。
候选 SHA256：`98ef2859a199bf814cbbed23365ab267de96616ce2f976e349eacc08a48f57ca`。
