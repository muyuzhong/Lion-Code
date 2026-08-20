# PR4 技术设计 — Product Adapter / Feature Cohesion

## 一、删除 Agent 继承

### 1.1 目标依赖链

```
LionCodingSession (application)
    ↓
CodingSessionBackend protocol (application.ports)
    ↑ 结构化实现
CodingSessionBackendAdapter (adapters)
    ↓ 委托
MetaAgent + product controllers (interaction/capability 产物)
    ↓
AgentRuntime → Kernel
```

### 1.2 MetaAgent 通用缺口（仅 generic 投影，无产品职责）

现有 `CodingSessionBackend` protocol 需要而 MetaAgent 缺失的能力，全部是通用对话/Provider 只读投影，补入 MetaAgent：

| 新增成员 | 实现 | 理由 |
|---|---|---|
| `queue_snapshot() -> QueueSnapshot` | `self._conversation.queue_snapshot()` | steer/follow_up 的只读对偶 |
| `async compact_for_overflow() -> bool` | `self._agent_runtime.compact_for_overflow()` | 通用上下文溢出恢复 |
| `is_running: bool`（property） | `self._conversation.is_running` | 通用运行状态 |
| `api_configured: bool` | `self._provider_controller.api_configured` | 通用 Provider 投影 |
| `provider_name: str` | `self._provider_controller.view.provider_kind` | 通用 Provider 投影 |

**禁止**进入 MetaAgent：list_sessions/restore_latest/legacy 迁移、show_cost、set_terminal_output、Plan toggle/approval、notice/confirm 实例回调。

### 1.3 `adapters/coding_session_backend.py`

```python
class CodingSessionBackendAdapter:
    """FullProfile 产品的 CodingSessionBackend 组合适配器。"""

    def __init__(
        self,
        *,
        agent: MetaAgent,
        plan: PlanRuntime,                      # FullProfile 必含，factory 已断言
        confirmation: ConfirmationController,
        notices: NoticeController,
        status_sink,                            # SubagentStatusSink
        terminal_output_sink: Callable[[bool], None],  # 覆盖 AgentRuntime renderer 开关
        session_repository: SessionRepository,
        cwd: Path,
    ) -> None: ...
```

职责映射（全部委托，无继承）：

- **ConversationPort**：messages/subscribe/prompt/continue_/steer/follow_up/queue_snapshot/cancel/cancelled/compact_for_overflow → `agent.*`
- **SessionPort**：session_id/new_session/compact/aclose → `agent.*`；list_sessions/resume/restore_latest → 自有实现（JSONL + legacy JSON 统一枚举、迁移），从旧 `Agent` 平移
- **SettingsPort**：model/provider_name/permission_mode/api_configured/provider_config/configure_provider/thinking_* → `agent.*`；cwd → 构造注入；set_terminal_output → `terminal_output_sink` + confirmation/status_sink 标志
- **UsagePort**：token_usage → `agent.usage`
- **ControlPort**：set_confirm_fn → confirmation；set_notice_fn → notices；set_plan_approval_fn/toggle_plan_mode → plan
- **产品便利 API**（REPL/CLI 用）：`chat`、`abort`、`is_aborted`、`is_processing`、`clear_history`（=new_session）、`show_cost`（usage+budget 投影，从旧 Agent 平移）、`restore`/`restore_latest`/`latest_session_id`

legacy session 迁移（`_migrate_legacy_core_session`）从旧 Agent 原样平移：所需 model/thinking_level 取自 `agent.model`/`agent.thinking_level`，cwd 取构造注入。

### 1.4 公共构造入口

同文件提供 factory（Composition Root 语义的 Full 产品装配）：

```python
def build_full_coding_backend(
    *, permission_mode, model, api_base, anthropic_base_url, api_key,
    thinking, max_cost_usd, max_turns, terminal_output=True,
    custom_system_prompt=None,
) -> CodingSessionBackendAdapter:
```

