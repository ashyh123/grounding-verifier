# v2.4 合并统计（数据诊断，无被测方案成绩）

| split | subset | 案例 | 主张 | S | C | U | S/C 精确证据 |
|---|---|---:|---:|---:|---:|---:|---:|
| dev | all | 15 | 211 | 185 | 9 | 17 | 193/194 |
| dev | natural | 10 | 126 | 106 | 3 | 17 | 108/109 |
| dev | conflict_supplement | 5 | 85 | 79 | 6 | 0 | 85/85 |
| test | all | 35 | 427 | 385 | 21 | 21 | 402/406 |
| test | natural | 20 | 256 | 235 | 4 | 17 | 238/239 |
| test | conflict_supplement | 15 | 171 | 150 | 17 | 4 | 164/167 |
| all | all | 50 | 638 | 570 | 30 | 38 | 595/600 |
| all | natural | 30 | 382 | 341 | 7 | 34 | 346/348 |
| all | conflict_supplement | 20 | 256 | 229 | 23 | 4 | 249/252 |

| 任务 | S/C 精确证据 | 覆盖率 |
|---|---:|---:|
| ragtruth_data2txt | 231/234 | 98.7% |
| ragtruth_qa | 76/77 | 98.7% |
| ragtruth_summary | 288/289 | 99.7% |

| split / subset | context words min / median / mean / max | answer words min / median / mean / max |
|---|---|---|
| dev / all | 204 / 635 / 668.4 / 1402 | 75 / 161 / 165.7 / 269 |
| dev / natural | 262 / 708.0 / 652.1 / 1054 | 75 / 156.5 / 163.2 / 269 |
| dev / conflict_supplement | 204 / 382 / 701 / 1402 | 93 / 185 / 170.6 / 236 |
| test / all | 164 / 425 / 553.9 / 1626 | 60 / 132 / 138.6 / 304 |
| test / natural | 164 / 558.0 / 677.4 / 1626 | 62 / 139.5 / 152.5 / 304 |
| test / conflict_supplement | 187 / 399 / 389.3 / 852 | 60 / 108 / 120.1 / 187 |
| all / all | 164 / 441.5 / 588.3 / 1626 | 60 / 135.0 / 146.7 / 304 |
| all / natural | 164 / 607.5 / 669.0 / 1626 | 62 / 146.0 / 156.1 / 304 |
| all / conflict_supplement | 187 / 390.5 / 467.2 / 1402 | 60 / 124.0 / 132.7 / 236 |

## 审计摘要

- 剔除主张 12；整例剔除 0。旧 10 条父主张退休，替代子主张保留 15、仍剔除 4，分别记账。
- 拆分产生的 15 条保留候选中，14 条成为新增 gold；1 条与已有相同标签、文本、重叠回答跨度的 gold 合并溯源，避免重复计分。
- 证据兜底和新 prompt 统计、model_doubts、上游无标注回答及目标达成情况：
```json
{
  "evidence": {
    "overall": {
      "exact": 595,
      "eligible_sc": 600,
      "coverage": 0.9916666666666667
    },
    "by_task": {
      "ragtruth_data2txt": {
        "exact": 231,
        "eligible_sc": 234,
        "coverage": 0.9871794871794872
      },
      "ragtruth_qa": {
        "exact": 76,
        "eligible_sc": 77,
        "coverage": 0.987012987012987
      },
      "ragtruth_summary": {
        "exact": 288,
        "eligible_sc": 289,
        "coverage": 0.9965397923875432
      }
    },
    "offline_repair": {
      "original_none_sc": 98,
      "recovered_claims": 86,
      "index_corrected_quotes": 119,
      "original_input_sha256": "64d84d79314032f5232da407e07b95f2bf87a6b9e4e70572c43c7900022e6523"
    },
    "original_none_new_prompt": {
      "rerun_claims": 98,
      "new_prompt_exact_claims": 95,
      "new_prompt_additional_claims_after_offline": 10,
      "index_corrected_quotes": 0,
      "model_doubts": 11,
      "protocol_errors": 0,
      "usage": {
        "calls": 98,
        "input_tokens": 141441,
        "output_tokens": 19626
      }
    },
    "initial_supplement_and_recovery": {
      "supplement": {
        "calls": 252,
        "exact": 249,
        "protocol_errors": 0
      },
      "recovered": {
        "calls": 10,
        "exact": 10,
        "protocol_errors": 0
      }
    },
    "index_corrected_quotes_offline": 119,
    "index_corrected_quotes_new_calls": 0
  },
  "model_doubts": {
    "records": 75,
    "unique_claims": 65,
    "protocol_diagnostics": 4,
    "semantic_doubts_or_not_found": 71
  },
  "upstream_unannotated_answers": {
    "display_name": "上游无标注回答",
    "cases": 7,
    "cases_with_model_doubts": 4,
    "model_doubts_records": 5,
    "case_ids_with_doubts": [
      "ragtruth-1453",
      "ragtruth-211",
      "ragtruth-3247",
      "ragtruth-619"
    ]
  },
  "targets": {
    "test_contradicted": {
      "observed": 21,
      "minimum": 15,
      "met": true
    },
    "data2txt_evidence": {
      "observed": 0.9871794871794872,
      "minimum": 0.7,
      "met": true
    }
  }
}
```

本轮修改仅依据标签分布和证据流水线诊断；未运行任何 hard-test 被测方案。
所有标签来自 RAGTruth 人工跨度映射；引文精确存在不保证语义充分，无二次人工确认。
新增集 GPT 下限已按用户授权取消，其余固定配额、长度和去重规则不变。
