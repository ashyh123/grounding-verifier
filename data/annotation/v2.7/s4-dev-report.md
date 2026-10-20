# v2.7 S4 轨道 A dev 报告

**状态：dev 已跑；出现截断，按停止条件停在 S4，未冻结、未跑 test。**

## 运行

- 数据：`data/eval_aggrefact.v2.7.dev.jsonl`，58 篇文档 / 196 条主张；10 个子集。
- 方案：baseline / minimal / optimized v3；oracle 模式，主张直接给定。
- 配置：`deepseek-v4-pro`，prompt v3，并发 4，max_tokens 4096。
- 失败：baseline 0，minimal 1，optimized 0。失败率 1/58 = 1.72%，低于 5%。

## 指标（宏平均 BAcc）

| 方案 | 主结果 | 剔除失败 | 失败文档 |
|---|---:|---:|---:|
| baseline | 0.590 | 0.590 | 0 |
| minimal | 0.731 | 0.822 | 1 |
| optimized | 0.798 | 0.798 | 0 |

- 主结果：optimized − minimal = +0.066 [+0.015, +0.119]，区间不含 0。
- 剔除失败：optimized − minimal = −0.025 [−0.085, +0.026]，没有证据表明存在差异。

主结果的差异完全由 minimal 的失败文档驱动；该失败不是随机错误，而是长主张列表的截断。

## 失败详情

- 文档：`aggrefact-TofuEval-MediaS-4ff4dc016b2f`，TofuEval-MediaS，61 条主张。
- 错误：`LLM unavailable after retries: unparseable response: Unterminated string starting at: line 1 column 16175 (char 16174)`。
- minimal 的 oracle 路径把全部 61 条主张放进一次调用；输出约 16k 字符，接近/超过 `max_tokens=4096` 的容量。
  这是截断，不是随机 JSON 错误。optimized 逐条核验，所以没有这个问题。
- test 的 TofuEval-MediaS 有 104 条主张、TofuEval-MeetB 有 103 条；不处理的话 minimal 在 test
  很可能重复截断，且涉及 207/854 = 24% 的 test 主张。

## 实际费用与预算

| 方案 | dev 费用 | 每条主张 |
|---|---:|---:|
| baseline | $0.0000 | $0 |
| minimal | $0.1812 | $0.000924 |
| optimized | $0.6742 | $0.003440 |
| **合计** | **$0.8554** | **$0.004365** |

- 按 dev 实际单价，test 854 条主张约 **$3.73**；加轨道 B $7.84，两个 test 合计约 **$11.57**；
  再加已花的 dev $0.855，**总计约 $12.43**，远低于 $16。预算不是本轮的问题。
- minimal 的失败调用没有 meta token 计数，因此实际费用略高于表中数字；影响很小。

## 需要决定

1. **在 oracle harness 里分批 minimal 的主张（推荐）**：例如每 20 条一批，多次调用、合并结果；
   prompt、模型和 verifier 代码不变，但调用数/费用增加。这是对 oracle 入口的适配，需要在
   freeze 前登记为协议偏离，并重跑 S4。optimized 已经是逐条核验，不需要改。
2. **把截断计为失败继续**：主结果按“失败全错”计，minimal 0.731；剔除失败 0.822。
   这违反“出现截断就停”的停止条件，而且 test 的 2 篇 TofuEval 文档会带 207 条主张的损失。
3. **缩小轨道 A 样本**：排除主张数超过阈值的文档（例如 >50），或去掉 TofuEval；这会改变
   10 个子集的样本，需重新登记，且失去这两个子集的代表性。

**建议选 1**：只改 v2.7 的 oracle 入口，不动 `verifier/**`、prompt、模型或金标；分批后重跑 dev，
确认 minimal 不再截断，再按实际费用冻结。第 5 节的结论规则不变。
