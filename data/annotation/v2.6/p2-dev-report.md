# v2.6 P2 dev 试跑报告

**状态：仅作流程与预算检查，不构成方案优劣结论。** dev 只有 30 例、9 个正例，区间很宽；
test 尚未运行。

## 运行配置

- 数据：`data/eval_ragtruth_resp.v2.6.jsonl`，dev 30 例（Summary / QA / Data2txt 各 10）。
- 方案：baseline（确定性，无模型调用）、minimal、optimized v3。
- 模型与参数：`deepseek-v4-pro`，prompt v3，temperature 0，thinking disabled，max_tokens 4096，
  provider `openai`，并发 4，价格 1.32 / 3.96 USD per Mtok。
- 代码与 prompt：v2.5 freeze 中 114 个文件当前哈希全部未变，因此被测系统与 v2.5 一致。
- 结果：`results/v2.6-dev/run1/`；指标与阈值扫描：`results/v2.6-dev/report/`。
- 失败：0；重试：0；截断：0（每次调用上限 4096 output tokens，所有调用均解析成功）。

## 主表（dev，30 例，9 正例）

| 方案 | 失败 | 精度 | 召回 | F1 [95% CI] | 平衡准确率 | 句子 F1 | 定位率 | 输出引文合法率 | 原始引文合法率 | 每例费用 |
|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|
| baseline | 0 | 0.310 | 1.000 | 0.474 [0.250, 0.651] | 0.524 | 0.149 | 1.00 | 1.000 | 1.000 | $0.0000 |
| minimal | 0 | 0.600 | 1.000 | 0.750 [0.500, 0.917] | 0.857 | 0.531 | 0.98 | 1.000 | 0.966 | $0.0053 |
| optimized | 0 | 0.360 | 1.000 | 0.529 [0.303, 0.714] | 0.619 | 0.308 | 0.98 | 1.000 | 0.973 | $0.0376 |

三种方案的 dev 召回都是 1.000，差别全部来自误报。minimal 误报 6 例，optimized 误报 16 例。

## 配对差值（dev，仅记录）

| 比较 | F1 差值 [95% CI] | 措辞 |
|---|---|---|
| optimized − minimal | −0.221 [−0.371, −0.106] | minimal 优于 optimized |
| minimal − baseline | +0.276 [+0.154, +0.426] | minimal 优于 baseline |
| optimized − baseline | +0.056 [+0.000, +0.127] | 没有证据表明存在差异 |

这个方向与 v2.5 的点估计一致（v2.5 也是 minimal 0.455 略高于 optimized 0.434，但区间跨 0）；
dev 的区间不含 0 仍不能当作 test 结论。可能的原因：
v2.5 的 test 为凑矛盾样本而偏向正例，自然分布下干净回答更多，optimized 更严格的核验更容易把
「原文没有明说」的合理概括判成 U/C。这是 test 要检验的假设，不能用 dev 下结论。

## 句子对齐阈值

- 评分器：`token_set_ratio`；阈值：**60**（冻结值）。
- dev 的 14 个上游片段全部（14/14）在 top-1 命中所属句子；最低分 66.7，p25 = 89.1，中位数 100。
- 阈值 60 低于最低真实片段分 66.7，留有余量；在此阈值下，minimal 与 optimized 的 C/U 主张
  定位率都是 0.976。
- 扫描 30–90：句子 F1 在 60–75 之间基本持平（minimal 0.531，optimized 0.308–0.324）；
  阈值 80 起定位率开始明显下降（minimal 0.857），85 时 optimized 降到 0.744。
- 选择 60 而不是 70–75：后两者虽然 optimized 的句子 F1 高约 0.008–0.016，但定位率降到
  0.90–0.93，且更接近真实片段的最低分；用 9 个正例去追逐这点差异不值得。

完整扫描与片段对齐结果在 `results/v2.6-dev/report/v26_report.json` 的
`threshold_sweep`、`best_score_quantiles`、`span_alignment`。

## 成本与 test 估算

- dev 实际：minimal $0.1578（$0.00526/例），optimized $1.1284（$0.03761/例），合计 $1.2863。
- 按 test 180 例、上下文均值 +5.8%、回答长度 −13.3% 缩放：minimal 约 $0.88，
  optimized 约 $6.82，合计约 **$7.7**；加 15% 余量约 **$8.9**。
- 方案 A 的 $12 上限足够；即使 optimized 的输入 token 有明显上浮，仍有约 30% 余量。
- optimized 平均每例 13.7 次 LLM 调用、延迟 p50 11.1 s、最大 32.8 s；test 180 例、
  并发 4 的墙钟时间预计 15–25 分钟。

## dev 中值得记录的现象

1. **optimized 的误报主要是「合理概括被判为无依据」。** 例如 `ragtruth-13153` 的
   “Hugging can lead to emotional intimacy” 被 P1 的「empathic listening ... emotional intimacy」
   间接支持，但 optimized 判 U；`ragtruth-1596` 的 “successful 64 Test matches” 因为原文只写
   “veteran of 64 Test matches” 被判 U。这些是上游未标注的推断，属于金标噪声与严格核验的交叉。
2. **minimal 有 4 例、6 条主张因引文无法定位被内部降级为 UNSUPPORTED。** 其中
   `ragtruth-4055`、`ragtruth-7003` 是金标干净回答，降级直接造成误报；`ragtruth-8240`、
   `ragtruth-8659` 本来就是正例，降级不改变回答级判断。
3. **只看输出引文会把这类失败藏起来。** 被丢弃的引文不会出现在最终输出，所以「输出引文合法率」
   是 1.000；新增的「原始引文合法率」按 `meta.raw_citations_*` 计算，minimal 为 0.966
   （355 条中 12 条不是 as-given 精确引文），optimized 为 0.973（526 条中 14 条）。
   该指标在 P2 加入，属于对已登记「引用合法率」的补全，仍冻结前登记。

## 结论

- 流程检查通过：0 失败、0 重试、无截断、无超长；预算与耗时可控。
- 冻结阈值 60；冻结后 test 只跑一次。
- dev 的 minimal > optimized 只作为 test 的待检验假设，不作为结论。
