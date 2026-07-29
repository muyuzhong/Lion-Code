# Tau TUI 融合:架构审计与迁移边界

> 初始审计基线:Lion-Code master `0e31f3b`(PR #12 之后)× Tau `d597a8a`
> (Release 0.3.3,2026-07-25)。阶段 5 复核基线为 Lion master `3370351`
> (2026-07-29,依赖与文档收尾前)。§1–9 保留迁移决策历史,§10–12 描述当前落地状态。

---

## 1. Lion master 已完全替代的 Tau 模块

### 1.1 tau_agent → lion_code/core(全部替代,含本地演化)

| Tau 文件 | Lion 文件 | 差异 |
|---|---|---|
| messages / provider / provider_events / types / events | 同名 | 仅 import 改名,等价 |
| session/entries · jsonl · tree | core/session 同名 | 仅 import 改名,等价 |
| tools.py | core/tools.py | +`AgentToolResult.is_error`(保留权限/Hook/新鲜度结构化失败) |
| loop.py | core/loop.py | +`get_tools`/`get_system` 每轮解析;+`prepare_context` 钩子;+并行工具分批(`_tool_call_batches`/`_run_parallel_tool_batch`);terminate 全量判定 |
| harness.py | core/harness.py | Config +三钩子;中断修复的 ToolResult 以 Message 事件通知持久化订阅者 |
| session/memory.py | core/session/memory.py | 合成摘要 UserMessage 带时间戳 |
| session/storage.py | core/session/storage.py | +fsync;+崩溃残留半行截断(比上游健壮) |

### 1.2 tau_ai → lion_code/providers(选择性替代)

- 已 vendor 且等价(仅改名):`openai_compatible`、`anthropic`、`stream`、`retry`、`http`、`http_errors`、`model_limits`、`_provider_events`、`events`、`provider`;`env.py` → `config.py`。
- Lion 新增:`factory.py`(不读环境变量的纯组装)。
- **未 vendor**:`google.py`、`mistral.py`、`openai_codex.py`;`fake.py` 已在阶段 0 吸收用于应用层/TUI 测试。
- 上游 anthropic.py 的 `thinking_mode == "disabled"` 显式 payload 已在阶段 0 同步。

### 1.3 tau_coding → Lion 既有能力(不 vendor,已有等价物)

| Tau 模块 | Lion 等价 |
|---|---|
| tools.py(read/write/edit/bash) | tooling/(Registry/Runtime/中间件/权限/新鲜度/结果策略) |
| context_window.py | context/(ContextManager,Budget/Snip/Microcompact/自动压缩) |
| session.py 持久化部分 + session_manager.py | session_runtime/(Recorder/Repository)+ core/session;**索引/标题/多会话管理是缺口 → application/session_manager.py** |
| provider_config.py / provider_runtime.py | providers/config.py + factory.py + lion_code/config.py(~/.lion-code/config.json);Lion 面小得多,够用 |
| skills.py | lion_code/skills.py(发现/解析/执行,含 fork 模式) |
| system_prompt.py / context.py | prompt.py(build_static_system_prompt / load_claude_md) |
| oauth 全家桶 / credentials / catalog | **不迁移**(Lion 用 api_key 配置;目录制模型列表非目标) |
| extensions/ 运行时 | **不迁移**(仅 vendor TUI 需要的 markup Protocol 类型) |
| session.py 的 CodingSession 本体 | **缺口 → application/session.py(LionCodingSession,本次核心工作)** |

Lion 独有、Tau 无对应:权限系统、中间件、Hooks、Read Freshness、Result Policy、Memory(coordinator/injector/dream)、Plan、子 Agent、Goal/Loop/Auto、MCP 客户端。

阶段 1–4 已补齐上表当时标记的 `LionCodingSession`、SessionManager、Provider 配置和
Textual 前端缺口；这些“缺口”仅作为初始审计判断保留,不再表示当前待办。

---

## 2. Tau TUI 逐文件依赖图与分类

`src/tau_coding/tui/`(Tau 0.3.3 实测):

| 文件 | 行数 | tau_agent | tau_ai | tau_coding(非 tui) | 分类 |
|---|---|---|---|---|---|
| file_drop.py | 83 | — | — | — | **A 原样迁入** |
| terminal_title.py | 124 | — | — | — | **A 原样迁入** |
| themes/*.json ×3 | 数据 | — | — | — | **A 原样迁入** |
| __init__.py | 69 | — | — | — | B |
| adapter.py | 99 | events, messages | events(Delta×2) | events | **B 改 import** |
| state.py | 552 | messages, tools, types | — | extensions.api(3 个 markup Protocol), skills | **B 改 import+补类型** |
| autocomplete.py | 511 | — | — | commands, prompt_templates, skills | **B 改 import+补类型** |
| config.py | 207 | — | — | paths(TauPaths) | **B 改 import** |
| terminal_notification.py | 115 | — | — | —(仅同包) | **B 随包迁移** |
| widgets.py | 2256 | tools | — | prompt_templates, session_stats, skills, system_prompt, version | **B 改 import+补类型** |
| themes/__init__.py | 459 | — | — | resources(ResourceDiagnostic) | **B 改 import** |
| app.py | 6711 | events, messages, provider, provider_events, tools, types | — | 20+ 模块,深度持有 CodingSession | **C 必须重构** |

关键观察:

1. **风险集中在 app.py 一个文件**——唯一持有并驱动 CodingSession 的地方;其中 24 项能力用 `getattr(session, ...)` 鸭子探测,本已是"可选能力"形态,抽成显式 Protocol 成本低。
2. **widgets.py 已用 `SessionSummarySource`(Protocol) 与会话解耦**(字段:cwd/model/provider_name/tools/skills/prompt_templates/context_files/context_token_estimate/auto_compact_token_threshold/context_window_tokens/thinking_level/session_title/extension_names/session_stats)——LionCodingSession 直接结构化满足它即可。
3. **Delta 事件双源**:adapter.py 从 `tau_ai.events` 取 `TextDeltaEvent/ThinkingDeltaEvent`,app.py 从 `tau_agent.provider_events` 取同名类型。Lion 中 providers/events.py 是 core/provider_events 的纯 re-export(同一对象),迁移时**统一 import 自 `lion_code.core.provider_events`**,消除判型分叉隐患。
4. B 类文件对 tau_agent 的依赖全部是消息/工具/事件 dataclass(无行为),对 tau_coding 的依赖多为只读值类型——都能机械替换。

---

## 3. TauTuiApp 直接依赖的 tau_coding 能力清单

### 3.1 CodingSession 静态访问(22 项)

`skills` `messages` `prompt_templates` `available_models` `available_providers` `provider_name` `model` `tools` `extension_tool_sources` `cwd` `is_running` | `handle_command()` `reload()` `export()` `compact()` `resume()` `prompt()` `set_provider()` `set_model()` `reload_provider_settings()` `emit_pending_session_start()`

### 3.2 getattr 鸭子探测(24 项)

`session_title` `extension_runtime` `queue_follow_up_message` `cancel` `run_terminal_command` `tree_choices` `branch_to_entry` `new_session` `available_model_choices` `scoped_model_choices` `toggle_scoped_model` `set_model_choice` `set_thinking_level` `cycle_thinking_level` `cycle_scoped_model` `available_thinking_levels` `command_registry` `session_manager` `queue_update_event` `last_diagnostic_log_path` `aclose` `session_id` `queued_messages` `is_running`

### 3.3 其它 tau_coding 能力

- **commands**:`CommandRegistry` / `create_default_command_registry` / `CommandResult`(27 个意图标志) / `format_reload_summary` / `LOGIN_PROVIDER_ALIASES`
- **provider_config**:load/save/resolve_provider_selection/resolve_startup_thinking_level/provider_has_usable_credentials/upsert_* 等 11 个符号
- **provider_runtime**:`create_model_provider`
- **oauth/credentials/catalog**:OAuth 屏、FileCredentialStore、BUILTIN_PROVIDER_CATALOG 等(**Lion 不迁移**)
- **session/session_manager**:`CodingSessionConfig` `SessionManager` `CodingSessionRecord` `jsonl_session_storage` `parse_terminal_command` `is_context_overflow_error` `ModelChoice` `SessionTreeChoice/BranchResult` `TREE_RUNNING_MESSAGE`
- **extensions.api**:KeyInterceptor/MainViewFactory/SlotWidget*/Placement(扩展 UI 承载,**Lion 不迁移**)
- **resources/shell_config/version**:TauResourcePaths、load_shell_settings、current_version

---

## 4. 依赖 → Lion 模块映射

| Tau 依赖 | Lion 落点 | 说明 |
|---|---|---|
| CodingSession 全部会话 API | **application/session.py(LionCodingSession,新建)** | 组合(不重写)LionAgentRuntime/ToolRuntime/SessionRecorder/ContextManager/MemoryCoordinator |
| CodingSessionEvent 联合 | **application/events.py(新建)** | 见 §9 |
| CommandRegistry/CommandResult | **application/commands.py(新建,vendor 注册表骨架)** | autocomplete.py 与 app.py 共同依赖其形状,值得按 Tau 结构 vendor 后填 Lion 命令 |
| SessionManager/CodingSessionRecord | **application/session_manager.py(新建)** | 底层复用 session_runtime.SessionRepository;补索引/标题/touch 语义 |
| provider_config.* / provider_runtime.create_model_provider | **application/provider_settings.py(新建,薄)** + providers/factory + lion_code/config.py | Lion 不做目录制;ModelChoice 从保存的配置合成 |
| tau_agent.*(events/messages/provider_events/tools/types) | lion_code.core 同名 | 机械替换;Delta 事件统一 core.provider_events |
| tau_ai.events | lion_code.core.provider_events | 消除双源 |
| skills.Skill / parse_skill_invocation | lion_code.skills | 对齐字段(name/path/content/description);缺的解析函数补上 |
| prompt_templates.PromptTemplate | application 新建 dataclass(阶段 4 可选实现发现逻辑) | 先空元组占位 |
| session_stats.SessionStats | 由 observers.UsageObserver.totals 合成 | turn/tool 计数入 LionCodingSession |
| system_prompt.ProjectContextFile | prompt.py 侧新建轻类型(path) | 对应 CLAUDE.md/AGENTS.md 发现 |
| extensions.api 三个 markup Protocol | **tui/markup.py(新建,仅 Protocol 定义)** | state/widgets 保持可用,无扩展运行时 |
| resources.ResourceDiagnostic | tui/themes 本地化定义或 application 轻类型 | 仅主题诊断用 |
| paths.TauPaths | `~/.lion-code`(lion_code/config.py 常量) | tui.json 落 `~/.lion-code/tui.json`(与现 TUI 一致) |
| version.current_version | lion_code 包版本 | pyproject 单源 |
| shell_config / oauth / catalog / extensions 运行时 | **裁剪** | 阶段 3 重构 app.py 时删除相关屏与分支 |

---

## 5–7. 迁移方式三分类(结论)

- **5. 原样迁入(A)**:`file_drop.py`、`terminal_title.py`、`themes/*.json`。
- **6. 只改 import(B)**:`__init__.py`、`adapter.py`、`state.py`、`autocomplete.py`、`config.py`、`terminal_notification.py`、`widgets.py`、`themes/__init__.py`——其中 state/autocomplete/widgets 需要 §4 的少量补型(Skill/PromptTemplate/SessionStats/ProjectContextFile/markup Protocol/ResourceDiagnostic),均为只读数据类型,不引业务。
- **7. 必须重构(C)**:`app.py`(6711 行)。重构内容:
  1. 面向 LionCodingSession 协议而非 Tau CodingSession;
  2. 删除 OAuth 登录屏、provider catalog、custom provider 登录、extensions UI bridge(KeyInterceptor/MainView/Slot);
  3. 接入 Lion 特有交互:权限确认 Modal、Plan 审批 Modal(现 tui.py 已有实现可移植);
  4. 命令分派对齐 application/commands.py 的 CommandResult 意图集(裁掉 login/logout/catalog 相关标志);
  5. 保留:transcript 渲染循环、事件适配、补全、picker 框架、主题、队列显示、终端标题/通知。

---

## 8. LionCodingSession 最小公共接口

落点 `lion_code/application/session.py`。**组合现有组件,严禁重写 Agent Loop**;第一版允许内部持有现 `Agent` 实例作为实现细节,对外只暴露本协议,后续把组装职责逐步上移、Agent 瘦身。

```python
class LionCodingSession:
    # -- 环境/身份 --
    cwd: Path
    session_id: str | None
    session_title: str | None          # 阶段 4 前可恒 None

    # -- 运行控制(核心) --
    def prompt(text, *, streaming_behavior: Literal["steer","follow_up"] | None = None
        ) -> AsyncIterator[LionSessionEvent]     # 运行中未指明行为则 RuntimeError
    async def continue_() -> AsyncIterator[LionSessionEvent]
    def cancel() -> None
    is_running: bool

    # -- Transcript / 状态 --
    messages: tuple[AgentMessage, ...]           # canonical,不含 Memory overlay
    queued_steering_messages: tuple[str, ...]
    queued_follow_up_messages: tuple[str, ...]
    def queue_update_event() -> QueueUpdateEvent

    # -- 会话管理 --
    async def list_sessions() -> list[SessionRecord]
    async def resume(session_id: str) -> str
    async def new_session() -> str               # 替代 Tau 的 clear 语义
    async def aclose() -> None

    # -- Provider / 模型 / thinking --
    provider_name: str
    model: str
    available_model_choices: tuple[ModelChoice, ...]   # 从保存配置合成,无目录
    def set_model(model: str) -> None
    def configure_provider(**kw) -> None         # 对应现 Agent.configure_api
    thinking_level: str
    available_thinking_levels: tuple[str, ...]
    async def set_thinking_level(level: str) -> str

    # -- 压缩 / 上下文 --
    async def compact(instructions: str | None = None) -> str
    context_token_estimate: int
    context_window_tokens: int
    auto_compact_token_threshold: int | None

    # -- 命令 / 技能 / 模板 --
    command_registry: CommandRegistry
    def handle_command(text: str) -> CommandResult
    def expand_prompt_text(text: str) -> str
    skills: tuple[Skill, ...]
    prompt_templates: tuple[PromptTemplate, ...]  # 阶段 4 前恒 ()
    tools: tuple[AgentTool, ...]

    # -- Usage --
    session_stats: SessionStats                   # 来自 UsageObserver + 计数

    # -- Lion 特有交互(Tau 无) --
    permission_mode: str
    def set_confirm_fn(fn) -> None                # 权限确认 → TUI Modal
    def set_plan_approval_fn(fn) -> None          # Plan 审批 → TUI Modal
    def toggle_plan_mode() -> None
```

约束:内部必须使用 LionAgentRuntime、ToolRuntime、SessionRepository/Recorder、ContextManager、MemoryCoordinator、providers.factory;不得出现第二套 Agent Loop、第二套会话存储。widgets 的 `SessionSummarySource` 由上述属性结构化满足(`extension_names` 恒 `()`,`context_files` 来自 CLAUDE.md 发现)。

**阶段 1 最小集**:运行控制 + Transcript/队列 + aclose + settle 事件;其余分阶段补。

---

## 9. Lion 应用级事件模型

落点 `lion_code/application/events.py`。采纳 Tau 实际 emit 的事件集(实测 session.py 只 emit 8 种,另 3 种已定义未用),Lion 启用其中有用者并增补:

```
SessionOwnEvent =
    SessionAgentEndEvent(messages, will_retry)      # 包装底层 AgentEnd
  | AgentSettledEvent()                             # 一轮彻底归位(UI 空闲信号)
  | QueueUpdateEvent(steering, follow_up)
  | CompactionStartEvent(reason: manual|threshold|overflow)
  | CompactionEndEvent(reason, aborted, will_retry, error_message)
  | AutoRetryStartEvent(attempt, max_attempts, delay_ms, error_message)
  | AutoRetryEndEvent(success, attempt, final_error)
  | SessionChangedEvent(session_id, reason: new|resume|clear)     # Lion 增补
  | ProviderChangedEvent(provider_name, model)                    # Lion 增补
  | ThinkingLevelChangedEvent(level)                # Tau 已定义未 emit,Lion 启用

LionSessionEvent = AgentEvent | SessionOwnEvent     # AgentEvent 来自 lion_code.core.events
```

要点:

- **不能用 AgentEndEvent 表示 TUI 归位**——AgentEnd 后可能还有溢出压缩、重试、steering 续跑、follow-up 队列;`AgentSettledEvent` 才是空闲信号(Tau 实证语义)。
- 事件次序契约(对齐 Tau):溢出路径 `AgentEnd → CompactionStart(overflow) → CompactionEnd → AutoRetryStart → …续跑事件… → AutoRetryEnd → AgentSettled`。
- 权限确认与 Plan 审批**不走事件**,维持注入式回调(现 Agent 机制),TUI 换模态弹窗——与 docs/tui.md 既有三边界一致。
- Memory overlay 只进 Provider Projection,**不产生 UI 事件**。

---

## 10. 阶段 5 后的实际运行边界

### Agent / Core / Provider

- `Agent` 始终构造 Provider 与 `LionAgentRuntime`;OpenAI-compatible、Anthropic、子 Agent、
  side-query、dream/learning/goal/loop 都复用 canonical Core messages。
- Provider 配置由 Agent 自己保存。空闲态切换会保留 canonical history,原子替换 Provider
  并刷新 compactor、文本查询和模型限制;活动流中拒绝切换。
- 产品代码不导入第三方 OpenAI/Anthropic SDK。两个协议由 `lion_code/providers/` 中基于
  httpx 的实现直接访问。
- `agent.py` 在阶段 5 收敛为 2116 行,没有为行数目标增加包装层。

### TUI / CLI

- 裸运行进入唯一的 `lion_code/tui/` Textual 应用;`--repl` 进入纯文本 REPL;带 prompt
  时执行 one-shot。
- TUI 通过 `LionCodingSession` 消费 Core/application typed events,文本 delta 追加到活动
  stream,工具行原位更新。命令 notice 使用会话级 callback;权限与 Plan 审批使用注入式回调。
- TUI 会关闭 Agent 的终端 renderer,REPL 保留 `ui.print_*` 直写 stdout;不存在进程级
  全局输出 sink。

### Session

- `SessionRecorder` / `JsonlSessionStorage` 是唯一写入路径,新会话只生成 `.jsonl`。
- `session_runtime/legacy.py` 只负责发现、读取并迁移旧 `.json`;迁移输出 JSONL,源文件不
  覆盖、不改名、不删除。

---

## 11. 最终包结构与依赖方向

```
lion_code/
├── core/            # 便携 Agent 内核(≈tau_agent + Lion 演化)
├── providers/       # 模型供应商(≈tau_ai 子集 + factory + fake)
├── adapters/        # ToolRuntime → Core AgentTool
├── tooling/ context/ memory_runtime/ session_runtime/ observers/
├── application/     # 新:应用会话层
│   ├── session.py           # LionCodingSession
│   ├── events.py            # LionSessionEvent
│   ├── commands.py          # CommandRegistry/CommandResult
│   ├── provider_settings.py # 配置解析→factory 参数
│   └── session_manager.py   # 多会话索引/标题(包装 SessionRepository)
├── tui/             # 新:≈tau_coding/tui(app.py 重构版)
│   ├── app.py adapter.py state.py widgets.py autocomplete.py
│   ├── config.py file_drop.py markup.py
│   ├── terminal_title.py terminal_notification.py
│   └── themes/(含 3 个 json)
├── agent_runtime.py agent.py __main__.py ui.py
└── skills.py subagent.py autonomy.py dream.py memory.py prompt.py …
```

依赖单向(违反即架构缺陷):

```
tui → application → agent_runtime → core → (Provider 协议)
        application → context / memory_runtime / session_runtime / tooling / providers.factory
        providers → core 类型
禁止:core→tui, core→ToolRuntime, providers→tui, providers→ToolRuntime,
      tui→providers, tui→Agent 私有字段, session→SDK 消息格式, context→SDK
```

最终产品依赖:`pydantic>=2.11`、`rich>=13`、`textual>=8.2.8`、`pygments>=2.18`、
`anyio>=4`、`httpx[socks]>=0.27`。仓库没有依赖锁文件。独立在线 benchmark 的
`benchmark` optional extra 保留 OpenAI SDK,只在显式 `--online` 时惰性导入；基础安装、
离线评测与 `lion_code/` 运行路径不依赖它。Anthropic SDK 不再声明。

---

## 12. 迁移顺序与验收标准

阶段 0–4 已完成并通过各阶段自动化/真机验收。下面保留原迁移顺序作为追溯记录；其中
“legacy”“灰度”和“待补”描述的是当时的中间状态,不表示这些路径仍存在。

### 阶段 0:准备(小 PR)

- `textual>=0.86` → `>=8.2.8`;新增 `pygments>=2.18`;验证 legacy tui.py 与全测试在 textual 8.x 下可用。
- 新建 `UPSTREAM.md`(上游 repo、commit d597a8a / v0.3.3、导入模块清单、本地修改摘要=本文 §1、License、同步日期);扩充 `THIRD_PARTY_NOTICES.md` 覆盖 providers 与将迁入的 tui。
- vendor `providers/fake.py`;同步上游 anthropic `thinking disabled` 分支。
- **验收**:全测试绿;legacy TUI 手工冒烟(Windows 终端);文档齐。

### 阶段 1:application 骨架

- `application/events.py` + `application/session.py`(最小面:prompt/continue_/cancel/is_running/messages/队列/aclose + Settled/Queue/SessionAgentEnd 事件)。内部组合现 Agent(Core Runtime 路径),不新增 Loop。
- **验收**:单测覆盖——文本闭环、工具闭环、cancel、事件次序(AgentEnd→Settled)、运行中 steer/follow_up 入队并发 QueueUpdate;`messages` 与 JSONL Session 一致;Memory 不出现在 messages。

### 阶段 2:TUI 素材迁入(不接线)

- vendor A/B 类 10 个文件 + themes 到 `lion_code/tui/`,import 全部改 `lion_code.*`;Delta 事件统一 `core.provider_events`;补 §4 类型(markup.py、PromptTemplate、SessionStats、ProjectContextFile、ResourceDiagnostic)。
- `tui.py` → `legacy_tui.py`,`__main__.py` 暂仍指向 legacy。
- **验收**:`python -c "import lion_code.tui.state, lion_code.tui.widgets, …"` 全通;adapter/state 的事件→状态单测(可从 Tau 测试改写);legacy TUI 不回归。

### 阶段 3:app.py 重构接线

- 以 LionCodingSession 重写 app.py(§7 清单);移植权限/Plan/模型三 Modal;commands.py 落地(/clear /plan /cost /compact /model /new /resume /theme /thinking /skills /quit);`__main__.py` 默认新 TUI,`--legacy-tui` 逃生。
- **验收**:与现 tui.py 逐项功能对照打勾(流式文本、工具卡片、权限确认、Plan 审批含 clear-and-execute、模型热配、会话恢复/切换/侧栏、cost/usage 状态栏、abort);`LION_CORE_RUNTIME=1` 下手工冒烟含中文/非 UTF-8 控制台;test_tui 重写通过。

### 阶段 4:能力补齐 + 灰度扩围

- session_manager(标题/touch/SessionChangedEvent)、ModelChoice picker、thinking 循环(记录 ThinkingLevelChangeEntry)、steer/follow-up 输入 UI、AgentSettled 终端通知、溢出压缩+AutoRetry 事件链、(可选)prompt templates。
- 灰度扩围:Anthropic 后端上 Core;子 Agent 上 Core;side-query 迁 Provider;`LegacySdkTextQueryService` 替换;dream.py 解除私有客户端读取。
- **验收**:各能力单测+集成测试;两后端 × 新 TUI 手工矩阵;评审"`LION_CORE_RUNTIME` 默认开启"。

### 阶段 5:清理(实现完成,待最终 Trellis check 与用户验收)

- `64e25b6`:Core/Provider 单路径、canonical history 与原子热切换。
- `9e92d09`:删除 SDK 对话、旧压缩和旧查询路径。
- `1f95fb0`:删除旧 JSON writer,收敛 JSONL-only write + legacy read/migrate。
- `3370351`:删除旧 TUI、CLI 回退和全局输出 bridge。
- 收尾切片移除产品 SDK 直接依赖并同步本文、`UPSTREAM.md`、`docs/tui.md` 与 README；
  在线 benchmark 依赖隔离到 optional extra。
- 双协议/provider/application/session/TUI 自动化矩阵:277 passed、1 skipped;最终独立关键
  矩阵 183 passed;全量 pytest 473 passed、6 skipped、6 subtests passed。
- `compileall`、CLI help、依赖解析、产品禁止符号扫描、阶段范围 Ruff F 与
  `git diff --check` 通过。仓库没有项目级 mypy 配置;临时 mypy 诊断作为既有基线记录。
  Trellis check 已完成,任务在用户验收前保持 `in_progress`。

---

## 附:本次审计方法与数据来源

- Lion:master `0e31f3b` 工作树直读 + codegraph;符号级引用见审计过程记录。
- Tau:`d597a8a` 浅克隆直读;`git diff --no-index` 逐文件比对 core/providers。
- Tau CodingSession API 面、事件实证集(8 emit + 3 未用)、TUI 逐文件 import 表均以 0.3.3 源码为准,未依赖记忆。
