# 执行计划：桌面客户端配置持久化、消息无响应与空会话落盘修复

## Gate 0：基线隔离

1. 确认工作树脏改动均为 WSL/CRLF 行尾假阳性（AGENTS.md §行尾假阳性），`git diff --stat` 复核真实内容；不批量提交 `.trellis` 噪音。
2. 确认 `desktop/src/renderer/src/styles.css` 用户未提交修改不被覆盖（不 `git checkout` 该文件、不暂存它）。
3. 确认当前 `task.py current` 指向本任务（in_progress 后）。

## 实施顺序（三个独立 commit）

### 第一步：R1 配置持久化（commit 1）

1. 修改 `lion_code/config.py::resolve_api_credentials`：env 只覆盖 api_key/base_url，model 始终从 config 读回；保持 allow_placeholder 语义。
2. 确认 `lion_code/sidecar.py::build_session` 无需额外改动（`creds["model"] or 默认` 自然生效）。
3. 新增/更新单测（`tests/` 下 config 相关）：四象限覆盖。
4. 验证：`py_compile` + 定向 unittest + ruff + mypy + 与基线比对。

### 第二步：R3 空会话落盘（commit 2）

1. 修改 `lion_code/session_runtime/recorder.py`：`_initialize_unlocked` 拆分"已有文件恢复写位置"与"新文件首次写入初始元数据"；初始元数据在首次 `record_message` 时写，其余读写路径（record_model_change / record_thinking_level_change / record_compaction / context_entry_ids）复用同一惰性初始化。
2. 修改 `lion_code/runtime/session.py`：`new_session` / `ensure_ready` 不再强制写盘（新文件场景）；`ensure_ready` 保留"已有文件恢复"。
3. 排查 `AgentRuntime.new_session _注意 ensure_ready 调用` 与 `compact_if_needed` 在 0 消息时的行为，回归相关测试。
4. 单测：new_session 后无文件；首条消息后文件存在且 Entry 含初始三行 + 消息；list_sessions 无 0 消息会话。
5. 架构测试：若改动触及 Kernel 层边界，同步 `tests/architecture/*` 期望值与 `.trellis/spec/backend/*.md`。

### 第三步：R2 消息无响应（commit 3）

1. **先复现定根因**：集成测试（create_app + 桩 Provider）断言未配置 API 时 WS 事件序列；用 `desktop/e2e/sidecar-real.spec.ts` 真实 sidecar 冒烟。
2. 按 design.md 候选根因收敛实际根因，选最小修复（优先后端 chat 产出 error 消息，保持前端纯投影）。
3. 回归测试覆盖"未配置时发送有明确反馈""已配置时正常流式"。
4. Renderer 侧如需改动（lionRuntime.ts/assistantRuntime.tsx），补 `desktop/tests/renderer` 用例。

## 验证（每步 + 总验收）

```bash
# Python 门禁
python -m ruff check lion_code tests scripts --output-format=json > ruff.json
python scripts/check_quality_baseline.py ruff-check ruff.json --status 1 --baseline docs/quality-baseline-2026-08.json
python -m mypy lion_code
python scripts/check_quality_baseline.py mypy mypy.txt --status 1 --baseline docs/quality-baseline-2026-08.json
# pytest
PYTHONPATH=tests python3 -m unittest discover tests -p "test_*.py"
# 指定回归
python3 -m unittest discover tests -p "test_config*.py" -s .  # 按实际路径

# Desktop
cd desktop
npm test
npm run typecheck
npm run test:e2e -- --project=chat-protocol --workers=1
npm run test:e2e -- --project=sidecar-real --workers=1
```

- 确认 `git diff --stat` 只含真实改动；不提交 styles.css。
- R3 手工冒烟：连续点 5 次新建任务，`~/.lion-code/sessions`（或 LION_SIDECAR_STATE_HOME 下）不新增文件，侧栏会话数不涨；发一条消息后出现一个会话。

## Review Gate

- R1：env 与 config 优先级是否符合"env key + config model"预期；无回归到 CLI/TUI 启动路径。
- R3：延迟初始化不破坏：会话恢复（已有文件）、配置变更 Entry、压缩、子 Agent 不落盘（is_sub_agent 分支）。
- R2：未配置时用户能在 UI 看到明确错误；已配置路径端到端正常；不新增协议字段。
- 三 commit 各自可回滚；diff 不含 styles.css 与 .trellis 噪音。

## 回滚点

见 design.md §回滚点：三个独立 commit，无 schema 迁移；任一可单独 revert。
