# v2.7 数据统计（S2 草案）

**状态：轨道 B 已完成统计；轨道 A 被 LLM-AggreFact 的 gated 访问挡住，等待 Hugging Face 登录。**
本文件不构成 rules.json；样本量和预算确认后才写规则。

## 轨道 B：RAGTruth++

来源：`blue-guardrails/ragtruth-plus-plus`，revision
`afaec19e64122b4a58718dc31bcd555c97460233`，只本地使用，原始 CSV 与生成的
`data/eval_ragtruthpp.v2.7.jsonl` 都不提交；仓库只保留 `sources.json`、`selection.json`
（含数据集 sha256）、规则和构建代码。

- 回答数：408（816 条 message，408 user + 408 assistant）；幻觉片段 865。
- 与 RAGTruth `response.jsonl` 精确匹配：408/408；回答文本不一致 0；片段偏移不一致 0。
- 任务：QA 234、Summary 174；无 Data2txt。
- 生成模型：六个模型各 68 条。
- 宽松金标（RAGTruth 原始片段）：正例 65/408（15.9%），幻觉句 88。
- 严格金标（RAGTruth++ 片段）：正例 305/408（74.75%），幻觉句 619；每回答片段数
  0:103、1:89、2:78、3:49、4:32、5:26、6:12、7:13、8:4、9:1、11:1。
- 严格片段类型：Subtle Conflict 352、Subtle Baseless Info 190、Evident Conflict 183、
  Evident Baseless Info 115、Incorrect Refusal 22、Subtle Introduction Of Baseless Info 3。

### 排除与重叠

- 与 v2.3–v2.5 用过的 source_id 重叠：24 条回答、4 个 source；排除后 **384 条**。
- 其中与 v2.6 test 的 response_id 重叠：**29 条**，直接复用 v2.6 已有预测，不占 200 条新跑额度。
- 与 v2.6 dev 的 response_id 重叠：4 条；不属于复用范围，按新回答处理。
- 需要新跑：**355 条**。

### 按种子 20261024 截取

排序键：`random.Random(f"{seed}:response:{response_id}").random()`，再按 response_id 稳定排序。
取前 200 条新回答；29 条 v2.6 test 重叠全部纳入。合计 **229 条**。

- 新跑的 200 条：严格金标正例 150、宽松正例 31；QA 117、Summary 83。
- 模型分布：llama-2-7b 38、gpt-4 38、mistral 32、gpt-3.5 32、llama-2-70b 30、llama-2-13b 30。
- 长度：上下文 121 / 303.5 / 1230 词（min / median / max）；回答 7 / 94 / 282 词；
  句子 1 / 5 / 22。
- 全部 384 条的上下文最长 1230 词，回答最长 282 词，均在现有服务上限内；构建时 0 失败。

### 预算估算（按 v2.6 test 实际单价）

- 新跑 200 条：minimal 约 $1.04，optimized 约 $6.80，合计约 **$7.84**。
- 复用的 29 条不产生模型费用；baseline 0。
- 与设计文档的 $7.8 估算一致。

### 免费 baseline 检查

`results/v2.7-dev/baseline/`：229 条选中回答，0 失败，29 条复用 v2.6 预测。
strict 金标 BAcc 0.539、句子 F1 0.498；loose 金标 BAcc 0.526、句子 F1 0.111。
baseline 几乎对每条回答都报警，所以 strict 下 F1 看似高（0.853），但 BAcc 接近随机；
这是解析与指标管线的检查，不是方案结果。

## 轨道 A：LLM-AggreFact

来源：`lytang/LLM-AggreFact`，revision `981dfd0bd8e58e7238a9ab92b2e6ea44bce918e4`，
CC-BY-ND-4.0；用户已接受 gated 条款，本机 HF token 已登录。原始 parquet 和生成的
`data/eval_aggrefact.v2.7.*.jsonl` 都本地保留、不提交；仓库只保留 `sources.json`、
`aggrefact-selection-*.json`（统计）和构建代码。

- 10 个子集，排除 `RAGTruth` 子集：AggreFact-CNN、AggreFact-XSum、ClaimVerify、ExpertQA、
  FactCheck-GPT、Lfqa、Reveal、TofuEval-MediaS、TofuEval-MeetB、Wice。
- 文档长度上限 4000 词。被排除：test ClaimVerify 49 篇 / 81 主张、ExpertQA 67 / 71、
  Wice 18 / 18；dev ClaimVerify 42 / 74、ExpertQA 73 / 80、Wice 18 / 18。
- 按种子 `20261024` 整篇文档抽取：
  - test（S2 确认回退到 80/子集）：461 篇文档、**854 条主张**、512 正例；整篇抽样导致
    Lfqa 87、TofuEval-MediaS 104、TofuEval-MeetB 103。
  - dev（10/子集）：58 篇文档、**196 条主张**、108 正例；Lfqa 25、
    TofuEval-MediaS 61、TofuEval-MeetB 38。
- 切段：优先空行段落，长段按句子拆，按约 150 词打包；每段都是原文的 verbatim substring，
  记录 start/end；最多 25 段/文档、最大 8282 字符，均低于服务上限。
- 免费 baseline：test 宏平均 BAcc 0.606 [0.579, 0.627]（80/子集重采样前），dev 0.590；0 失败。
  baseline 精度高、召回低，是管线检查，不是方案结果。

### 预算

- 轨道 A dev 实际：$0.8999（minimal 分批后 0 失败）；test 854 条主张按 dev 单价外推约 **$3.92**。
- 轨道 B：$7.84。
- 加上已花 dev，总计约 **$12.66**，低于 $16 上限；第 10.2 节的 80/子集回退已应用。

**S4 状态：分批重跑通过，0 失败、无截断；等待 freeze 确认。**

