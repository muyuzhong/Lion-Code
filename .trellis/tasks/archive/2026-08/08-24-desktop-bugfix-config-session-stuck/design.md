# 设计：桌面客户端配置持久化、消息无响应与空会话落盘修复

## 背景与根因

三个 bug 归属 Python 配置层 / 应用会话层 / Renderer 运行时投影。均已在源码与实测确认（R1、R3 根因确定，R2 需复现定稿）。

### R1 配置重启后清空 —— 根因确定（已实测复现）

`lion_code/config.py::resolve_api_credentials` 的优先级缺陷：

```python
if source_env.get("OPENAI_API_KEY") and source_env.get("OPENAI_BASE_URL"):
    ...  # 进入此分支后 model 恒为 None
elif source_env.get("ANTHROPIC_API_KEY"):
    ...
elif source_env.get("OPENAI_API_KEY"):
    ...
if api_key is None:
    saved = load_api_config(config_path)
    if saved.get("api_key"):
        ...
        model = saved.get("model") or None
```

- 实测：写入 `{provider:anthropic, model:claude-sonnet-4-6, api_key, base_url}` 后，
  - 无 env：读回正确（`model=claude-sonnet-4-6`）；
  - **env 存在 `OPENAI_API_KEY+BASE_URL`：返回 `{use_openai:True, model:None}`** —— 已保存 model 被丢弃，`build_session` 回落默认 `claude-opus-4-6`。
- 连带后果：模型名与 provider 可能错配（config 存 anthropic 模型，env 却走 openai 通道），向 OpenAI 端点发 claude 模型名 → 无效请求/挂起，加剧 R2。

**修复设计（最小，不引入新抽象）**：调整 `resolve_api_credentials`，把 config 的读取与 env 的 key/base 覆盖解耦：
- env 只负责提供 `api_key`（和对应 `api_base`）；
- `model` 始终从 config 读回（config 没有才为 None，由调用方回落默认）；
- 保持 `allow_placeholder` 现有语义（无任何凭证时的占位端点）。

需要同时修正 `build_session`（sidecar.py）：`model = saved model` 的语义稳定后，`creds["model"] or "claude-opus-4-6"` 自然正确，若 provider 因 env 覆盖而变成 openai-compatible 但 model 是 anthropic 模型名，属用户选择，不在本任务强制归一（无信号可判断用户意图）。

### R3 新建会话立即落盘 0 消息 JSONL —— 根因确定

链路：`POST /api/sessions/new → session.new_session() → AgentRuntime.new_session → SessionRuntime.new_session → _reset_recorder(...)` → 末尾 `ensure_ready()` → `SessionRecorder._initialize_unlocked()` **无条件写 3 行初始 Entry**（SessionInfo/ModelChange/ThinkingLevelChange），即使消息数为零。

`SessionRepository.list_sessions` 对所有 `.jsonl` 都列，`messageCount` 取 `len(state.messages)`，因此空会话出现在侧栏且每次点"新建"递增。

**修复设计**：把 Recorder 的磁盘初始化从 `new_session` 强制路径中移除——**延迟到首条真实消息（`record_message`）才创建文件**。

- `SessionRecorder._initialize_unlocked()` 拆分：
  - `ensure_ready`/启动时：若文件已存在，做恢复（`_restore_existing`）；若不存在，**不再写入初始元数据**，只标记 `_initialized` 前的"未落盘"态。
  - 首次 `record_message`：先写初始元数据（SessionInfo/Model/Thinking），再写该消息，一次性完成。
- `new_session` 后不调用会写盘的 `ensure_ready`（或 `ensure_ready` 只在已有文件时恢复写位置）。
- `SessionRepository.list_sessions`：**有数据时自然带 messageCount；0 消息且未落盘的会话不产生文件，天然不出现**。对磁盘上历史遗留的 0 消息文件保持不动（遍历成本不变，无额外过滤）。
- 内存态（`messages`、`/api/status.session_id`）不受影响：`new_session` 仍更新 SessionIdentity，Recorder 对象仍被创建（只是不落盘），首条消息触发初始化后会话 ID 落到磁盘。

风险点：`compact_if_needed` / `record_configuration_change` 在 0 消息时也可能触发 Recorder 初始化 → 需保证这些路径与 `record_message` 走同一"未落盘→写初始元数据"逻辑，避免配置变更在无消息时创建文件（同样延迟或只写已有文件）。验收以"0 消息会话不产生 JSONL"为准。

