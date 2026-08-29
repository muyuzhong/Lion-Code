# Agent Note: 裁剪 ToolRuntime.rollback() 恢复消费面（WorkspaceSnapshot.restore/RestoreResult/rolled_back 审计）

- Status: proposed
- 日期: 2026-08-29
- 范围: `lion_code/tooling/runtime.py`、`lion_code/tooling/snapshot.py`、`lion_code/tooling/context.py`、`lion_code/tooling/audit.py`、`tests/tooling/`、`tests/integration/test_core_tool_runtime.py`、`.trellis/spec/backend/tool-runtime-recovery.md`、`docs/architecture/tool-call-flow.md`

## Problem

workspace 快照的「消费侧」恢复/回滚整条面没有任何生产调用者，只有测试与 spec 钉住：

1. `ToolRuntime.rollback(...)`（`tooling/runtime.py:124-178`）：全仓 `\.rollback\(` 唯一命中是定义点与两个测试（`tests/integration/test_core_tool_runtime.py:193` 伪造 rollback 工具的用例、`tests/tooling/test_snapshot_runtime.py:148`）；模型侧触达不了：snapshot_id 只进 `ToolResult.details`（`middleware.py:93`），不进模型可见文本，没有任何内置工具能拿到 id 触发恢复。
2. `WorkspaceSnapshot.restore`（`snapshot.py:117-178`）与 `RestoreResult`（:23-31）：生产唯一调用点是 runtime.py:142（rollback 内部），其余全在测试。
3. `ToolContext.workspace_snapshot` 字段（`context.py:42-43`）与 `AuditResult` 的 `"rolled_back"` 值（`audit.py:18`）沿同一死链。
4. spec/文档消费者：`.trellis/spec/backend/tool-runtime-recovery.md` 整份把 rollback 列为公共契约（§2 签名、§3 rollback/audit 契约、§4-6 矩阵），`docs/architecture/tool-call-flow.md:76` 提及「rollback(snapshot_id) 回滚能力」。

快照**创建**链（`WorkspaceSnapshotMiddleware`/`create`/GC）是生产热路径，不受本次提案影响。

## Proposal

1. 删除 `ToolRuntime.rollback` 方法与 `ToolContext.workspace_snapshot` 字段（若审计双通道也收口：`agent_builder.py:780-782` 同时注入 `audit_fn` 与 `audit_log` 两通道，可随本候选一并收为单通道）。
2. 删除 `WorkspaceSnapshot.restore` 与 `RestoreResult`（含 `pre_restore_snapshot_id`/`restored_paths` 字段）；`AuditResult` 移除 `"rolled_back"` 与 `tool="rollback"` 分支。
3. 同步删 3 个测试文件中对应用例；改写 `tool-runtime-recovery.md`（删除或降级 rollback 契约段）与 `tool-call-flow.md:76`；`tooling/__init__.py` 移除 `RestoreResult` 导出。

## Why not keep it

快照恢复是「为未来 rollback 工具预留」的投机消费面：今天没有任何代码路径能让模型或宿主触发恢复。`.trellis/spec` 是现状文档而非产品承诺，按历次笔记先例（`usage-snapshot-unused-fields`/`prune-capability-unused-slots` 均删过 spec-promoted 无消费者面）与 AGENTS.md「不预防性抽象」，倾向删除。

## Acceptance criteria

- `rg -n "\.rollback\(|\.restore\(|RestoreResult|workspace_snapshot|rolled_back" lion_code/` 仅剩快照创建链合法命中（`WorkspaceSnapshot.create`、`GC`）。
- `tests/tooling/`、`tests/integration/test_core_tool_runtime.py` 全绿；快照创建/审计正常路径行为不变。

## Risks

- 若 owner 认定 `tool-runtime-recovery.md` 是待接入的真实能力（未来加 rollback 工具），则本提案应改为「保留 spec、删除实现」或整体放弃——删除等于吊销一份已写明的契约，需要产品侧确认；恢复成本约 60 行 + spec 重写。