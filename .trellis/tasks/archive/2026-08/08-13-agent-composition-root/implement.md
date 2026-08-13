# 执行计划：Agent Composition Root

## 0. 开始实现前的门禁

- [x] `prd.md`、`design.md`、本文件已评审并获得用户对最终 planning summary 的
      明确批准。
- [x] 当前 master 的既有 dirty `.claude/`、`.codex/`、`.trellis/` 文件已记录为
      不属于本轮；实现只触碰本轮目标文件和任务 artifacts。
- [x] 运行 scoped AST/source probe，确认 whole-Agent injection 与
      `PlanRuntime(self)` 作为本轮收尾目标，而不是通过 Builder 掩盖前置缺陷。

## 1. 建立 Config/Dependencies 与 composition ports

- [x] 新增 `lion_code/composition/__init__.py`、`config.py`、`ports.py`。
- [x] 定义 frozen `AgentConfig`、frozen `AgentDependencies`，规范化 custom tools
      为不可变 tuple，并为 Provider/hooks/UI/project loader 保留现有 monkeypatch
      seams。
- [x] 实现 Runtime identity、Session state、Memory turn、Plan host、MCP/notice/
      confirmation/status 和必要 deferred ports；确保它们不引用 `Agent`。
- [x] 为 ports 写 focused unit tests，覆盖 live state、callback、MCP flag、
      child config 和 construction-order failure。

## 2. 提取一次性 Agent builder

- [x] 新增 `lion_code/composition/agent_builder.py`，按 design 中的 1-9 顺序搬移
      `Agent.__init__` 的 concrete construction。
- [x] 迁移默认 Capability registration 与 ToolSource 安装；保留 supplied registry
      的 replace/active 语义和 MCP root/child ownership。
- [x] 让 builder 返回显式 `AgentComposition`，不暴露 `get/resolve/services`，不把
      Builder/Agent 写入任何 runtime/domain 依赖。
- [x] 通过 structural ports 给 `AgentRuntimeCoordinator`、`PlanRuntime`、
      `SessionMemoryCoordinator`、`AutonomyRuntime`、`LearningRuntime`、
      `SubagentFactory` 传递窄依赖。

## 3. 收敛 Agent facade

- [x] 将旧 `Agent(...)` 参数转换为 Config/Dependencies，并支持 grouped config/
      dependencies 入口；冲突输入明确拒绝。
- [x] 删除 Agent 中的 concrete construction 和 `_register_capabilities`；保留
      public API、Application backend methods、兼容 delegate/property seams。
- [x] 逐项搜索并处理 `Runtime(self)`、`identity=self`、`session=self`、
      `memory=self`；不添加 fallback 或兼容层掩盖遗漏。
- [x] 保持 `patch("lion_code.agent.create_provider")`、hooks、renderer、notice、
      UI print、project loader 等既有 seams 可工作。

## 4. Capability architecture acceptance

- [x] 添加测试内 `ExampleCapability`/`SandboxCapabilityStub`，通过 Dependencies
      registration 验证 ToolSource、PromptLayer、SessionParticipant/TurnParticipant
      和 close 行为。
- [x] 添加 AST/source assertions：新增 capability 不需编辑 Agent/runtime/session/
      ToolContext/application/tui；Builder 不被保存；没有 ServiceLocator/
      AgentContainer；没有 whole-Agent constructor parameter。
- [x] 更新既有 constructor-owner architecture assertions，把 state/runtime owner
      从 `agent.py` 迁移到 `composition/agent_builder.py`。

## 5. 回归验证

- [x] focused tests：composition、agent runtime、provider manager、capabilities、
      plan、session memory、subagent、application/TUI integration。
- [x] `python -m pytest -q`。
- [x] `python -m pytest -q tests/architecture tests/runtime tests/capabilities`。
- [x] `lint-imports --no-cache`。
- [x] `ruff check lion_code tests scripts` 与 `ruff format --check`（记录当前基线
      的非本轮问题，不扩大无关格式化）。
- [x] `mypy lion_code tests`（记录 baseline 与本轮新增错误分开）。
- [x] `python -m compileall -q lion_code tests`、`git diff --check`。
- [x] 运行项目已有 quality baseline 脚本/CI 等价检查，报告全量与 scoped 结果。

## 6. 收尾门禁

- [x] 检查 `git diff` 只包含本轮文件；不 stage 用户已有 dirty files。
- [x] 使用中文提交说明，按职责拆分提交（若实现确实形成独立 wiring/guard 单元）。
- [x] 更新 `.trellis/spec/backend/`：只记录本轮确认的 Composition Root 约定，避免
      把临时实现细节写成未验证规范。
- [x] 完成最终报告五项架构结论和全量质量结果；本 PR 后停止纯解耦重构。

## 风险文件与回滚点

- 高风险：`lion_code/agent.py`、`lion_code/agent_runtime.py`、
  `lion_code/session_lifecycle.py`、`lion_code/subagent_factory.py`、
  `tests/architecture/test_runtime_boundaries.py`。
- 新增核心：`lion_code/composition/*`。
- 回滚：仅回滚本轮 work commit；保留任务 artifacts 和已有未识别 dirty files，
  不使用 `git reset --hard` 或覆盖用户修改。
