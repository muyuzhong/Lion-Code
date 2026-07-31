# 实现评测运行器与轨迹协议

## Goal

提供端到端评测的可复现底座：严格的数据契约、隔离运行器、无敏感受控轨迹、patch/verifier 接口和中文报告骨架。

## Requirements

- 在 benchmarks/agent_e2e 内实现 catalog、manifest、worker、orchestrator、trace、verifier 和 report 的基础边界。
- 正式成绩必须由 Agent container 与后置 verifier container 产生；无 Docker 时只允许离线验证并返回 blocked。
- Agent worker 使用 Agent.run、Core event subscription 和独立 SessionRepository；默认产品 MCP 行为不变，评测显式禁用 MCP。
- 所有离线测试使用 FakeProvider/FakeDocker；结果、trace 和 manifest 不保存密钥或用户 session。

## Acceptance Criteria

- [ ] 数据模型、catalog/lock 和结果序列化具有单元测试及 schema version。
- [ ] fake lifecycle 覆盖成功、timeout、worker 异常、verifier 异常、cleanup 和 checkpoint 恢复。
- [ ] Agent 默认 MCP 路径无回归，mcp_enabled=False 不连接 MCP，session 不落入 task workspace。
- [ ] Docker 缺失返回 blocked，不输出 task_resolved。

## Dependency

这是其他三个子任务的前置；父任务 design.md 与 implement.md 是本任务的技术设计来源。
