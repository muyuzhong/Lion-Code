# 项目约定

## 注释原则

- 注释只补充代码无法直接表达的信息：设计原因、业务规则来源、不变量、兼容/性能/安全约束。用准确命名、类型和函数拆分表达"做什么"，不逐行翻译代码。
- 公共接口的文档注释说明契约、边界、副作用和异常；简单私有实现不强制。
- 临时方案用 `TODO(issue): 原因与完成条件`，不留无负责人、无期限的 TODO。
- 注释与代码不一致按缺陷处理，改实现时同步更新或删除。源码注释用中文，标识符和必要术语保留英文。

每完成单次改动都进行提交，并添加中文描述

# 项目原则

1. 不保留向后兼容。过时的直接删，别加兼容层、别写migration、别留fallback。
2. 选能满足当前需求的最简单实现，先跑通最小端到端版本再往上加。不预防性抽象、不加多余的配置层，绝不为未完成的复杂度拆掉能跑的东西。
3. 组件保持模块化，关注点分离。
4. 优先用成熟的、有人维护的库；先翻项目已有依赖能做什么，别假设库里没有，别自己重写。
5. 架构决策往长了做，不接受"先这样以后再换"。先看成熟产品怎么解决同一问题，用已验证的模式。

## PR 规范

- 一个 PR 只承载一个职责迁移或一个独立改动（保证可单独回滚），不攒多个子阶段。
- PR 描述必须包含：迁移的状态所有权、保持不变的不变量、测试矩阵、行数与依赖变化、回滚点。
- 大于 10 个提交或 20 个文件的 PR 需要拆分，机械重命名或自动生成除外。

## 工程经验（CI 门禁 / 分层重构）

### 本地验证与 CI 门禁

- 本地快速验证：`PYTHONPATH=tests python3 -m unittest discover tests -p "test_*.py"`；依赖 pytest fixture 的测试文件在 CI 验证。
- **推送前本地跑全套质量门禁并同步基线**，只靠 CI 事后报错＝每轮推送必红一次：
  `python -m ruff check lion_code tests scripts --output-format=json > ruff.json && python scripts/check_quality_baseline.py ruff-check ruff.json --status 1 --baseline docs/quality-baseline-2026-08.json`；
  ruff format / mypy / radon / vulture 同理（调用方式参照 `.github/workflows/ci.yml`）。
- 提交前静态预检：`py_compile` + AST 扫描（未使用变量、字段引用）。CI 的 ruff/mypy/coverage 全部与基线 `docs/quality-baseline-2026-08.json` 比对，**新增任何违规（含 F841）都红**；报 `new fingerprints` 时先看输出：新违规修代码，行号漂移则更新基线条目随代码提交。
- CI 只在 `pull_request` 与 `push: master` 触发（分支推送不跑，必须开 PR），所有门禁 `if: always()` 一次暴露全部问题，`gh run watch --exit-status` 等待结果。
- 行尾假阳性：WSL 编辑写 LF、Windows checkout 是 CRLF（`core.autocrlf=true`），`git diff` 可能把整文件当改动。提交前复核 `git diff --stat` 只含真实内容改动；被污染副本用 `git checkout HEAD -- <file>` 恢复后重编。

### GitHub PR 链

- 判断 PR 是否已落地用 **tree 对比**（`git diff origin/master <sha> --stat` 为空即内容一致），别只看 commit 祖先——squash 合并并删除中间分支后拓扑不可靠。
- **链式 PR 上游合并后必须 rebase 到新 master 再 force-push**，否则 GitHub 报 `CONFLICTING`（squash 后下游里的上游提交与新 master 拓扑对不上）。更稳的重放：`git rebase --onto origin/master <上游分支旧 tip> <本分支>`，只重放本链专属提交；完成后 `git diff <旧 tip> HEAD --stat` 为空即内容零变化，再 `git push --force-with-lease`。冲突时逐文件取语义正确的一侧。
- **链上多条 PR 同时打开时按链路顺序合并**：先合最上游，落地后 rebase 下游、等 CI 绿、再合下一个。下游 CONFLICTING 期间 CI 检出的是分支自身而非 merge 结果，解除冲突后的首轮 CI 才跑真实 merge 结果、才暴露基线违规，必须等这轮绿再合。
- 本地 master 陈旧时先 `git checkout -B master origin/master` 对齐，否则 `gh pr merge` 报 fast-forward 警告（squash 合并实际仍会成功）。

### 分层重构（改 Kernel 层代码）

- 四层边界由 `tests/architecture/*`（AST 门禁）+ `_boundaries.py` + import-linter 强制，`.trellis/spec/backend/*.md` 记录。动 Kernel 层前先读 `four-layer-ownership.md` / `runtime-boundaries.md`，改完同步架构测试期望值与 spec，否则 CI 红。
- 验证路径：改 → `py_compile` → 定向 unittest → 全量可跑 unittest → 用架构测试 helper（`_tree` / `_class_annotated_fields` / `_attribute_call_sites` 等）复核门禁 → 提交 → 推送 → 等 CI。
- 等待 re-home 的被移除行为测试用 `@unittest.skip(_REHOME)` 标注恢复条件（PR1 模式，见 `tests/memory_runtime/test_core_integration.py`），保留文档价值与恢复点，不要删除。

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
