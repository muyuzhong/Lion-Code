# PR1 修复默认 Full 项目指令加载

Parent：`08-22-memory-system-design-convergence`（对应其 implement.md 的 PR1 段）

## Goal

让已有 AGENTS/CLAUDE loader 真正进入默认 Full product 的 system prompt，先修复“规则根本没被看见”的根因。当前 `lion_code/prompt.py` 已实现 `load_project_context_files()` / `load_claude_md()`，但生产代码没有调用，导致 root-to-cwd 的项目指令未进入模型。

## Requirements

- R1：默认 Full product 的 dynamic prompt 构造中实际加载 root-to-cwd 的 AGENTS.md / CLAUDE.md，复用现有 `load_project_context_files` / `load_claude_md`，不增加第二个 loader 或 cache。
- R2：保持现有加载语义：同目录 AGENTS 在 CLAUDE 后、子目录在父目录后；空文件跳过；重复加载遵循现有实现行为。
- R3：不读取 Trellis/Skill 文件，不写回项目文件，不引入 Memory 依赖。
- R4：custom prompt 路径现有语义不变（不因本改动破坏 custom prompt 组合）。
- R5：当前用户、系统/开发者指令优先级高于项目指令；项目指令只是追加，不覆盖。

## Acceptance Criteria

- [ ] 为 root-to-cwd 顺序、同目录 AGENTS 后于 CLAUDE、空文件、custom prompt 共存增加测试（`tests/test_prompt.py`）。
- [ ] 默认 Full product 构造的 system prompt 含项目指令内容（集成层面测试）。
- [ ] 不新增第二个 loader/cache 代码路径。
- [ ] 同步 prompt/composition 相关 spec 与测试期望。
- [ ] CI 基线全绿，无新增违规。

## Out of Scope

- Memory 系统本身（PR3/PR4）。
- Session handoff（PR2）。
- 自动写回 AGENTS、修改 AGENTS 内容。

## 回滚点

回退接线 commit 即可，无持久数据变化。
