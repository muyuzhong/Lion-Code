# 验证 Memory 离线 lexical 召回

## Goal

用固定人工夹具比较 literal、FTS5 `unicode61` 和 `trigram`，决定二期是否值得重新规划自动召回。

## Requirements

- 覆盖中文两字短查询、英文、代码符号、路径、负样本和项目隔离。
- 脚本只读夹具、使用临时数据库，不读取或写入生产 Memory。
- 输出 recall@5、precision@5、负样本误召回率、失败样例和 go/no-go。
- 不把 tokenizer、阈值、boost 或 FTS 带入一期产品代码。

## Acceptance Criteria

- [ ] 固定命令可复现全部策略结果。
- [ ] 两字中文 trigram 限制有回归测试和报告。
- [ ] 报告明确是否达到最终设计水位，结论不自动授权二期实现。

## Dependency

与产品代码无依赖，可在前两个 child 后独立实施。
