# v2.7 S4 轨道 A dev 报告

**状态：dev 完成；第一次运行触发截断，按批准改为 minimal 每 20 条主张一批后重跑，0 失败。
尚未冻结，尚未跑 test。**

## 运行

- 数据：`data/eval_aggrefact.v2.7.dev.jsonl`，58 篇文档 / 196 条主张；10 个子集。
- 方案：baseline / minimal / optimized v3；oracle 模式，主张直接给定。
- 配置：`deepseek-v4-pro`，prompt v3，并发 4，max_tokens 4096。
- 第一次运行：baseline 0 失败、minimal 1、optimized 0。
- 第二次运行（batched，推荐用于 freeze）：三方案都是 0 失败。

## 第一次运行：截断

- `aggrefact-TofuEval-MediaS-4ff4dc016b2f`，61 条主张，minimal 把全部主张放进一次调用；
  16k 字符 JSON 在 `max_tokens=4096` 处截断：
  `unparseable response: Unterminated string starting at ... char 16174`。
- 主结果：optimized 0.798 vs minimal 0.731，配对差 +0.066 [+0.015, +0.119]。
- 剔除失败：optimized 0.798 vs minimal 0.822，配对差 −0.025 [−0.085, +0.026]。
- 差异完全由这次截断驱动；test 的 TofuEval 两篇文档有 104/103 条主张，不处理会重复。

## 第二次运行：minimal 分批（20 条/调用）

这是唯一改动：`eval/run_v27.py` 的 oracle 入口把 minimal 的主张分成每批 20 条，依次调用后
按原顺序合并；prompt、模型、`verifier/**` 和金标都不变。optimized 本来就是逐条核验。

| 方案 | 宏平均 BAcc | 95% CI | 失败文档 | dev 费用 | 每条主张 |
|---|---:|---|---:|---:|---:|
| baseline | 0.590 | [0.542, 0.645] | 0 | $0.0000 | $0 |
| minimal | 0.797 | [0.697, 0.853] | 0 | $0.2269 | $0.001158 |
| optimized | 0.811 | [0.714, 0.865] | 0 | $0.6730 | $0.003434 |

- 配对差 optimized − minimal = **+0.014 [−0.032, +0.053]**，区间含 0：
  没有证据表明两者存在差异。
- 剔除失败结果相同（没有失败）。
- minimal 的分批把 dev 费用从 $0.1812 提高到 $0.2269（+25%），换来了 0 截断。

## 预算

- dev 实际：$0.8999（baseline $0、minimal $0.2269、optimized $0.6730）。
- test 854 条主张按 dev 每条主张单价外推：minimal 约 $0.989、optimized 约 $2.933，合计约 **$3.92**。
- 加轨道 B $7.84、已花 dev $0.8999，总计约 **$12.66**，低于 $16 上限。
- 预算不是阻塞项；剩余余量足够覆盖失败重试和长文档。

## 结论与状态

- 分批后没有失败、没有截断、没有超长；停止条件未触发。
- S4 通过。等待 S5 冻结确认后，按冻结计划跑 test。
- 需要写入 freeze 的协议偏离：minimal 的 oracle 入口按 20 条主张/调用分批（仅 `eval/run_v27.py`），
  其余被测配置与 v2.6 一致。
