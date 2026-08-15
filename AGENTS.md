# 项目约定

## 注释原则

- 优先用准确命名、类型和函数拆分表达“做什么”，注释只补充代码无法直接表达的信息。
- 注释重点说明设计原因、业务规则来源、不变量，以及兼容性、性能或安全约束。
- 不逐行翻译代码；显而易见的流程和重复签名信息不写注释。
- 公共接口的文档注释应说明契约、边界、副作用和异常，简单的私有实现无需强制补齐。
- 临时方案使用 `TODO(issue): 原因与完成条件`，不要留下无负责人、无期限的 TODO。
- 修改实现时同步更新或删除注释；与代码不一致的注释按缺陷处理。源码注释使用中文，标识符和必要术语保留英文。

每完成单次改动都进行提交，并添加中文描述

# 项目原则

1. 不保留向后兼容。过时的直接删，别加兼容层、别写migration、别留fallback。
2. 选能满足当前需求的最简单实现。不要预防性抽象，不要多此一举的配置层。
3. 系统分层长。先跑通一个最小的端到端版本，再往上加东西。绝不为了未完成的复杂度拆掉能跑的东西。 
4. 组件保持模块化，关注点分离。
5. 优先用成熟的、有人维护的库。没有明确理由别自己重写。
6. 先翻项目里已有的依赖能做什么，再考虑加新包或自己写。别上来就假设库里没有。
7. 架构决策往长了做。不接受"先这样以后再换"的临时方案。
8. 先看成熟产品怎么解决同一个问题，用已验证的模式，别从零发明。

## PR 规范

- 一个 PR 只承载一个职责迁移或一个独立改动；不把多个子阶段攒成一个大 PR。
- PR 描述必须包含：迁移的状态所有权、保持不变的不变量、测试矩阵、行数与依赖变化、回滚点。
- 出现问题时可以单独回滚，而不是回滚整条路线。
- 大于 10 个提交或 20 个文件的 PR 需要拆分，除非改动是机械重命名或自动生成。

## 工程经验（CI 门禁 / 分层重构）

### 本地验证与 CI 门禁

- 本地快速验证可用 unittest 风格测试：
  `PYTHONPATH=tests python3 -m unittest discover tests -p "test_*.py"`；
  依赖 pytest fixture 的测试文件需在 CI 验证。
- 提交前静态预检：`py_compile` + 自写 AST 扫描（未使用变量、字段引用）。
  CI 的 ruff/mypy/coverage 都与基线（`docs/quality-baseline-2026-08.json`）比对，
  **新增任何违规（含 F841 未使用变量）都会红**。
- CI（`.github/workflows/ci.yml`）只在 `push: master` 与 `pull_request` 触发，分支推送不跑，
  必须开 PR。所有门禁 `if: always()`，一次暴露全部问题；`gh run watch --exit-status` 等待结果。
- 推送 amend / force-push 会触发新的 CI run。

### GitHub PR 链

- 本地 master / 远端引用可能陈旧。判断“某 PR 是否已落地”用 **tree 对比**
  （`git diff origin/master <sha> --stat` 为空即内容一致），不要只看 commit 祖先——
  本项目用 squash 合并并删除中间分支，历史拓扑不可靠。

### 分层重构（改 Kernel 层代码）

- 四层边界由 `tests/architecture/*`（AST 门禁）+ `_boundaries.py` + import-linter 强制执行，
  并被 `.trellis/spec/backend/*.md` 记录。动 Kernel 层代码前先读
  `four-layer-ownership.md` / `runtime-boundaries.md`，改完同步更新架构测试期望值与 spec，
  否则 CI 红。
- 删除跨层特殊行为的验证路径：改 → `py_compile` → 定向 unittest → 全量可跑 unittest →
  用架构测试 helper（`_tree` / `_class_annotated_fields` / `_attribute_call_sites` 等）写临时脚本
  复核门禁 → 提交 → 推送 → 等 CI。
- 被移除行为（等待 re-home）的测试用 `@unittest.skip(_REHOME)` 标注恢复条件，跟随
  `tests/memory_runtime/test_core_integration.py` 的 PR1 模式，保留文档价值与恢复点，不要删除。

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
