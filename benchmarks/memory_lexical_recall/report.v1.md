# Memory lexical 召回离线原型报告

夹具 SHA-256：`dc19ba7bd3c4a0ed88a0669daad59fe5f5960d8189737e32d330f1eab43a1ef0`

复现命令：`python benchmarks/memory_lexical_recall/benchmark.py`

## 口径

- top-k：5
- recall@5：正样本逐 query 召回率的宏平均。
- precision@5：正样本实际返回的前五条中相关项比例的宏平均；空结果记 0。
- 负样本误召回率：返回任意结果的负样本 query 比例。
- 项目隔离率：返回结果中属于 long-term 或当前 project 的比例。
- literal 是一期显式召回基线；只有 FTS5 策略参与二期 go/no-go。

## 水位

| recall@5 | precision@5 | 负样本误召回率 | 项目隔离率 |
| ---: | ---: | ---: | ---: |
| ≥ 0.80 | ≥ 0.60 | ≤ 0.10 | = 1.00 |

## 结果

| 策略 | recall@5 | precision@5 | 负样本误召回率 | 项目隔离率 | 过线 |
| --- | ---: | ---: | ---: | ---: | --- |
| literal | 1.00 | 1.00 | 0.00 | 1.00 | 是 |
| unicode61 | 0.80 | 0.80 | 0.00 | 1.00 | 是 |
| trigram | 0.90 | 0.90 | 0.00 | 1.00 | 是 |

## 失败样例

### literal

- 无。

### unicode61

- `zh-two-char-wait: expected=['ci-merge-gate'], returned=[]`
- `zh-natural-language: expected=['recall-noise'], returned=[]`

### trigram

- `zh-two-char-wait: expected=['ci-merge-gate'], returned=[]`

## 两字中文限制

固定 query `等待` 在包含该短语的中文内容中：

- trigram 返回：`[]`；
- 这是 FTS5 trigram 无法为少于三个 Unicode 字符形成三元片段的已知限制；
- 报告不得把 trigram 概括为“支持中文”，二期重新规划必须单独处理短 query。

## Go / No-Go

**GO**：至少一个 FTS5 策略达到实验水位，值得重新规划二期 relevant 自动召回。

本结论只决定是否值得重新规划与评审二期；不选择生产 tokenizer，不授权实现、接入或发布二期自动召回。
