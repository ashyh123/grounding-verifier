# 第 2 节评分修正与历史结果副本重算（2026-10-19）

`eval-v2`；基准提交 `daf673e8036240a4bb9d63e12514b356f275c9ac`。`make test`：150 passed in 3.02s。
对 12 个目录的独立副本运行真实 `--rescore`；7 个目录已有数字变化，5 个目录已有数字不变；失败 0 个。
原 `data/eval.jsonl` 和 `results/` 共 49 个文件的 SHA256 全部不变，预测副本与原件逐字节一致。
**⏸ 已停止：未覆盖旧 summary 或文档中的历史数字，未提交代码，未进入第 3 节；等待用户确认。**

## 改动与计数口径

错误类别：词面相似不代表主张等价；不满足数字/否定约束的边不能参与一对一分配。
改动集中在 align_claims 的候选矩阵：先过滤，再最大化可匹配数量与相似度；指标和失败报告共用同一结果。
新增 guard_rejected_pairs、遗漏/多余/重复候选/新增候选计数，以及任务、难度、上下文长度、主张级跨段分组。
guard_rejected_pairs 是全部被拒绝的高相似候选边数，可能一条主张对应多条边，不能直接当作遗漏或语义错误数。
分组保留金标分母、失败和遗漏；难度为案例级（subtle 优先）；跨段只依据主张标签；缺元数据为 unknown。
分组计分复用整例对齐，不重新筛选金标并对齐；分组不报告无法可靠归属的输出精度。
已有 scipy、rapidfuzz 足够；没有新增依赖、模型调用或配置；Alignment 结果集中暴露配对与必要计数。
只有历史 summary 缺少新指标时报告 N/A，以便读取本次明确要求保留的旧产物。

## 已有主张准确率与 macro-F1（每轮分别列出）

| 目录 | 方法/轮次 | Accuracy 旧 → 新 | Macro-F1 旧 → 新 | guard 候选边 |
|---|---|---:|---:|---:|
| results/dev-anthropic-path | optimized/0 | 0.988764 → 0.988764 | 0.996564 → 0.996564 | 24 |
| results/dev-baseline | baseline/0 | 0.382022 → 0.382022 | 0.410957 → 0.417493 | 20 |
| results/dev-flashcheck | minimal/0 | 0.977528 → 0.977528 | 0.975041 → 0.975041 | 19 |
| results/dev-flashcheck | optimized/0 | 0.977528 → 0.977528 | 0.987548 → 0.987548 | 27 |
| results/dev-minimal-x3 | minimal/0 | 0.988764 → 0.977528 | 0.978477 → 0.975041 | 19 |
| results/dev-minimal-x3 | minimal/1 | 0.977528 → 0.966292 | 0.969266 → 0.965830 | 19 |
| results/dev-minimal-x3 | minimal/2 | 1.000000 → 0.988764 | 1.000000 → 0.996564 | 19 |
| results/dev-oracle | baseline/0 | 0.494382 → 0.494382 | 0.453898 → 0.453898 | 0 |
| results/dev-oracle | minimal/0 | 1.000000 → 1.000000 | 1.000000 → 1.000000 | 0 |
| results/dev-oracle | optimized/0 | 1.000000 → 1.000000 | 1.000000 → 1.000000 | 0 |
| results/dev-v1-x3 | optimized/0 | 0.977528 → 0.966292 | 0.987548 → 0.984041 | 26 |
| results/dev-v1-x3 | optimized/1 | 0.977528 → 0.966292 | 0.987548 → 0.984041 | 27 |
| results/dev-v1-x3 | optimized/2 | 0.988764 → 0.977528 | 0.996564 → 0.993056 | 26 |
| results/dev-v2 | optimized/0 | 0.966292 → 0.955056 | 0.954258 → 0.950676 | 25 |
| results/dev-v3-x3 | optimized/0 | 0.988764 → 0.988764 | 0.996564 → 0.996564 | 24 |
| results/dev-v3-x3 | optimized/1 | 0.988764 → 0.988764 | 0.996564 → 0.996564 | 24 |
| results/dev-v3-x3 | optimized/2 | 0.988764 → 0.988764 | 0.996564 → 0.996564 | 23 |
| results/dev-v4-x3 | optimized/0 | 0.988764 → 0.966292 | 0.996564 → 0.971533 | 23 |
| results/dev-v4-x3 | optimized/1 | 0.988764 → 0.977528 | 0.996564 → 0.993056 | 23 |
| results/dev-v4-x3 | optimized/2 | 0.988764 → 0.977528 | 0.996564 → 0.993056 | 23 |
| results/final_e2e | baseline/0 | 0.590164 → 0.590164 | 0.528421 → 0.535636 | 14 |
| results/final_e2e | minimal/0 | 0.983607 → 0.967213 | 0.982745 → 0.978730 | 13 |
| results/final_e2e | minimal/1 | 0.983607 → 0.967213 | 0.982745 → 0.978730 | 13 |
| results/final_e2e | minimal/2 | 0.983607 → 0.967213 | 0.982745 → 0.978730 | 13 |
| results/final_e2e | optimized/0 | 0.983607 → 0.967213 | 0.970343 → 0.966229 | 15 |
| results/final_e2e | optimized/1 | 0.983607 → 0.967213 | 0.970343 → 0.966229 | 15 |
| results/final_e2e | optimized/2 | 0.983607 → 0.967213 | 0.970343 → 0.966229 | 15 |
| results/final_oracle | baseline/0 | 0.704918 → 0.704918 | 0.569352 → 0.569352 | 0 |
| results/final_oracle | minimal/0 | 0.967213 → 0.967213 | 0.940134 → 0.940134 | 0 |
| results/final_oracle | minimal/1 | 0.983607 → 0.983607 | 0.982745 → 0.982745 | 0 |
| results/final_oracle | minimal/2 | 0.983607 → 0.983607 | 0.982745 → 0.982745 | 0 |
| results/final_oracle | optimized/0 | 1.000000 → 1.000000 | 1.000000 → 1.000000 | 0 |
| results/final_oracle | optimized/1 | 1.000000 → 1.000000 | 1.000000 → 1.000000 | 0 |
| results/final_oracle | optimized/2 | 1.000000 → 1.000000 | 1.000000 → 1.000000 | 0 |
| results/label-audit | minimal/0 | 0.980000 → 0.980000 | 0.973859 → 0.973859 | 0 |
| results/label-audit | optimized/0 | 0.993333 → 0.993333 | 0.994257 → 0.994257 | 0 |

