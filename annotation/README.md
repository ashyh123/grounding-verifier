# 标注流水线（v2.5 已冻结，2026-10-20）

当前状态：**v2.4 已冻结；v2.5 已冻结**。仅在 `eval-v2` 工作，不提交到 main。

## 版本索引

| 版本 | 状态 | 数据 | 报告 / 冻结 |
|---|---|---|---|
| v2.3 | 已冻结 `c78d411` | `data/eval_hard.jsonl` | [完整报告](../data/annotation/full-v2.3/report.md)、[五例试点报告](../data/annotation/pilot5-dev-v2.3/report.md)、[冻结记录](../data/annotation/freeze.json) |
| v2.4 | 已冻结 `cbccac9` | `data/eval_hard.v2.4.jsonl` | [检查点报告](../data/annotation/v2.4/report.md)、[合并统计](../data/annotation/v2.4/final_report.md)、[冻结记录](../data/annotation/v2.4/freeze.json) |
| v2.5 | 已冻结（source commit 见 freeze） | `data/eval_hard.v2.5.jsonl` | [合并统计](../data/annotation/v2.5/final_report.md)、[审计](../data/annotation/v2.5/audit.json)、[冻结记录](../data/annotation/v2.5/freeze.json) |

v2.5 在 v2.4 的 50 例上追加 13 例 `subtle_supplement`（test 10 / dev 3，全部来自上游
train），补齐全部主张的 `overlapping_source_labels`，并对既有疑问和全部 C/U 主张做
`doubt_category` 分类与预先登记的敏感性分析。目标「test 中 Subtle Conflict 来源的 C ≥ 8」
**未达到**（保留 7 条）；未追加案例、未放宽规则。v2.4 freeze 的 README 校验已按用户授权
做最小适配；v2.4 历史提交 `cbccac9` 不变。

v2.5 初次冻结后，用户授权修复 optimized 在 DeepSeek 上的 JSON 解析失败。修复位于
`verifier/openai_client.py`；旧 freeze 存档为
`data/annotation/v2.5/freeze.pre-optimized-fix.json`，新 freeze 重新记录修复后的代码哈希。
数据集、标注和评分口径未变。

