# 评测基础设施设计

## Scope

本子任务只实现可离线验证的评测底座：数据契约、catalog/lock 校验、运行生命周期、无敏感 trace、JSON/中文报告，以及一个默认行为不变的 MCP 禁用 seam。它不构造 30 条任务、不拉取 SWE-bench-Live 数据，也不执行付费模型调用。

## Architecture

评测代码位于 benchmarks/agent_e2e，公开入口由 orchestrator 调用。它接受冻结 catalog 与 profile，先完成纯本地校验，再委托一个可替换的 ContainerBackend 执行 Agent worker 和 verifier。真实 Docker backend 只在 Docker 可用时启用；Unavailable backend 返回 blocked。

Agent worker 的结果通过 Agent.run 和 agent.core_runtime 的事件订阅收集。worker 使用独立 SessionRepository，避免 session 文件落到 task worktree。评测需要完整根 Agent，因此新增 Agent(mcp_enabled=True) 参数；默认 True 保持 CLI/TUI 语义，评测传 False 阻止全局/项目 MCP 发现。

## Contracts

- TaskSpec：任务 ID、family、split、base revision、公开 prompt、资源信息和 gold evidence hash。
- ExperimentProfile：model/provider 名称、prompt/compression/tool 版本、seed、repeat、timeout、预算和 agent code SHA。
- ExperimentManifest：profile 与 catalog 的冻结快照、选择任务、平台/镜像与 run ID。
- TaskResult：attempt、verdict、validity、patch hash、AgentRunResult、trace 摘要、成本和 invalid reason。
- Gate/Verdict/Fault 类型留给后续子任务；foundation 只保证序列化和 report 能保留未知扩展字段。

所有模型都必须拒绝未知字段或在读取时显式报告 schema version 不兼容；不得以自由字典悄悄吞掉评测协议漂移。

## Isolation Contract

正式 task_resolved 必须同时满足：ContainerBackend 可用、Agent workspace 与 verifier workspace 分离、private assets 不在 Agent 容器挂载表中、verifier 正常执行。否则结果为 blocked 或 invalid，不能为 passed/failed。

Host fallback 仅用于 unit test、catalog/manifest/trace/gate 离线验证，不能写 official 分数。

## Tests

- 数据模型 round-trip、未知字段、版本不兼容、catalog split/重复 ID/证据缺失。
- Unavailable backend、worker/verifier 异常、checkpoint 与 cleanup。
- fake Agent/Core event trace、敏感键脱敏、循环 fingerprint。
- Agent 默认 MCP 初始化与 mcp_enabled=False 的差异；独立 session 目录不进入工作区 diff。

父任务 design.md 和 implement.md 规定容器最终语义、在线预算和外部锚点协议；本文件只锁定本子任务的最小接口。
