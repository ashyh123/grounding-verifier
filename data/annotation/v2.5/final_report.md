# v2.5 合并统计（数据诊断，无被测方案成绩）

| split | subset | 案例 | 主张 | S | C | U | S/C 精确证据 |
|---|---|---:|---:|---:|---:|---:|---:|
| dev | all | 18 | 245 | 218 | 10 | 17 | 227/228 |
| dev | natural | 10 | 126 | 106 | 3 | 17 | 108/109 |
| dev | conflict_supplement | 5 | 85 | 79 | 6 | 0 | 85/85 |
| dev | subtle_supplement | 3 | 34 | 33 | 1 | 0 | 34/34 |
| test | all | 45 | 537 | 483 | 27 | 27 | 506/510 |
| test | natural | 20 | 256 | 235 | 4 | 17 | 238/239 |
| test | conflict_supplement | 15 | 171 | 150 | 17 | 4 | 164/167 |
| test | subtle_supplement | 10 | 110 | 98 | 6 | 6 | 104/104 |
| all | all | 63 | 782 | 701 | 37 | 44 | 733/738 |
| all | natural | 30 | 382 | 341 | 7 | 34 | 346/348 |
| all | conflict_supplement | 20 | 256 | 229 | 23 | 4 | 249/252 |
| all | subtle_supplement | 13 | 144 | 131 | 7 | 6 | 138/138 |

| 任务 | S/C 精确证据 | 覆盖率 |
|---|---:|---:|
| ragtruth_data2txt | 296/299 | 99.0% |
| ragtruth_qa | 98/99 | 99.0% |
| ragtruth_summary | 339/340 | 99.7% |

| split / subset | context words min / median / mean / max | answer words min / median / mean / max |
|---|---|---|
| dev / all | 125 / 506.5 / 607.5 / 1402 | 64 / 156.5 / 159.3 / 269 |
| dev / natural | 262 / 708.0 / 652.1 / 1054 | 75 / 156.5 / 163.2 / 269 |
| dev / conflict_supplement | 204 / 382 / 701 / 1402 | 93 / 185 / 170.6 / 236 |
| dev / subtle_supplement | 125 / 316 / 303 / 468 | 64 / 110 / 127.3 / 208 |
| test / all | 164 / 425 / 549.4 / 1626 | 60 / 128 / 136.5 / 304 |
| test / natural | 164 / 558.0 / 677.4 / 1626 | 62 / 139.5 / 152.5 / 304 |
| test / conflict_supplement | 187 / 399 / 389.3 / 852 | 60 / 108 / 120.1 / 187 |
| test / subtle_supplement | 177 / 361.5 / 533.7 / 1117 | 94 / 124.0 / 129.1 / 196 |
| all / all | 125 / 425 / 566.0 / 1626 | 60 / 132 / 143 / 304 |
| all / natural | 164 / 607.5 / 669.0 / 1626 | 62 / 146.0 / 156.1 / 304 |
| all / conflict_supplement | 187 / 390.5 / 467.2 / 1402 | 60 / 124.0 / 132.7 / 236 |
| all / subtle_supplement | 125 / 332 / 480.5 / 1117 | 64 / 124 / 128.7 / 208 |

## 审计摘要

- 新增 10 test / 3 dev；上游 split：{'train': 13}；GPT 7/13。
- 剔除主张 11；整例剔除 0。历史 v2.4 剔除主张 12 另记。
- 证据：全部 S/C 733/738；新增集 138/138。
- doubt_category：{'agree': 49, 'evidence_not_found': 28, 'partial_claim': 31, 'suspected_wrong_label': 29}；敏感性分析将剔除 29 条。
- 目标：test Subtle-Conflict 来源的 C = 7（≥8）：未达到；partial_overlap 剔除中另有 7 条此类 C，未追加案例、未改规则。

```json
{
  "targets": {
    "test_contradicted": {
      "observed": 27,
      "minimum": 15,
      "met": true
    },
    "test_contradicted_from_subtle_conflict": {
      "observed": 7,
      "minimum": 8,
      "met": false
    },
    "data2txt_evidence": {
      "observed": 0.9899665551839465,
      "minimum": 0.7,
      "met": true
    }
  },
  "doubt_categories": {
    "records": 137,
    "in_dataset": 137,
    "by_category": {
      "agree": 49,
      "evidence_not_found": 28,
      "partial_claim": 31,
      "suspected_wrong_label": 29
    },
    "by_category_label": {
      "agree": {
        "CONTRADICTED": 18,
        "SUPPORTED": 13,
        "UNSUPPORTED": 18
      },
      "evidence_not_found": {
        "CONTRADICTED": 1,
        "SUPPORTED": 7,
        "UNSUPPORTED": 20
      },
      "partial_claim": {
        "CONTRADICTED": 7,
        "SUPPORTED": 22,
        "UNSUPPORTED": 2
      },
      "suspected_wrong_label": {
        "CONTRADICTED": 11,
        "SUPPORTED": 14,
        "UNSUPPORTED": 4
      }
    },
    "sensitivity_claims_in_dataset": [
      "ragtruth-12692-c8",
      "ragtruth-13340-c12",
      "ragtruth-13340-c5",
      "ragtruth-1340-c12",
      "ragtruth-14323-c6",
      "ragtruth-14912-c1",
      "ragtruth-14912-c5",
      "ragtruth-15677-c3",
      "ragtruth-1698-c2-v24-split1",
      "ragtruth-1698-c6",
      "ragtruth-1730-c6",
      "ragtruth-2354-c1",
      "ragtruth-2468-c4",
      "ragtruth-2672-c2",
      "ragtruth-2672-c7",
      "ragtruth-3080-c4",
      "ragtruth-348-c11",
      "ragtruth-3980-c2",
      "ragtruth-4118-c8",
      "ragtruth-5675-c8",
      "ragtruth-5851-c8",
      "ragtruth-6973-c23",
      "ragtruth-6973-c25",
      "ragtruth-7051-c9",
      "ragtruth-7098-c10",
      "ragtruth-7159-c16",
      "ragtruth-7952-c6",
      "ragtruth-7952-c9",
      "ragtruth-9492-c8"
    ],
    "sensitivity_claims_classification_only": [],
    "protocol_errors": 0,
    "errors": 0
  },
  "upstream_splits": {
    "train": 13
  }
}
```

本轮修改只依据标签分布和流水线诊断；未运行任何 hard-test 被测方案。
所有标签来自 RAGTruth 人工跨度映射；引文精确存在不保证语义充分，无二次人工确认。
