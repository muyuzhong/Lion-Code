# 实施计划

1. 固定 DeepEval 与 Opik Python SDK 版本为 benchmark 可选依赖。
2. 实现三个固定 DeepEval 指标和 trajectory/test case 转换，使用 fake judge 完成离线测试。
3. 实现宿主 Opik publisher，按既有 timestamp/parent 重建 spans 并写入 feedback。
4. 实现 timeout、partial failure、flush 和基于既有脱敏轨迹的独立 retry。
5. 添加 traced pytest eval 入口，确认与共享分析函数一致且不运行 Agent。
6. 在 Linux 对一条既有 Verified 结果运行真实 DeepEval 与 Opik Cloud smoke。

## 验证

- compileall、受影响 tests/benchmarks、git diff --check。
- fake judge/client 不需要网络和凭证；真实 smoke 必须显式开启并记录预算。
- 在 Opik UI 按 run_id 验证 trace tree、Harness feedback 和三项 DeepEval 指标。

## 停止条件

- 任何凭证或未脱敏正文进入 Harbor environment、日志、报告或 Cloud trace 时停止上传。
- DeepEval/Opik SDK 固定版本无法满足现有 typed contract 时报告阻塞，不添加兼容层。
