# PR7c Composition Profile Layer — Implement

## Dependency gate

- [x] PR7b 已提交、通过 MCP 残留扫描和全部门禁，当前 branch 基于
  `muyuzhong/pr7b-mcp-total-removal`。
- [x] 创建/切换 `muyuzhong/pr7c-composition-profile-layer`，不带入 unrelated dirty files。

## Ordered checklist

- [x] 新增 frozen Profile values、Facade enum 与 optional SkillComposition；Profile 类型固定表达内置
  Capability 组合，不暴露任意 Capability enum/set；用 AST tests 禁止 feature bool、mutable state、
  builder/service-locator 方法。
- [x] 新增 CommandExecutionBackend/local backend，把 builtin `run_shell` 改为显式 backend binding；更新
  调用方和 fake-backend behavior tests。
- [x] 提取 ToolPermissionStrategy，让 Profile-selected strategy 原样进入 middleware；保持现有
  PermissionPolicy 行为不变。
- [x] 删除 `AgentConfig.custom_system_prompt/custom_tools` 与 `AgentDependencies.extra_capabilities`，把 prompt、
  tools、extension specs 移入 Profile，不留 alias/fallback。
- [x] 把 `build_agent_composition(config, dependencies, capabilities=...)` 收敛为单一 Profile 输入，删除
  capability set API/PRODUCT_CAPABILITIES，归一化 Minimal/Coding/Full 选择。
- [x] Minimal 构造 caller-tool/zero-capability graph；Coding 构造 backend-bound tools 与 optional Skill；
  Full 构造 Memory/Plan/SubAgent/default Skill/extension specs。
- [x] 迁移 build_meta_agent、新增 build_coding_agent、让 Full Agent 使用 FullProfile；MetaAgent 增加通用
  run_once narrow seam。
- [x] SubagentFactory 使用 CodingProfile child graph，验证不会构造 Full-only Capability。
- [x] 增加三种真实 object-graph tests、strong-negative constructor tests，更新 public exports/specs。

## Validation

- [x] `python -m py_compile` 覆盖所有修改文件；AST 扫描 Profile fields 与 Kernel/Harness import/branch。
- [x] 定向测试：profiles、bare/composition/kernel/runtime architecture、MetaAgent、builtin/tool runtime/
  permission、SubAgent/Skill、Plan/Memory。
- [x] `python -m pytest -q`；`python -m compileall -q lion_code tests scripts`；`lint-imports --no-cache`。
- [x] 按 CI workflow 执行 Ruff check/format、mypy、radon、vulture、coverage baseline gates；新 D/E/F
  complexity fingerprint 必须拆 helper，不能只更新基线。
- [x] 运行 executable object-graph probe，记录三种 graph 的 facade、tool names、capability names、backend、
  strategy、prompt layers 与高级对象 presence。
- [x] `git diff --check` 与 Windows Git diff stat/line-ending 复核。
- [x] scoped file count 目标不超过 20；若真实迁移超过门槛，先把 backend/permission seam 拆为独立前置
  PR，不带着超限 PR7c 推送。

## Review and commit gate

- [x] 调度独立 `trellis-check`，修复 spec/architecture/typing/test findings 并重复相关门禁。
- [x] 只 stage PR7c 源码、测试、spec 与任务文件；不使用 `git add -A`。
- [x] 中文提交描述；记录 PR7c commit SHA、相对 PR7b 的 diff stat 与独立回滚命令。
