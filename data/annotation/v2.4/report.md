# v2.4 第 1–4 节汇报（2026-10-20）

依据 [Notion v2.4](https://app.notion.com/p/3fe7b21c658881c79ac2f508e5917120)，当前停在第 4 节「⏸ 汇报」，未对新增 20 例调用起草/证据模型，未进入指标登记与最终合并冻结。

## 1. 工作区归档与事前登记

旧 v2.2 工具、测试、score/pilot 目录、中断中间文件以及剩余旧来源元数据/许可证共 212 个文件已按指令提交存档：`35f50f7`。归档提交后 git status 干净；没有提交 .env、key 或完整原始上游数据。

初始抽样规则在任何本轮模型调用前提交为 `a805da8`。固定任务配额下可用 GPT 来源上界为 9/20，不可能满足 70%；原规则与诊断已存档。用户明确选择「取消新增集 GPT 下限（推荐）」，修订规则在调用前提交为 `ddae187`，只取消 conflict_supplement 的 GPT 比例下限，其余配额、长度、Conflict、来源隔离、近重复和种子保持不变。

## 2. 原 30 例证据修复

离线重放原输出：在原 98 条无精确证据的 S/C 中恢复 86 条，修正 119 条引文的 index。目标段内未命中时，只有在其他段全局恰好出现一次的逐字引文才会改段号；重复出现和非原文引文仍拒收，原始模型输出保留。

新 prompt 显式编号每段为 [passage N]，只对原 98 条 none S/C 调用 98 次；原有精确证据的主张没有重跑。新 prompt 有 95 条找到精确证据，其中在离线修复之外额外恢复 10 条；新 prompt 的 index_corrected 引文为 0。两阶段合计现有 S/C 覆盖 336/338（99.4%），仍有 2 条无精确证据，标签不变。

| 任务 | S+C | v2.3 精确证据 | 离线修复后 | 新 prompt 合并后 | 最终覆盖率 |
|---|---:|---:|---:|---:|---:|
| ragtruth_summary | 200 | 174 | 196 | 199 | 99.5% |
| ragtruth_qa | 50 | 44 | 45 | 50 | 100.0% |
| ragtruth_data2txt | 88 | 22 | 85 | 87 | 98.9% |

本次新 prompt 疑问/找不到 11 条、协议异常 0 条；原 v2.3 疑问记录保留，当前没有把新旧日志相加当成独立主张数。新 prompt 用量：141,441 输入 token / 19,626 输出 token，非账单金额。

## 3. 被 partial_overlap 剔除的主张

原 10 个父主张已重新拆分为 19 条新主张，保留 15 条（S=9 / C=1 / U=5），4 条仍因 partial_overlap 剔除。10 个父主张均有保留子主张，但这不等于整条原复合主张全部找回。每条新 ID 带 derived_from，标签重新由原回答 span 重叠映射。

拆分输入只有原句、原文区域和切分位置，没有上游标签类型。第一轮模型把改写主张作为引文，第二轮出现结构输出错误；两次失败均存档。修正为仅提供原文及位置、复用原有 inline schema 并限制最多一个工具调用后，10 例均成功，没有触及连续三次修复仍失败的停止线。

新主张当前是待合并的中间产物：新拆分主张的证据定位、全案例覆盖与重复检查将在下一阶段与新增案例一起处理；没有改写旧金标。精确跨度和确定性标签映射不等于拆分语义已获人工复核。

## 4. 固定抽样结果

每例来自上游 test、quality=good、至少一个 Conflict；与原 30 例及旧项目来源/近重复组隔离。种子 20261020；输入池正序/逆序重跑一致。

| 任务 | dev 新增 | test 新增 |
|---|---:|---:|
| Summary | 2 | 6 |
| Data2txt | 2 | 6 |
| QA | 1 | 3 |
| 合计 | 5 | 15 |

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

实际新增 GPT 数：4/20。这个比例是用户取消下限后的固定抽样结果，没有再挑选样本。原 30 例在新中间产物标 subset=natural，新增 20 例标 subset=conflict_supplement；原始 v2.3 文件没有被修改。

## 验证、范围与下一步

`make test`：223 passed（37.25s）；git diff --check 通过。测试覆盖唯一引文跨段纠错、同段/跨段多次出现拒收、编号上下文的真实 CLI 到本地 HTTP 模型边界、仅重跑原 none S/C、固定标签不变、按原文位置拆分无标签泄漏、抽样配额/来源隔离/可复现性。

正式检查确认：98 次重跑的 ID 集合与 v2.3 原 none S/C 完全一致；旧 368 条主张的文本/标签与已有精确引文保持不变；所有新引文精确切片成立。v2.3 freeze --check 通过，原 data/eval.jsonl、data/eval_hard.jsonl、results/ 和冻结元数据哈希不变。

新流程代码在 annotation/v24/（424 行），测试 163 行；无新依赖，复用现有模型客户端、精确 span 标签映射、SciPy 配额分配和近重复算法。版本目录是保留 v2.3 冻结文件的明确要求，不是运行时兼容开关。复查范围为这三个新入口、新测试及输出检查；旧 v2.2 内容按要求原样归档，未宣称完成额外仓库审计。

待用户确认后才会：起草新增 20 例并完成其标签/证据流程，处理恢复主张的证据和整体合并检查，实施预登记的幻觉检出与 bootstrap 指标，生成 data/eval_hard.v2.4.jsonl 及新的 audit/freeze。不会覆盖 v2.3 或运行 hard test 的被测方案。