v2.5 规格来自 Notion「v2.5 修改建议」，并继续沿用
[zcode 执行指令 v2.3](https://app.notion.com/p/3fe7b21c6588813fa732c6a51e30e6f7) 与
[zcode 执行指令 v2.4](https://app.notion.com/p/3fe7b21c658881c79ac2f508e5917120) 的规则。
本轮基于 v2.4 冻结提交 `cbccac9` 新增产物，不修改 v2.3/v2.4 的冻结数据与代码。
修改只依据标签分布和标注流水线诊断；**未在 hard test 上运行任何被测方案**。

## v2.3 流程记录（历史）

v2.3 首轮仍为已抽样的 30 例（10 dev / 20 test），回答和上下文保持不变。

扩展处理已完成：30 例 / 368 条保留主张，剔除 10 条 partial_overlap，无整例剔除。
最终统计见 [完整报告](../data/annotation/full-v2.3/report.md)。合并已通过正式 schema；
`make test` 为 212 passed。冻结记录为 `data/annotation/freeze.json`；流程在本分支提交后等待测量指令。

五例 dev 试点已完成：63 条起草主张剔除 3 条，保留 60 条；精确证据 32/53 条 S/C，
模型疑问 5 条；`make test` 为 211 passed。详见
[试点报告](../data/annotation/pilot5-dev-v2.3/report.md)。用户随后已确认第 5 节扩展、合并和冻结。

已改为直接映射 RAGTruth 上游人工标签，`label_source: ragtruth_human`。
不再使用人工复核、盲审、A/B/C 分桶或翻译。相关旧工具保留，但不进入 v2.3 流程。
用户本轮确认：证据定位使用 `mimo-v2.6-pro`，沿用已有 `ANTHROPIC_API_KEY` 与 MiMo 接口；
剩余起草继续同一模型。所有标注调用拒绝 DeepSeek 模型和 endpoint。

旧流程的后台起草和复核服务已停止；已成功写出的剩余草稿在本轮复用并补齐。
本轮获授权生成 `data/eval_hard.jsonl` 并冻结、提交；不会运行 hard test 的被测方案。

## 已归档的复核材料

以下文件在 `data/annotation/` 中保留原始字节，在扩展名前增加 `.revoked-mimo-review`：
`decisions_round1.jsonl`、`pilot5_review_20261020.jsonl`、`human_confirmations.jsonl`、
`disagreements.jsonl`、`adjudication_notes.jsonl`、`adjudication_suggestions.jsonl`、
`adjudication_zh.json`。路径、SHA256、时间与原因追加到 `revocations.json`；v2.2 的归档条目保留。
原因：mimo 复核与起草使用同一模型且可见上游标签，整体确认不构成独立人工判断。

`candidates.jsonl`、`selection.json`、`drafts.jsonl`、`draft_revisions.jsonl`、
`drafts.original-mimo-pilot.jsonl` 均保持原始字节。本轮不继承旧 flags 的豁免。

## 标签映射（离线）

```bash
uv run python -m annotation.map_labels --drafts data/annotation/drafts.jsonl \
  --out-dir data/annotation/pilot5-dev-v2.3
```

脚本从原回答的精确 `answer_spans` 重新计算，与 Conflict 重叠为 CONTRADICTED，
否则与 Baseless Info 重叠为 UNSUPPORTED，否则 SUPPORTED；Conflict 优先。
主张跨度按字符集合合并，避免重叠引文重复计数。部分重叠且片段外超过 20 字符时剔除主张；
恰好 20 字符不剔除。剔除比例超过 30% 时整例剔除，恰好 30% 保留。

上游片段若不与任何起草主张的精确跨度重叠，输出 `needs_redraft`，证据入口拒绝继续。
用户授权后可加 `--redraft-uncovered`：仅允许同一起草模型重新起草一次，仍只发上下文和完整回答，
不发上游标签。新 ID 带 `redraft1`、记录 `derived_from`，完整调用记录追加到 `redrafts.jsonl`；
再次映射仍未覆盖就整例以 `source_label_uncovered` 剔除，不补抽。失败调用保留，不自动重试。
所有输出目录禁止覆盖已有映射；新一轮先改名存档。

产物：`mapped.jsonl`、`excluded.jsonl`、`mapping-report.json`。被剔除主张与整例剔除分别记录。
这些是中间产物，不是冻结金标。

## 证据定位（用户授权后调用模型）

```bash
uv run python -m annotation.find_evidence \
  --mapped data/annotation/pilot5-dev-v2.3/mapped.jsonl
```

复用已有 Anthropic 协议客户端和独立标注 key，无新依赖。
只对保留的 SUPPORTED / CONTRADICTED 主张调用模型，输入仅为上下文、主张和已定标签。
模型仅返回 `index` + `quote` 及可选疑问说明；额外 verdict 字段会被拒绝。
偏移由脚本计算，仅收精确子串；不调用模糊或规范化匹配。
无精确引文时保持标签，`evidence_status: none`；该主张参与标签准确率，不进入引用精度或召回分母。
UNSUPPORTED 无证据且不调用模型。模型表示找不到或怀疑标签时追加 `model_doubts.jsonl`，不能改标签。

每条调用写入 `evidence_calls.jsonl`，含实际返回模型、请求模型、参数、prompt SHA256、
UTC 起止时间和 token 用量；无自动重试。再次运行会检查已有 checkpoint 与当前标签、prompt、模型一致，
跳过成功记录，遇到失败记录停止。完成后写 `evidenced.jsonl`、`evidence-report.json`。
对不同案例最多并发 3 个请求，同一案例按主张顺序处理。

## 数据来源与限制

候选抽样保持原 v2.2：Summary 6/12、QA 3/5、Data2txt 1/3（dev/test），种子 20261019，
上游 test split、quality=good；来源分组及近重复隔离规则不变。
标签直接来自 RAGTruth 人工标注，未经二次人工复核，可能有上游漏标或错标。
剔除规则可能使保留集偏向较容易的样本；精确引文只证明原文存在，不证明语义充分。
跨段证据不自动等于需要跨段推理。

## 变更范围与验证

最小方案是新增脚本直接映射已有结构及定位证据，扩展现有 loader/scorer 的无证据分支。
标签来源、精确状态和调用 provenance 是规格要求；调用者只选择模型和 key，其余由脚本计算。
不新增框架、依赖、复核流程或模型投票。合并与冻结已采用 v2.3 离线校验入口。

`make test` 覆盖真实 CLI 到本地 HTTP provider 的流程及边界：部分重叠 20/21、30% 阈值、
Conflict 优先、重叠跨度去重、漏覆盖一次重起草后剔除、模型不能改标签、精确引文、找不到、
疑问记录、失败 checkpoint 不重复调用、无证据准确率及引用分母。
`data/eval.jsonl`、`results/` 与上述五份保护文件的 SHA256 在试点前后核对。

## 扩展、合并与冻结（本轮已获用户授权）

用户已确认继续使用 mimo-v2.6-pro 完成剩余 25 例、合并和冻结。复用已有的成功草稿，
仅补齐缺少的案例；输出追加到 `drafts.remaining25.jsonl`，不改五例 `drafts.jsonl`。
剩余案例的映射和证据产物位于 `data/annotation/full-v2.3/`，与试点输出分开。

```bash
uv run python -m annotation.map_labels --drafts data/annotation/drafts.remaining25.jsonl \
  --out-dir data/annotation/full-v2.3 --redraft-uncovered
uv run python -m annotation.find_evidence --mapped data/annotation/full-v2.3/mapped.jsonl
make annotate-merge
# 更新数据说明、完成 make test 后：
make annotate-freeze
```

合并入口要求所有抽样案例均被处理（被整例剔除的也必须列入输入）。它重新计算上游标签和剔除，
核对候选的完整回答、上下文、source_group 与 split，从模型原始引文重新核对证据及疑问日志，
拒绝缺失/重复案例、标签改写、未完成定位或不一致的证据检查点。输出 `data/eval_hard.jsonl`、
`data/annotation/audit.json`。旧复核合并实现存档为 `merge_review.py`，新入口不读取人工决定。

冻结入口记录合并输入、原始 RAGTruth 两份本地快照、模型参数和 prompt 哈希、数据说明、
评分代码、verifier prompts 与当前 commit。`--check` 离线重算所有哈希。
上游原文件仅在本地保留并记录 SHA256；不提交完整快照、`.env` 或 key。
冻结后提交到 `eval-v2`；hard test 测量仍须单独指令。

### 本轮发现的协议边界

MiMo Anthropic 接口的 tool_choice 只有 auto，不能保证响应一定为 tool_use。
模型完成响应但结构不符合要求时，不从自然语言猜证据，保留标签、空证据、原始响应及
`protocol_error`，作为 `model_doubts` 中明确标为 pipeline diagnostic 的记录；不自动重试。
这类诊断与模型对上游标签的真正疑问在 audit 中分开计数。
HTTP/网络失败仍停止流程，已在途请求会等其返回并记账，停止派发新请求。

首次扩展在旧版本并发取消路径下留下至多两笔未取得最终响应/usage 的请求；原始检查点、
失败记录和说明保存在 full-v2.3 的 attempt1 文件。已完成的失败响应转成无证据并保留原始记录哈希，
未重试该响应。报告 token 总量只累计可观测 usage，不能声称等于完整账单。
