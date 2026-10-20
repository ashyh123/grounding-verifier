# v2.7 S6 test 报告

**状态：两轨道按 freeze 各跑一次，三方案各 1 轮；0 失败、0 截断；optimized 在两轨道各有 1 次
重试并恢复；总费用约 $10.80，低于 $16。未重跑。**

## 轨道 A：LLM-AggreFact（oracle，主张给定）

数据：461 篇文档 / 854 条主张 / 512 正例；10 个子集；minimal 每 20 条主张一批。

| 方案 | 宏平均 BAcc | 95% CI | 失败文档 | 费用 |
|---|---:|---|---:|---:|
| baseline | 0.608 | [0.577, 0.628] | 0 | $0.0000 |
| minimal | 0.729 | [0.687, 0.759] | 0 | $1.3700 |
| optimized | **0.776** | [0.729, 0.804] | 0 | $2.6640 |

配对 optimized − minimal：**+0.047 [+0.011, +0.079]**，区间不含 0。

分任务：optimized 在 6/10 个子集更高，minimal 在 AggreFact-XSum、ExpertQA、FactCheck-GPT、
Lfqa、Wice 更高。逐子集表在 `results/v2.7-test/aggrefact/report/v27_aggrefact_report.json`。

## 轨道 B：RAGTruth++（端到端，两套句子金标）

数据：229 条回答（200 条新跑 + 29 条复用 v2.6 预测）；阈值 60。

| 金标 | 方案 | 句子 F1 [95% CI] | 回答 BAcc | 失败 |
|---|---|---:|---:|---:|
| 宽松（RAGTruth 原始） | minimal | **0.371** [0.271, 0.463] | **0.758** | 0 |
| 宽松 | optimized | 0.218 [0.152, 0.284] | 0.620 | 0 |
| 严格（RAGTruth++） | minimal | 0.522 [0.461, 0.578] | 0.647 | 0 |
| 严格 | optimized | **0.628** [0.578, 0.677] | **0.751** | 0 |

配对 optimized − minimal：

| 金标 | 句子 F1 差值 [95% CI] | 回答 BAcc 差值 [95% CI] |
|---|---|---|
| 宽松 | −0.153 [−0.226, −0.086] | −0.138 [−0.201, −0.076] |
| 严格 | +0.106 [+0.046, +0.168] | +0.104 [+0.031, +0.176] |

**结论（按第 5 节规则）：排名由金标标准决定。宽松标准下 minimal 更好，严格标准下 optimized
更好；应按使用场景选择。** 这不是两个结果互相抵消，而是同一批回答、同一批预测在金标宽严变化下
的真实反转。

任务分组（句子 F1，minimal / optimized）：宽松 QA 0.352 / 0.301，Summary 0.567 / 0.353；
严格 QA 0.714 / 0.853，Summary 0.661 / 0.867。

## 失败实例（每轨道按 ID 顺序取前 5 条，不挑选）

### 轨道 B（严格金标）

前 5 条全部是 minimal 的漏检；optimized 在其中 1 条（`ragtruthpp-1156`）抓到了错误句。

- `ragtruthpp-1155` Summary，llama-2-7b：金标坏句 1，minimal 无 C/U 主张，漏 1。
- `ragtruthpp-1156` Summary，llama-2-13b：金标坏句 2，minimal 漏 2；optimized 抓到
  “A Delaware family ... are in critical condition ...” 并判 CONTRADICTED。
- `ragtruthpp-1182` Summary，gpt-4：金标坏句 2，minimal 漏 2。
- `ragtruthpp-1183` Summary，gpt-3.5：金标坏句 1，minimal 漏 1。
- `ragtruthpp-1185` Summary，llama-2-7b：金标坏句 4，minimal 漏 1、误报 1。

### 轨道 A

前 5 条都来自 AggreFact-CNN；minimal 把金标 0 的主张判成 SUPPORTED，optimized 在其中 2 条也错。

- `aggrefact-AggreFact-CNN-02d82ecf292a`：2 条主张，minimal 错 1，optimized 错 0。
  “Celtic beat St Mirren 2-0 ...” 金标 0，minimal 判 SUPPORTED。
- `...-38e94fc24e33`：1 条主张，两个方案都错；“jafar adeli ... arranged to meet ...” 金标 0。
- `...-6002ade50606`：2 条，minimal 错 1，optimized 错 0；“Equal Pay Day ... 77 cents” 金标 0。
- `...-67126bdf6043`：1 条，两个方案都错；“roberto martinez ... free-kick ...” 金标 0。
- `...-7b79dd51ba9f`：2 条，minimal 错 1，optimized 错 0；“Nathan Hughes ... knocked out George North ...” 金标 0。

这些是 claim 级假阳性；轨道 A 的 BAcc 已经对正负类都计分，所以它们会实际拉低分数。

## 费用

| 项目 | 费用 |
|---|---:|
| 轨道 A test | $4.0340 |
| 轨道 B test | $5.0131 |
| S4 两次 dev | $1.7553 |
| **合计** | **$10.8024** |

- 轨道 B 的 29 条复用预测没有产生新费用；费用只计 200 条新跑。
- 两次重试都恢复，没有失败；没有截断。重试的 token 已计入费用。
- 低于 $16 上限，余量约 $5.20。

## 停止条件

- 两轨道三方案失败率均为 0；无超长、无截断；费用低于上限；未改 prompt、代码、数据。
- 未触发停止条件，test 结果有效。未重跑。
