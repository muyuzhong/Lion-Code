# 项目约定

## 核心原则与防过度设计

1. **最小实现与禁止顺带重构**：只解决当前明确提出的问题，优先局部修改现有实现；不为未来假设提前设计，禁止顺便重构无关代码。
2. **严禁过度抽象**：默认拒绝新增 Manager、Factory、Registry、Adapter、Strategy、Resolver、Coordinator、通用 Config 系统、Plugin/Hook 机制或新抽象基类/Protocol。仅在已有 2 个以上真实使用场景且无法修改现有代码解决时才允许提取。
3. **彻底删除与零兼容包袱**：不保留向后兼容，过时实现直接删除，不留 fallback、migration 或兼容层。
4. **优先复用**：优先使用项目已有依赖和成熟库，不重复实现已有能力。

## 修改范围与注释规范

- **修改范围**：严格限制在任务直接所需代码，不主动格式化、重命名或重构无关代码，不主动改变公开接口。
- **意图表达**：优先通过命名、类型和函数拆分表达意图；公共接口文档注释描述契约、边界、副作用与异常。
- **注释原则**：注释仅记录设计原因、业务规则、不变量与安全约束，不逐行解释代码。临时方案标记 `TODO(issue): 原因与完成条件`。源码注释统一使用中文，标识符与技术术语保留英文。

## 最小验证原则

- **默认最小验证**：只运行与本次修改直接相关的 targeted tests，通过即停止。禁止默认运行全量 test suite、全项目 lint、完整 mypy、coverage 或 radon/vulture 等全局扫描。
- **完整门禁触发条件**：仅在用户明确要求、准备提交 PR/merge、修改 CI/构建/测试基础设施、或修改核心公共接口时执行全量质量门禁。
- **失败处置**：优先定位根因，与当前修改无关的已有失败不顺手修复，修复后仅重跑受影响测试。

## 架构边界与修改约束

- **修改前阅读**：修改 Kernel、Runtime、Context、Provider、Tool 等核心边界前，先阅读对应的 `.trellis/spec/` 和 `docs/architecture/` 文档，理解现有 ownership 与依赖方向。
- **保持单向边界**：优先保持现有边界，不为了“解耦”机械增加层或接口；业务逻辑严禁反向依赖组合层或具体基础设施实现。
- **真值来源**：架构约束以 `tests/architecture/`、`.trellis/spec/backend/`、`docs/architecture/`、`_boundaries.py` 及 import-linter 为准。代码与文档冲突时以当前代码和架构测试为准，并同步修正文档。

## Git 与 PR 规范

- **原子提交**：每个独立改动单次提交，Commit message 用中文描述明确目的；提交前检查 `git diff` 杜绝无关修改，不提交无意义 CRLF 变化；不擅自 force-push 或 rebase。
- **独立 PR**：一个 PR 只解决一个独立问题或完成一个职责迁移，保证可独立理解与回滚；过大 PR 按行为边界拆分，不混入无关清理。

<!-- TRELLIS:START -->

# Trellis Instructions

These instructions are for AI assistants working in this project.

This project is managed by Trellis. The working knowledge you need lives under `.trellis/`:

- `.trellis/workflow.md` — development phases, when to create tasks, skill routing
- `.trellis/spec/` — package- and layer-scoped coding guidelines (read before writing code in a given layer)
- `.trellis/workspace/` — per-developer journals and session traces
- `.trellis/tasks/` — active and archived tasks (PRDs, research, jsonl context)

If a Trellis command is available on your platform (e.g. `/trellis:finish-work`, `/trellis:continue`), prefer it over manual steps. Not every platform exposes every command.

If you're using Codex or another agent-capable tool, additional project-scoped helpers may live in:
- `.agents/skills/` — reusable Trellis skills
- `.codex/agents/` — optional custom subagents

Managed by Trellis. Edits outside this block are preserved; edits inside may be overwritten by a future `trellis update`.
<!-- TRELLIS:END -->
