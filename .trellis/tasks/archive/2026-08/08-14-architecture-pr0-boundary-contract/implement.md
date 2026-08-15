# PR0 四层架构 Implement（父任务：执行编排与集成评审）

父任务不承担子任务实现，只负责执行顺序、评审门与最终集成。子任务各自实现后，由父任务做集成验收。

## 1. 执行顺序

1. **08-14-pr0-boundary-audit**（先做）— 产出 tests → 四层归属清单，落地核心 runtime 测试重分类，更新 spec。
2. **08-14-pr0-event-stream-contract**（可与 1 并行）— Kernel 事件契约声明 + 测试。
3. **08-14-pr0-architecture-gates**（依赖 1 的归属结论）— 四层边界门禁。

依赖：audit 先产出归属，gates 引用之；event-stream 独立。

## 2. 评审门

- 每个 child 完成 → 跑其自带的验收（child implement 中定义）。
- 集成评审（父，PR0 最后一步）：
  - `python -m pytest -q`（全量）
  - `lint-imports --no-cache`
  - `python -m pytest -q tests/architecture/`（AST 门禁）
  - `git diff --check`
  - 质量基线（ruff/mypy/format）不劣化：ruff=218 / mypy=105 / format=146（见 memory quality-baseline）
  - 核对跨 child 验收标准（父 prd.md）

## 3. 集成验收清单

- [ ] `<relevant-memory>`/Plan reset/MCP/SubAgent 测试不再归类于 Core Runtime 必须行为（spec + 测试归属体现）
- [ ] Kernel 事件契约（10 事件）有代码级声明或测试
- [ ] 四层边界有 import/AST 门禁，全量测试通过
- [ ] 无 R5 禁止项（Null/Noop/ServiceLocator/CapabilityContext/build_meta_agent/大规模搬迁/Feature-specific protocol）
- [ ] 现有 Full Product 行为测试保持通过（只重定义归属）
- [ ] 完成后总结输出（父 prd.md 的"完成后需总结"6 项）

## 4. 最终总结要求（PR0 交付）

按父 prd.md 总结：实际架构边界 / 修改内容 / 新增架构测试 / 原方案与真实代码不一致点 / 下一 PR（Memory Runtime hard-chain removal）的真实入口。

## 5. 分支与提交

- 基于 master（本地已含 origin #27）。每个 child 完成后提交。
- 遵循 memory 约定：commit without asking, branch off master first。
- 最终 PR0 合入 master 后再决定推送 origin（是否推交由用户）。