### R2 发送消息后无回应 / 卡住 —— 需复现，给出候选根因

候选根因（按概率排序）：

1. **`AgentRuntime.chat()` 在 `api_configured == False` 时静默 return**（只 `_emit_notice` 发 `notice` 事件，不发任何 message 事件）。而前端 `reduceServerEvent` 的 `case "notice": return state` **直接丢弃 notice** → 用户看到"发了消息、没有 assistant 消息、也没有错误提示"= 无回应。`_drive` 结束后仍 yield `AgentSettledEvent`，`isStreaming` 会复位，但 UI 无任何可见反馈。
2. **env 覆盖导致 model 与 provider 错配（承接 R1）**：如 e2e `sidecar-real` 那样设置 `OPENAI_API_KEY + OPENAI_BASE_URL` 时，config 的 anthropic 模型名发到 openai 端点 → 请求 4xx/5xx 或长时间挂起重试 → UI 表现"卡住不动"。
3. **WS 竞态**：`sendInput` 返回 false（socket 未 OPEN）→ `onNew` throw `"WebSocket 未连接"`，而 `isSendDisabled` 只读 `transportStatus`，可能发生 message 已进 composer 但发送抛错被 assistant-ui 吞掉的卡顿。

**复现/定稿方案**（实现阶段先做，定稿后再写修复）：
- 用 `desktop/e2e/sidecar-real.spec.ts` 的真实 Python sidecar + `LION_SIDECAR_STATE_HOME` 独立 home，设置"config 已保存但无 env"与"config + env 覆盖"两组，在 UI 发送消息并断言返回值 / 可见状态。
- 用纯 Python 集成测试（起 `create_app` + 真实/桩 Provider）覆盖 `AgentRuntime.chat` 静默 return 路径，断言 WS 下发的 event 序列。

修复方向（定稿后按实际根因取舍，均为最小改动）：
- 若为 (1)：`api_configured == False` 时不再静默——`chat()` 直接让 harness 产出一条带 error 的 assistant 消息（走正常事件流），或前端 `reduceServerEvent` 把 `notice` 映射为可见错误状态。优先后端产出 error 消息（保持前端纯投影，不动协议）。
- 若为 (2)：R1 修复后自然缓解；必要时 `sidecar.py` 在 provider 错配时不启动（无信号，倾向不做）。
- 若为 (3)：`sendInput`/`onNew` 使失败显式化（setTransport error + 不移除消息），保持协议不动，仅改动 `lionRuntime.ts` + `assistantRuntime.tsx`。

## 边界与约束

- **不改 wire 协议**（ClientAction/ServerEvent 字段不变），若 (1) 修复选择"产 error 消息"，产的是既有 `turn_end`/`message` error 语义。
- **不改 08-24 纯 UI 移植范围的文件**（展示组件、styles.css 未提交改动保持原样）。
- Python 侧改动限定 `lion_code/config.py`、`lion_code/session_runtime/recorder.py`、`lion_code/runtime/session.py`，可能涉及 `lion_code/adapters/*`、`lion_code/application/session.py`、`lion_code/runtime/agent.py`、`lion_code/sidecar.py`（任一 Kernel 层改动同步架构测试期望值）。
- 不新增依赖，复用 `pytest/tmp_path`、`tests/server`、`desktop/tests/renderer`、e2e 既有基座。

## 测试策略

- R1：`tests/` 下 `resolve_api_credentials` 四象限单测（无凭证 / config 无 env / config+env key / env key+config model）。
- R3：SessionRecorder/SessionRepository——`new_session()` 后无文件；首条 `record_message` 后文件存在且含 3 行初始 Entry + 消息；`list_sessions` 不列空会话。
- R2：集成测试（create_app + 桩 Provider）断言未配置时 WS 有可见 error 事件；e2e 用真实 sidecar 手动冒烟发送消息出现回复/错误。
- 全量质量门禁：`python -m ruff check lion_code tests scripts` 与基线比对、`py_compile`、`npm test`、`npm run typecheck`、`test:e2e --project=chat-protocol`。

## 回滚点

三个修复相互独立，各自单 commit 可单独回滚：
- R1：回滚 `config.py` 补丁即恢复 env 优先旧行为；
- R3：回滚 Recorder 延迟初始化；
- R2：回滚对应的 chat 错误产出 / notice 展示改动。
不涉及 schema 迁移或数据格式变化（JSONL Entry 结构不变）。
