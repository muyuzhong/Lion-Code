# PR7b MCP Total Removal — Implement

## Dependency gate

- [x] PR7a 实现提交 `d74f42a` 已完成轻量核验；PR7b 以 PR7a branch 为唯一代码基线。
- [x] 创建/切换 `muyuzhong/pr7b-mcp-total-removal`，保留 unrelated dirty files，不使用 `git add -A`。

## Ordered checklist

- [x] 删除 MCP 专用源码与直接测试：client、Capability、tool adapter、ToolEnvironment。
- [x] 从 Composition constants/graphs/builders/ports 删除 MCP selection、state、manager、capability 与
  environment；临时 `PRODUCT_CAPABILITIES` 只剩 Skill/SubAgent/Plan/Memory。
- [x] 从 `AgentConfig`、`AgentDependencies`、`AgentComposition`、`Agent`、MetaAgent 删除 MCP 参数、字段、
  properties、assertions、imports 与 compatibility seams。
- [x] 简化 SessionStatePort/SessionLifecycle close chain；SubagentFactory 只共享 selected registry，删除
  ToolEnvironment/child_view 路径。
- [x] 更新 Dream retained adapter、benchmark worker、CLI/Application/TUI/session comments 与受影响测试；
  不恢复 Supervisor 生产 caller。
- [x] 清理 capabilities/tooling exports、import-linter、quality baseline、project docs、tests ownership 与
  backend specs。
- [x] 增加强否定架构断言，禁止 MCP 文件、module import、config/facade/composition fields、capability name
  和 `.mcp.json` 加载逻辑重新出现。

## Validation

- [x] `python -m py_compile` 覆盖修改后 Python 文件；`python -m compileall -q lion_code tests scripts`。
- [x] 残留扫描：`rg -n -i "\bmcp\b|mcp_|mcp__|Mcp" lion_code tests docs .trellis/spec pyproject.toml .github`
  无输出；`rg --files lion_code tests | rg -i "mcp"` 无输出。
- [x] 定向测试：composition/bare/kernel/runtime architecture、Capability lifecycle、ToolRegistry、SubAgent/
  Skill、MetaAgent、Agent close、CLI/Application/TUI、Memory/Plan。
- [x] `python -m pytest -q` 与 `lint-imports --no-cache`。
- [x] 按 `.github/workflows/ci.yml` 执行 Ruff check/format、mypy、radon、vulture、coverage baseline gates；
  删除失效 baseline fingerprints，禁止用基线掩盖新违规。
- [x] `git diff --check`，Windows Git 复核 diff stat/行尾；确认大文件数仅来自 MCP 删除与机械残留清理。

## Review and commit gate

- [x] 调度独立 `trellis-check`（子代理网络不可用，改为逐项自核：残留扫描/删除完整性/行为保持/
  强否定测试有效性/spec 一致性）。
- [x] 只 stage PR7b 源码、测试、spec、baseline 与任务文件；中文提交描述。
- [x] 记录 MCP 删除文件、剩余 Capability 图、测试矩阵、行数/依赖变化与独立回滚命令。