- 内部：构造 `AgentConfig` + `RuntimeBindings`（含 `_agent_*` 默认绑定，从旧 `Agent.__init__` 平移）→ `build_agent_composition(FullProfile(...))` → 直接以 `composition.runtime.*` 构造 `MetaAgent` → 断言 Full 专属字段非 None → 组装 Adapter。
- `__main__.py`：`from .adapters.coding_session_backend import build_full_coding_backend`；REPL/TUI/one-shot 全部改走 Adapter（`LionCodingSession(backend=adapter)`）。
- 旧 `Agent.__init__` 的 `config=`/`bindings=` 双轨参数、`tool_registry`/`confirm_fn` 等 legacy 依赖参数**不再保留**——测试需要的注入点直接用 `build_profile_agent` / `build_coding_agent` / `build_meta_agent`（现有公共路径）或给 factory 加显式参数。

### 1.5 monkeypatch seam 处理

旧 `lion_code.agent._agent_provider_factory` 保留的 `create_provider` 动态 seam：删除后测试改为 monkeypatch 真实工厂 `lion_code.providers.factory.create_provider`（`ProviderBindings.provider_factory` 默认引用同一函数对象）。

### 1.6 删除清单

- `lion_code/agent.py` 整文件（含 `Agent`、`_agent_*` 默认绑定、`AgentRunResult` re-export）。
- `lion_code/__main__.py` 中 `Agent` 引用。
- 13 个测试文件的 `from lion_code.agent import Agent` → 按语义迁移：
  - 产品级（CLI/TUI/application/integration/capability migration/hooks）：`build_full_coding_backend()`
  - 只需通用 Agent 语义的：`build_profile_agent(FullProfile/CodingProfile...)` 或 `build_coding_agent`
  - 依赖旧 `_execute_tool_call`/`_confirm_dangerous` seam 的测试：改走 `tool_runtime.execute` + `ConfirmationController` 真实路径

## 二、Feature Cohesion

### 2.1 移动表（见 prd.md R2）

额外说明：

- `capabilities/plan/runtime.py` 保留 `PlanView`/`PlanState`/`PlanToolOutcome`（量小，不单拆 types.py）。
- `capabilities/subagent/types.py` = 旧 `lion_code/subagent.py`（agent 类型注册、提示词、`get_sub_agent_config`、ToolSelectionPolicy 预设）。
- `capabilities/skill/discovery.py` = 旧 `lion_code/skills.py`（SKILL.md 发现/解析/执行查找）。
- `application/skills.py`（Skill 视图 dataclass）**不动**，只改 import。

### 2.2 capabilities/__init__.py 收窄

只导出 generic SPI：`CapabilitySpec`、`CapabilityRegistry`、`CapabilityRuntime`、`DuplicateCapabilityError`、五个 slot Protocol。feature 符号（`create_plan_capability` 等）从 `lion_code.capabilities.plan/skill/subagent` 包导入；`composition/agent_builder.py` 改为从 feature 包导入。

### 2.3 import-linter / 架构门禁同步

- `capabilities/plan|skill|subagent` 可以 import `capabilities.types`（相对 `.types`）、`tooling`、`usage`，不得 import `composition`/`application`/`adapters`。
- `supervisor.py` 不得 import `adapters`（新增门禁）。
- `application`/`tui` 不得 import `composition` 之外的更深层与 `runtime`（现有门禁保持），并确认不 import Harness。

## 三、不改动项

- `composition/agent_builder.py` 的 capability 构造分支逻辑不动（只改 import 源）。
- 三个 Profile 定义、`build_profile_agent`/`build_coding_agent`/`build_meta_agent` 不动。
- Supervisor Plane（PR10 任务另行处理）不动，只加"不 import adapters"门禁。

## 四、风险与回滚

- 最大风险：13 个测试文件的 Agent 迁移中行为 seam 丢失（monkeypatch `lion_code.agent.Agent` 类属性等）。逐文件迁移、每步跑定向测试。
- 行号漂移会触发 quality baseline 指纹告警：随代码更新 `docs/quality-baseline-2026-08.json` 对应条目。
- 回滚点：commit 按"移动 feature 文件 → 建 Adapter → 删 agent.py → 测试迁移 → 门禁/文档"分步提交，任一步可单独 revert。
