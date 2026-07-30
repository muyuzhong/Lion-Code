# 评测基础设施实施计划

1. 新建 benchmarks/agent_e2e 的可导入包、严格模型、catalog/manifest 校验和离线报告。
2. 为 Agent 增加 mcp_enabled 默认参数，并让根 Agent 的 MCP 发现遵守该开关；补足 focused 回归测试。
3. 实现 TraceRecorder、脱敏、循环候选 fingerprint 和 TaskResult 聚合。
4. 实现 ContainerBackend 协议、Unavailable backend、受控 fake backend、单题 orchestrator、checkpoint 与 cleanup。
5. 实现 CLI 的 validate/offline-run 路径；online/real Docker 路径在 Docker 缺失时明确 blocked。
6. 添加 tests/benchmarks 覆盖协议、异常和 Agent seam，运行受影响测试、完整 pytest、compileall 与 diff check。

## Completion Conditions

- 所有 foundation PRD acceptance criteria 通过。
- 无真实 provider、无 Docker daemon 时可完成全套离线测试。
- 新增 Agent 参数默认不改变现有 MCP、CLI/TUI、SessionRecorder 行为。
