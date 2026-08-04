# 第四阶段：运行时边界可执行约束实施计划

## 实施顺序

### Step 1 — 建立架构扫描测试骨架

- 新建 tests/architecture/test_runtime_boundaries.py。
- 实现源码枚举、AST 解析、绝对/相对 Lion 导入归一化和函数作用域定位辅助函数。
- 先为当前已确认的合法形态写测试，再为每条规则增加最小 AST fixture，证明违规节点会被识别。

验证：

~~~text
python -m pytest -q tests/architecture/test_runtime_boundaries.py
~~~

### Step 2 — 固化符号与所有权不变量

- 加入 Provider 私有 history、旧消息路径、全局 set_sink、SessionRecorder 构造 allowlist、JSONL writer 旁路和 Memory Harness mutation 扫描。
- 将 legacy migration 的唯一例外写入测试常量和失败信息。
- 不修改 lion_code 运行时实现；若扫描揭示现状违规，先回到设计审查，而不是为使门禁变绿而扩大例外。

验证：

~~~text
python -m pytest -q tests/architecture/test_runtime_boundaries.py tests/memory_runtime/test_injector.py
~~~

### Step 3 — 收紧 import-linter 合同

- 将 pyproject.toml 的过窄 TUI 合同替换为完整运行时边界合同。
- 增加 Core 和 Providers 合同，保留 Application 与产品反向引用合同。
- 执行 lint-imports --no-cache；仅在与设计冲突的真实依赖出现时修订设计，不以 allow_indirect_imports 掩盖回归。

验证：

~~~text
lint-imports --no-cache
~~~

### Step 4 — 同步文档

- 在 .trellis/spec/backend/runtime-boundaries.md 增加 Executable Enforcement 小节，链接合同、架构测试、迁移 writer 例外和本地复现命令。
- 更新 docs/quality-baseline-2026-08.md 的 import-linter 合同数量与清单。

### Step 5 — 全量验证与审查

- 运行受影响测试、完整 pytest、compileall、lint-imports 和 diff 检查。
- 运行 Trellis 任务校验。
- 使用 trellis-check 进行跨层质量复核；若发现规则过宽、漏检或文档漂移，修复后完整重跑。

验证：

~~~text
python -m pytest -q tests/architecture/test_runtime_boundaries.py tests/memory_runtime/test_injector.py
lint-imports --no-cache
python -m pytest -q
python -m compileall -q lion_code tests
git diff --check
python ./.trellis/scripts/task.py validate 08-04-executable-runtime-boundaries
~~~

## 修改范围

- pyproject.toml
- tests/architecture/test_runtime_boundaries.py（新增）
- .trellis/spec/backend/runtime-boundaries.md
- docs/quality-baseline-2026-08.md
- .trellis/tasks/08-04-executable-runtime-boundaries/ 下的规划与上下文记录

## 不触碰

- lion_code/ 的运行时代码
- .github/workflows/ci.yml（现有 CI 已执行 import-linter 和 pytest）
- docs/tui-migration-audit.md、tests/application/test_coding_session.py、.trellis/tasks/08-01-quality-baseline/

## 回滚

若规则造成未预期的合法路径失败，先以 AST 位置和 import-linter 路径为依据确认它是否属于文档允许的边界；只有确认是合法例外时，才同步更新设计、规范和显式 allowlist。不得通过关闭合同、放宽 allow_indirect_imports 或删除测试来规避问题。
