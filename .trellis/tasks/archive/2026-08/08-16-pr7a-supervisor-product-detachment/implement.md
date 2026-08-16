# PR7a Supervisor Product Detachment — Implement

## Ordered checklist

- [ ] 从 `origin/master@ab3261d` 创建/确认 `muyuzhong/pr7a-supervisor-product-detachment`；保留所有
  既有 Trellis/Claude/Codex dirty work，不暂存无关文件。
- [ ] 在 `composition/agent_builder.py` 删除 Supervisor capability 常量、imports、construction branches、
  graph/result fields，并让 Memory 在无 Dream 条件下构造。
- [ ] 在 `session_memory_coordinator.py` 删除 Dream protocol、构造依赖与委托方法。
- [ ] 在 `agent.py` 删除 Supervisor assertions/state/delegates；保留 Capability、provider、permission、
  session、usage 与 application backend 契约。
- [ ] 删除 REPL/Application/TUI 的 Supervisor 命令面及 SubAgent 对 `schedule_wakeup` 的产品特判。
- [ ] 更新架构、composition、MetaAgent、Memory、CLI/Application/TUI 测试；按 `_REHOME` 规则 skip
  Agent-driven Supervisor 集成测试，保留直接 runtime tests。
- [ ] 同步 `.trellis/spec/backend/four-layer-ownership.md`、`runtime-boundaries.md` 与必要测试归属说明。

## Validation

- [ ] `python -m py_compile` 覆盖所有 PR7a 修改的 Python 文件，并运行 AST 残留扫描确认
  Composition/Agent/Product paths 无 Supervisor symbol。
- [ ] 定向测试：architecture bare/composition/runtime boundaries、MetaAgent、SessionMemoryCoordinator、
  CLI/Application/TUI 受影响文件以及独立 Autonomy/Dream/Learning runtime tests。
- [ ] `python -m pytest -q`。
- [ ] `python -m compileall -q lion_code tests scripts` 与 `lint-imports --no-cache`。
- [ ] 按 `.github/workflows/ci.yml` 执行 Ruff check/format、mypy、radon、vulture、coverage baseline gates；
  new fingerprint 修代码，纯行号漂移才更新 `docs/quality-baseline-2026-08.json`。
- [ ] `git diff --check`，并用 `D:\Git\cmd\git.exe diff --stat` 复核无 CRLF 全文件污染。

## Review and commit gate

- [ ] 调度 `trellis-check` 做独立 spec/quality review，修复 findings 后重复相关门禁。
- [ ] 只 stage PR7a 源码、测试、spec 与任务文件；禁止 `git add -A`。
- [ ] 中文提交描述；提交后记录 commit SHA 与 scoped diff stat。
- [ ] PR7a 是 PR7b 的唯一代码基线和独立回滚点；PR7b 不 amend PR7a。
