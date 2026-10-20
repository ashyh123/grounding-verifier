# v2.3 五例 dev 试点报告（2026-10-20）

依据 [Notion v2.3](https://app.notion.com/p/3fe7b21c6588813fa732c6a51e30e6f7)，在 `eval-v2` 完成第 1–4 节试点。
用户确认 MiMo 继续使用；实际返回模型均为 `mimo-v2.6-pro`，使用现有 MiMo Anthropic 接口。
七份旧复核文件已改名存档，记录在 `../revocations.json`。没有使用人工复核、盲审、分桶或翻译。

| 案例 | 起草→保留主张 | S / C / U（保留） | 剔除 | 精确证据 / S+C | model_doubts |
|---|---:|---|---|---:|---:|
| ragtruth-13105 | 14 → 14 | 9 / 0 / 5 | 0 | 8 / 9 (88.9%) | 4 |
| ragtruth-15677 | 7 → 6 | 5 / 0 / 1 | 1 partial_overlap | 4 / 5 (80.0%) | 0 |
| ragtruth-2426 | 10 → 9 | 8 / 0 / 1 | 1 partial_overlap | 7 / 8 (87.5%) | 0 |
| ragtruth-66 | 11 → 11 | 11 / 0 / 0 | 0 | 11 / 11 (100.0%) | 0 |
| ragtruth-9775 | 21 → 20 | 20 / 0 / 0 | 1 partial_overlap | 2 / 20 (10.0%) | 1 |

合计：63 条起草主张，剔除 3 条 partial_overlap，保留 60 条：53 S / 0 C / 7 U。
没有整例剔除，没有 source_label_uncovered，因此没有重起草调用。
32/53 条 S/C 有精确证据（60.4%）；按所有保留主张计为 32/60（53.3%）。
其余 21 条 S/C 保持标签，evidence_status=none；7 条 U 无证据且未调用模型。
模型疑问 5 条，包括有证据但怀疑标签的记录；并非所有 none 都表示模型质疑标签。

## 必须保留的限制

Data2txt `ragtruth-9775` 只有 2/20 条精确证据。该例有 23 条引文因不能在指定 passage 中
精确找到而被丢弃，主要涉及错误 passage index 或引文转义；没有改 index、模糊匹配、改标签或重跑来提高比例。
全部案例共丢弃 26 条不合格引文。精确子串验证不等于语义充分性验证。
本试点保留标签中没有 C，因此不能用这个试点声称验证了真实 C 案例的证据定位质量；Conflict 优先逻辑有离线测试。
`ragtruth-9775` 的上游幻觉落在被剔除主张中，保留标签全部为 S；这说明过滤会改变标签分布，不能把它宣称为经二次人工确认的干净回答。

## 产物与验证

- `mapped.jsonl`、`excluded.jsonl`、`mapping-report.json`：离线标签映射与剔除记录。
- `evidence_calls.jsonl`：60 条检查点（53 次真实调用，7 条 U 零调用），逐条记录模型、参数、prompt SHA256、UTC 时间和 token。
- `model_doubts.jsonl`：5 条；`evidenced.jsonl`、`evidence-report.json`：试点结果与证据统计。
- 映射中一条旧 nullable upstream_verdict 已规范为脚本结果；标签 verdict 未变。旧中间文件改名为 `.superseded-canonical-fields` 保留。
  重新物化时重用全部调用检查点，没有追加模型请求。
- `make test`：211 passed（18.47s）；`git diff --check` 通过。
- 内存中通过正式 EvalCase schema 与 validate 校验全部试点主张；所有已接受证据均符合原始 passage 的精确切片。
- 54 个保护文件 SHA256 均未变化，包括 data/eval.jsonl、results/ 与五份指定原始文件；14 份旧/新归档 SHA256 校验通过。
- 调用用量：67,367 输入 token，7,058 输出 token；这些是 provider 返回用量，不是账单金额。

## 最小设计复查

新增两个流水线模块共 378 行（map_labels 173 / find_evidence 205），测试 273 行。
新增量来自规格所需的确定性映射、一次重起草、证据边界、调用检查点及真实 CLI 场景；无新增依赖。
loader/scorer 仅增加 label_source、evidence_status 与引用分母分支，复用现有模型客户端。
旧复核工具按要求保留；本轮只运行新入口，没有叠加另一套模型投票或人工复核框架。
逐行复查范围为这两个新模块、新测试及本轮修改的客户端/loader/metrics；未对进入本轮前的全部未提交改动做仓库审计。
文档和 Makefile 原已有未提交修改，本轮未记录它们的初始逐行快照，因此不冒称 git diff 总量全是本轮新增。

## 暂停

遵照第 4 节「⏸ 汇报」：此处停止，等待用户确认后才扩展剩余 25 例。
剩余案例此前已有的部分草稿已保留；旧后台调用已停止，本轮未继续生成。
尚未修改合并/冻结工具、生成 data/eval_hard.jsonl、写 freeze.json、提交或运行 hard test。
