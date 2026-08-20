# Context Compaction and Projection Hardening — Implementation Plan

## Execution constraints

- 只实现 PRD 的四项修复；不顺手扩展 Capability compaction、ContextLayer 或 Provider 策略。
- 保留用户未跟踪的 `after1.tmp`，始终显式暂存任务路径，不使用 `git add -A`。
- 每完成一个可独立验证的改动即提交，commit subject 使用中文；不直接推送 master，不自动创建 PR。

## Ordered checklist

1. **移除 Plan compaction edge，并收敛 request 输入**
   - 删除 Plan protocol/read helper、Runtime 字段和 Composition 接线。
   - 保留 explicit → recent user → history user → unavailable objective 顺序。
   - 把 `CompactionRequest.recent_context` 替换为 bounded string hint；加入 4,000 chars / 5%
     effective-window 中较小的预算和最小 hint 投影。
   - 更新 compactor prompt、ContextRuntime/AgentRuntime 调用、fakes、unit/integration tests。
   - 增加 FullProfile reachable graph + exact removed coupling 架构门禁。
   - 聚焦验证后提交：`fix: 移除压缩链路的 Plan 依赖并限制近期提示`。

2. **增加九段摘要结构校验**
   - 提取唯一 heading 顺序，增加 `InvalidCompactionSummary` 和轻量 validator。
   - 覆盖合法、缺失、重复、乱序以及 validation failure 不落 CompactionEntry/不替换 history。
   - 保持 Provider error、empty summary 和 cancellation tests。
   - 聚焦验证后提交：`fix: 校验上下文压缩摘要结构`。

3. **限制瞬态状态投影**
   - 把 ContextView activity 改为 8 个 tool totals、3 个 repeated、5 个 recent 的有界快照；
     保持 failure=3 和单条摘要=240 chars。
   - 更新 AgentStateLayer 渲染和长历史测试。
   - GitStatusLayer 渲染 dirty total、前三项和 `... N more`；覆盖 clean/3/>3/rename/重复 render。
   - 聚焦验证后提交：`fix: 限制 Agent 与 Git 状态栏输出规模`。

4. **同步规范与完成门禁**
   - 修正 `.trellis/spec/backend/runtime-boundaries.md` 的 compaction/object graph/status bounds。
   - 运行全量质量门禁，检查 diff/stat、架构边界和 task scope；只修本任务新增问题。
   - 若规范未随前三个提交同步，单独提交：`docs: 同步上下文压缩与状态投影边界`。

## Focused validation

```powershell
python -m compileall -q lion_code tests scripts
python -m pytest -q tests/context/test_compaction.py tests/runtime/test_context_runtime.py
python -m pytest -q tests/context/test_context_layer.py tests/architecture/test_runtime_ownership.py
python -m pytest -q tests/integration/test_application_coding_session.py tests/integration/test_agent_core_runtime.py
git diff --check
```

## Full quality gate

```powershell
python -m pytest -q
python -m ruff check lion_code tests scripts --output-format=json > ruff.json
python scripts/check_quality_baseline.py ruff-check ruff.json --status 1 --baseline docs/quality-baseline-2026-08.json
python -m ruff format --check lion_code tests scripts
python -m mypy lion_code --platform win32 -O json > mypy.jsonl 2>&1
lint-imports --no-cache
```

Radon、vulture、coverage 与 changed-lines coverage 按 `.github/workflows/ci.yml` 的当前命令
执行并与 `docs/quality-baseline-2026-08.json` 比对。基线噪声与 scoped regression 分开报告。

## Review gates before task start

- `prd.md`、`design.md`、`implement.md` 无 blocking open question。
- `implement.jsonl` 与 `check.jsonl` 各有真实 spec/source/test context entry。
- 用户在看到最终 Goal / Scope / Acceptance / Decisions 摘要后，以后续消息明确批准实施。
- 激活实施时从最新 `origin/master` 工作，并再次确认只存在任务改动与保留的 `after1.tmp`。

## Rollback points

- Commit 1：恢复旧 request wiring 会同时恢复旧 Plan edge，只可整体回退该提交。
- Commit 2：移除 validator 即恢复 prompt-only contract，无数据迁移。
- Commit 3：恢复旧 View/layer rendering，不影响 canonical history 或 Session。
