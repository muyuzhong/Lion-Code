# 项目约定

## 核心原则

1. 只解决当前明确提出的问题。
2. 优先选择满足当前需求的最简单实现。
3. 优先局部修改，禁止顺便重构无关代码。
4. 不为假设中的未来需求提前设计。
5. 不预防性增加抽象层、扩展点、配置项或通用框架。
6. 能修改现有实现解决，就不要创建新的架构。
7. 只有当前已经存在两个以上真实使用场景时，才考虑提取公共抽象。
8. 不保留向后兼容。过时实现直接删除，不增加兼容层、migration 或 fallback。
9. 优先使用项目已有依赖和成熟、持续维护的库，不重复实现已有能力。
10. 保持模块边界和关注点分离，但不要为了“模块化”本身增加无实际价值的层级。

## 防止过度设计

默认拒绝新增以下结构，除非当前需求明确需要：

- Manager
- Factory
- Registry
- Adapter
- Strategy
- Resolver
- Coordinator
- 通用 Config 系统
- Plugin / Hook / Extension 机制
- 新的抽象基类或 Protocol

新增任何上述结构前，先确认：

1. 当前具体问题是否无法通过修改现有实现解决。
2. 是否已经存在至少两个真实使用场景。
3. 新抽象是否实际减少复杂度，而不是把复杂度转移到更多文件和接口中。

如果理由主要是“未来可能需要”，不要实现。

## 修改范围

- 修改范围严格限制在当前任务所需代码。
- 不主动清理、格式化、重命名或重构无关代码。
- 不因为发现附近代码“不够优雅”就顺便修改。
- 不主动改变公开接口，除非当前任务要求。
- 删除已经失去用途的旧代码，不保留废弃路径。
- 优先小而可验证的改动。

## 注释原则

- 注释只描述代码本身无法清楚表达的信息：
  - 设计原因
  - 业务规则
  - 不变量
  - 性能、安全或兼容约束
- 不逐行解释代码。
- 优先通过命名、类型和函数拆分表达“代码在做什么”。
- 公共接口的文档注释描述契约、边界、副作用和异常。
- 简单私有实现不强制写注释。
- 临时方案使用 `TODO(issue): 原因与完成条件`。
- 注释与代码不一致视为缺陷。
- 源码注释使用中文，标识符和必要技术术语保留英文。

## 验证原则

默认执行最小验证。

- 只运行与本次修改直接相关的 targeted tests。
- targeted tests 通过后停止验证。
- 不默认运行完整 test suite。
- 不默认运行全项目 lint。
- 不默认运行完整 mypy。
- 不默认运行 coverage。
- 不默认运行 radon、vulture 或其他全局质量扫描。
- 不因为修改完成而重复运行已经通过的测试。

以下情况才执行完整质量门禁：

- 用户明确要求。
- 准备提交 PR / merge。
- 修改 CI、构建系统或测试基础设施。
- 修改影响范围无法通过 targeted tests 合理覆盖。
- 修改核心公共接口并可能影响大量模块。

测试失败时：

1. 先判断失败是否与当前修改有关。
2. 与当前修改无关的已有失败不要顺手修复。
3. 优先定位根因，不通过增加 fallback 或绕过测试解决。
4. 修复后只重新运行受影响测试。

## 架构修改

涉及 Kernel、Runtime、Context、Provider、Tool 等核心边界时：

- 修改核心模块前，先阅读对应的 `.trellis/spec/` 和 `docs/architecture/` 文档。
- 先理解现有 ownership 和 dependency direction。
- 优先保持现有边界，而不是创建新的层。
- 不为了“解耦”而机械增加接口。
- 接口只存在于确实需要隔离变化或存在多个实现的边界。
- 不允许业务逻辑反向依赖组合层或具体基础设施实现。

架构约束以以下内容为准：

- `tests/architecture/`
- `.trellis/spec/backend/`
- `docs/architecture/`
- `_boundaries.py`
- import-linter 配置

代码与文档冲突时，以当前代码和架构测试为准，并同步修正文档。修改相关边界时同步更新对应架构测试和文档。

## Git 与提交

- 每个独立改动完成后提交一次。
- Commit message 使用中文描述。
- 一个提交只包含一个明确目的。
- 提交前检查 `git diff`，确保没有无关修改。
- 不因为 CRLF / LF 等问题提交整文件无意义变化。
- 不擅自 force-push、rebase 或修改历史，除非当前任务明确需要。

## PR 原则

- 一个 PR 只解决一个独立问题或完成一个职责迁移。
- 保证 PR 可以独立理解和回滚。
- 不把无关清理和功能修改混入同一个 PR。
- PR 过大时按行为边界拆分，而不是机械按文件数量拆分。

## 工作方式

开始实现前：

1. 阅读与当前任务直接相关的代码。
2. 找到现有实现路径。
3. 优先寻找最小修改方案。
4. 再开始编码。

不要先设计一个“理想架构”再把当前问题塞进去。

实现完成后：

1. 检查 diff。
2. 删除无必要的新增抽象和代码。
3. 运行最小 targeted tests。
4. 测试通过后停止。

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