全部旧字段逐路径差异见 [comparison.json](comparison.json)。每个重算副本中的 report.md 包含分组表。

## 测试与已知局限

单测覆盖数字改变/删除、正负号、否定翻转、删除含否定的条件、复合主张漏掉数字部分、重复/新增主张、
被拒配对不占用有效匹配、千分位与版本号、空输入和低相似候选不计守卫拒绝。
真实 rescore CLI 场景核对 399/400/799/800 词边界、失败分母、unknown、案例/主张级跨段区分、
重复与新增输出、报告一致、幂等重算、输入不变，以及 oracle 仍按位置评分；无网络/模型调用。
**纯条件删除或部分复合覆盖若未改变数字集合或显式否定，仍可能被词面相似度接受。**
本次守卫不是语义等价判定器；下列人工构造的反例现场验证仍匹配，保留为语义抽查的局限说明：
- prediction: `Restart is allowed.`；gold: `Restart is allowed if the cache is empty.`；自动接受：True。
- prediction: `The server uses TLS.`；gold: `The server uses TLS and writes logs.`；自动接受：True。

## 范围核对

搜索：`rg -n 'align_claims|token_set_ratio' --glob '*.py'`。
align.py 为唯一配对实现；metrics.py 及 report.py 调用点同步更新；test_core.py 同步改为拒绝漏掉 AES-256 的匹配。
metrics.py 的另一个 token_set_ratio 用于回答句子是否进入拆解的旧形状指标，不是金标对齐，保持原定义。
逐行审阅本次修改的 align.py、metrics.py、report.py、核心/对齐/CLI 测试与 EVALUATION 方法说明；
未对无关模块作全仓审计。eval/run.py 未修改，保留原 rescore 入口。

净行数相对本节开始时的工作区（包括新增测试，不把前一节未提交文件算作本节新增）：

| 区域/文件 | 净行数 |
|---|---:|
| verifier/align.py | +47 |
| eval/metrics.py | +53 |
| eval/report.py | +29 |
| eval/run.py | +0 |
| tests/test_core.py | +1 |
| tests/test_alignment.py | +75 |
| tests/test_eval_pipeline.py | +92 |
| docs/EVALUATION.md | +46 |
| annotation/README.md | +0 |

增长来自必需的守卫计数、四维分组、报告和反例/CLI 验证；已有标签 P/R/F1 计算已抽为共用函数，避免两份定义。
完整上游、.env、key 均未提交；未调用任何标注/被测模型，也未运行 hard test。
