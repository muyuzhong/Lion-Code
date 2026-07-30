# 自建历史回放任务集实施计划

1. 在 `benchmarks/agent_e2e` 增加 corpus 模块：公开 task card、私有 evidence、split/leakage 校验和 historical replay preflight。
2. 以 Lion Git 历史中 30 个真实变更为来源，记录完整 base/gold revision、binary diff SHA-256、公开验证命令、资源元数据和 family/split。
3. 用三次确定性 Git provenance 检查记录 base fail、gold pass 和稳定证据；不得运行真实 provider 或 Docker。
4. 添加 `tests/benchmarks/test_corpus.py`，覆盖配额、evidence、泄漏和 preflight 拒绝路径。
5. 新增中文 corpus 说明，明确 public/private 边界及 patch-equivalence 不能代表官方语义得分。
6. 运行聚焦测试、完整 pytest、compileall、diff check 与 Trellis context 校验。
