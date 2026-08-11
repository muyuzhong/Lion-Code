# Journal - zhangcx (Part 1)

> AI development session journal
> Started: 2026-07-27

---



## Session 1: Tau TUI 融合:审计 + 阶段0-3 + Claude Code 式补全体验

**Date**: 2026-07-27
**Task**: Tau TUI 融合:审计 + 阶段0-3 + Claude Code 式补全体验
**Branch**: `master`

### Summary

完成架构审计与迁移计划;阶段0-2(依赖/溯源/application骨架/TUI素材vendor);阶段3新写精简app.py接为默认入口;接入 / 补全弹出与主题picker。16个提交推送master,全量389通过。

### Main Changes

- docs/tui-migration-audit.md 12项审计与阶段0-5计划
- lion_code/application/(events/session/commands/视图类型)新建
- lion_code/tui/ vendor 12模块 + 新写 app.py + prompt_input.py
- tui.py→legacy_tui.py;__main__ 默认新TUI(--legacy-tui逃生)
- configure_api Core路径重建Provider修复

### Git Commits

| Hash | Message |
|------|---------|
| `7cf347f` | (see git log) |
| `a0812a6` | (see git log) |
| `ee48f36` | (see git log) |
| `03fe14d` | (see git log) |
| `28e20d4` | (see git log) |
| `e1e5961` | (see git log) |
| `df02482` | (see git log) |
| `96d8cd1` | (see git log) |
| `0b3aa4d` | (see git log) |
| `6972f68` | (see git log) |
| `f8be40c` | (see git log) |
| `6a34711` | (see git log) |
| `9a6eb03` | (see git log) |
| `fbf00fc` | (see git log) |
| `73e7583` | (see git log) |
| `60c17e5` | (see git log) |

### Testing

- [OK] 全量 389 passed / 18 skipped(pytest)
- [OK] tests/application 7例 + tests/tui 108例(含上游迁入的 adapter/config/themes/autocomplete)

### Status

[OK] **Completed**

### 详细纪要

### 背景

Tau(huggingface/tau)融合项目:把 Tau 的 Agent 内核/Provider/TUI 吸收为 Lion 底层,
Lion 保留工具/权限/中间件/Context/Memory/Session/Plan/Skill/子Agent/自动化。
此前 PR #7-12 已完成 core、providers、runtime、append-only session、
provider-neutral context、memory overlay。本次会话完成审计 + 阶段 0-3 + 补全体验。

### 架构审计(7cf347f)

`docs/tui-migration-audit.md`:12 项完整审计。核心结论:
- core/providers 与上游 Tau 0.3.3 (d597a8a) 逐文件比对:大多仅 import 改名;
  本地演化集中在 loop.py(get_tools/get_system/prepare_context/并行分批)、
  harness(中断修复事件化)、storage(fsync+断尾)、tools(is_error)
- Tau TUI 11 文件:2 个 A 类原样迁、8 个 B 类改 import、仅 app.py(6711 行)C 类需重构
- LionCodingSession 最小接口 + 应用级事件模型(Settled 为唯一归位信号)定稿

### 阶段 0:准备

- textual>=8.2.8 + pygments>=2.18(a0812a6);顺修 ModelScreen 弹屏测试竞态
- UPSTREAM.md 上游溯源 + THIRD_PARTY_NOTICES 扩充 + TAU_LICENSE 版权行更正(28e20d4)
- vendor providers/fake.py 供测试(ee48f36)
- 同步上游 anthropic thinking_mode=="disabled" 显式 payload(03fe14d)

### 阶段 1:application 骨架

- application/events.py(e1e5961):10 种应用级事件,对齐 Tau 实 emit 集 + Lion 增补
- application/session.py LionCodingSession(df02482):组合现 Agent(Core 路径),
  订阅桥转 AsyncIterator,AgentEnd→SessionAgentEnd,协程完成+排空后发 Settled;
  is_running 契约 = 从开始消费到 Settled(fake provider 秒完成时 task.done() 会失真);
  运行中 prompt 必须 streaming_behavior(steer/follow_up 入 Harness 队列)
- Agent 仅新增公开 core_runtime 只读属性

### 阶段 2:TUI 素材迁入

- 支撑类型(96d8cd1):application/{skills,prompt_templates,session_stats,resources,
  commands}.py + prompt.ProjectContextFile + version.py
- tui.py→legacy_tui.py(0b3aa4d/6972f68);用户已明确旧 TUI 要废弃
- lion_code/tui/ vendor 10 模块+3 主题 JSON(f8be40c):import 全改 lion_code.*,
  Delta 事件统一 core.provider_events,配置落 ~/.lion-code/tui.json,新增 markup.py
- 上游测试迁入 4 文件(6a34711);POSIX 拖拽格式用例 win32 跳过

### 阶段 3:新 TUI 主应用(ponytail 生效)

- 未整体移植 6711 行上游 app.py,在 vendored 组件上新写 ~700 行 tui/app.py(fbf00fc):
  TranscriptView 渲染 + 三 Modal 移植(权限确认/Plan 审批/模型热配)+ 会话侧边栏;
  ui sink 路由器只留子 Agent 输出与状态行(根 Agent 打印与核心事件重复,丢弃)
- LionCodingSession 扩属性面 + create_default_command_registry(9a6eb03):
  /quit /clear /plan /cost /compact /model /theme,CommandResult 意图分发
- __main__ 默认新 TUI(LION_CORE_RUNTIME=1 时),--legacy-tui 逃生
- 真 bug 修复(73e7583):Core 路径 configure_api 换 key/base 只重建了 SDK 客户端,
  httpx Provider 仍旧凭证 → 现在重建 Provider+Runtime 并保留 Harness 消息

### 补全体验(60c17e5,用户点名的 Claude Code 手感)

- vendor PromptInput→tui/prompt_input.py;`/` 弹补全(Tab 接受/Esc 关/上下选)
- 运行中 Enter=steer 入队、Alt+Enter=follow-up;Ctrl+O/T 切工具结果/thinking 显示
- /theme 换可搜索列表 picker;session.skills 视图(桥 SkillDefinition,缓存)
- 上游 autocomplete 测试 30 例迁入(5 例改本地机制注册表与 Lion 命令集解耦)

### 关键坑(勿重蹈)

1. widgets CSS 引用 $tau-* Textual 主题变量,必须挂载前 register_theme(app.py 已 vendor 映射)
2. IsolatedAsyncioTestCase 强制 asyncio debug,Textual 测试慢 10 倍 → TUI 测试一律 pytest-asyncio
3. 事件桥 is_running 不能依赖 task.done()(快 provider 排空期失真)
4. scratchpad 路径含中文用户名,Git Bash 编码崩 → 涉及该路径用 PowerShell

### 遗留债务(阶段 4/5)

- 阶段 4:model picker(需 provider_settings 模型目录)、session picker(需
  session_manager 索引)、thinking 档位、AgentSettled 终端通知、溢出压缩+AutoRetry
  事件链、Anthropic 后端上 Core、子 Agent 上 Core、3 处 side-query 迁 Provider
  (agent.py:_build_side_query/_run_evaluator_query/_run_classifier_query)、
  LegacySdkTextQueryService 替换、dream.py 私有客户端解耦、Windows 拖拽归一化、
  补全窗口溢出时迁上游按行测量版
- 阶段 5:删 legacy(_chat_openai/_chat_anthropic/旧压缩/legacy_tui/session.py 旧 JSON 写)、
  pyproject 移除 openai/anthropic
- Tau 上游克隆在会话 scratchpad(临时),下次同步需重新浅克隆并更新 UPSTREAM.md

### Next Steps

- 阶段4:model/session picker数据层(provider_settings+session_manager)
- 灰度扩围:Anthropic后端与子Agent上Core;3处side-query迁Provider
- 阶段5:删legacy双后端/legacy_tui/SDK依赖


## Session 2: hooks 兼容修复 + 新 TUI 成为默认入口

**Date**: 2026-07-27
**Task**: hooks 兼容修复 + 新 TUI 成为默认入口
**Branch**: `master`

### Summary

两个用户上报问题:trellis 写入的 Claude Code schema hooks 导致 lion-code 启动崩溃(跳过外来 schema);裸启动落入 legacy TUI 看不到新体验(TUI 启动默认 LION_CORE_RUNTIME=1,无凭证默认 OpenAI-compatible 占位由新 TUI 承载首跑配置)。全量 390 通过。

### Main Changes

- hooks.py:识别并跳过 matcher+嵌套hooks 数组的外来 schema 条目,Lion 条目仍严格校验
- __main__.py:TUI 启动 setdefault LION_CORE_RUNTIME=1;无凭证默认 OpenAI-compatible 占位端点

### Git Commits

| Hash | Message |
|------|---------|
| `5c58be3` | (see git log) |
| `fe8825d` | (see git log) |

### Testing

- [OK] tests/test_hooks.py 25例(含新回归用例);入口三场景冒烟(无凭证/--legacy-tui/OpenAI凭证)
- [OK] 全量 390 passed / 18 skipped

### Status

[OK] **Completed**

### Next Steps

- 阶段4任务已建:.trellis/tasks/07-27-phase4-tui-and-rollout(PRD 含 A-D 四组需求与验收)
- 用户待真机确认 / 补全手感;/model 列表 picker 是 A1 首件


## Session 3: 阶段4-A:model/session 列表 picker 落地

**Date**: 2026-07-27
**Task**: 阶段4-A:model/session 列表 picker 落地
**Branch**: `master`

### Summary

A1:/model 换 Claude Code 式可搜索列表(known_models 用过即记住,累积在 ~/.lion-code/config.json;无匹配输入即自定义模型名;Ctrl+E 进凭证表单;/model <name> 带参直切;参数补全接已知模型)。A2:/resume 会话列表 picker(复用 SessionRepository.list_sessions,未新建 session_manager);Ctrl+R 同入口。全量 399 通过。

### Main Changes

- application/provider_settings.py 最小模型目录(ModelChoice/load/remember)
- config.save_api_config 合并写回保留扩展键
- tui/app.py:ModelPickerScreen + SessionPickerScreen + 命令/快捷键接线

### Git Commits

| Hash | Message |
|------|---------|
| `22a3840` | (see git log) |
| `b41e64b` | (see git log) |

### Testing

- [OK] tests/application/test_provider_settings.py 5例;tui picker 4例;全量 399 passed

### Status

[OK] **Completed**

### Next Steps

- A 组完成;下一子项 B3 thinking 档位或 C6 Anthropic 上 Core
- 坑:ModalScreen 自定义属性勿用 visible(撞 DOMNode 样式 setter)


## Session 4: 阶段4-C6/C7:Anthropic 后端与子 Agent 上 Core

**Date**: 2026-07-27
**Task**: 阶段4-C6/C7:Anthropic 后端与子 Agent 上 Core
**Branch**: `master`

### Summary

灰度全面扩围:去掉 use_openai 与 is_sub_agent 两个排除条件,根/子 Agent、双后端统一走 Core Loop。跨协议切换保留会话历史(canonical 消息协议无关);子 Agent 不落盘会话、Memory 预取仍只服务主会话;修复 fork 不传 api_key 的凭证缺陷(_child_api_kwargs);新 TUI ModelScreen 撤 Anthropic 封锁,sink 路由器补子 Agent 文本缓冲。全量 402 通过。

### Main Changes

- agent.py:_use_core_runtime 仅看环境变量;core 门控统一为判 _core_runtime;configure_api 双协议+跨协议重建 Provider
- agent.py:_child_api_kwargs 凭证随 fork 继承;子 Agent 无 SessionRecorder
- tui/app.py:ModelScreen 支持 anthropic 保存;子 Agent 文本缓冲展示

### Git Commits

| Hash | Message |
|------|---------|
| `2696819` | (see git log) |
| `30c788d` | (see git log) |

### Testing

- [OK] 集成:anthropic core 闭环、跨协议保历史、子 Agent core 闭环+不落盘;全量 402 passed

### Status

[OK] **Completed**

### Next Steps

- C8:3 处 side-query 迁 Provider + LegacySdkTextQueryService 替换 + dream.py 解耦
- 注意:仓库有并行维护 Agent 在 slim/round-2 分支工作(.codex/ + MAINTENANCE.md),提交前确认当前分支是 master


## Session 5: 阶段4-C8:side-query 全面迁移 Core Provider

**Date**: 2026-07-27
**Task**: 阶段4-C8:side-query 全面迁移 Core Provider
**Branch**: `master`

### Summary

新增 providers/oneshot.complete_text 与 ProviderTextQueryService;Core 路径下 Memory 召回、side_query、评估器(role 结构经 canonical 转换)、Auto Mode 分类器全部改走 httpx Provider;dream.py 经 _child_api_kwargs 解除私有客户端直读;查询服务在 Runtime 构建/Provider 重建后刷新。C 组(灰度扩围)全部完成,阶段 5 删 legacy 的前置就绪。全量 405 通过。

### Main Changes

- providers/oneshot.py 一次性补全助手
- memory_runtime/query.py ProviderTextQueryService
- agent.py 三处 side-query Core 分支 + _canonical_side_messages
- dream.py 凭证走 _child_api_kwargs seam

### Git Commits

| Hash | Message |
|------|---------|
| `517fde8` | (see git log) |

### Testing

- [OK] oneshot 契约 2 例;集成 side-query 走 provider 1 例;全量 405 passed

### Status

[OK] **Completed**

### Next Steps

- 剩余阶段4子项:B3 thinking 档位、B4 AgentSettled 终端通知、B5 溢出压缩+AutoRetry 链、D 组小项
- 阶段5可开:删 legacy _chat_*/压缩/legacy_tui/session旧JSON写,pyproject 移除 openai/anthropic


## Session 6: 阶段4-B3:thinking 档位(Tau 6 档)接入 Core 路径

**Date**: 2026-07-27
**Task**: 阶段4-B3:thinking 档位(Tau 6 档)接入 Core 路径
**Branch**: `b3-thinking-tiers`

### Summary

此前 Core 路径完全不生效 thinking(factory 不带 thinking 参数,set_thinking 仅 legacy SDK 消费)。新增 providers/thinking.py(Tau 6 档 off..xhigh + 归一化/循环/coerce + Anthropic budget_tokens/OpenAI reasoning_effort 映射);factory.create_provider 增 thinking_level 参数;LionAgentRuntime.replace_provider 热替换 provider;Agent Core 路径 _thinking_level/set_thinking_level/cycle_thinking_level,档位变更热重建 provider+context_compactor 并记 ThinkingLevelChangeEntry,configure_api 透传档位,恢复会话 coerce 旧词汇;LionCodingSession 透传档位 API;/thinking 命令;TUI action_cycle_thinking 去桩(shift+tab)+_dispatch thinking_level 意图。全量 444 passed。

### Main Changes

- providers/thinking.py(新):6 档词汇+normalize/next/coerce(旧 SDK 词汇平滑过渡)+Anthropic budget_tokens/OpenAI reasoning_effort 映射
- providers/factory.create_provider:增 thinking_level 参数,按后端填 budget_tokens/reasoning_effort;None 保留默认
- agent_runtime.LionAgentRuntime.replace_provider:热替换 provider(harness 每轮 live 读 config.provider),返回旧 provider 供回收
- agent.py:Core 路径 _thinking_level/set_thinking_level/cycle_thinking_level/available_thinking_levels;档位变更经 replace_provider 热重建 provider+context_compactor+记 ThinkingLevelChangeEntry;configure_api 重建透传档位、recording 按 Core/legacy 分流;恢复会话 coerce 旧词汇并按档位重建 provider;legacy set_thinking/_thinking_mode 保留(阶段5删)
- application:LionCodingSession 透传档位 API;commands 注册 /thinking(带参设定/无参循环);Protocol 补 set/cycle;CommandResult.thinking_level 接入 _dispatch
- tui/app.py:action_cycle_thinking 去桩(shift+tab 真正循环);_dispatch 处理 thinking_level 意图;命令提示补 /thinking

### Git Commits

| Hash | Message |
|------|---------|
| `f5fcc06` | (see git log) |

### Testing

- [OK] [OK] providers/test_thinking 纯逻辑;test_factory 档位->参数映射;application/test_coding_session 档位 API+持久化+热重建+拒绝未知档位;integration 2 例适配
- [OK] [OK] 全量 444 passed, 18 skipped

### Status

[OK] **Completed**

### Next Steps

- B4:AgentSettled 终端通知
- B5:溢出压缩+AutoRetry 事件链
- D 组小项:Windows 拖拽归一化、补全窗口按行测量
- 阶段5:删 legacy(_chat_*/压缩/legacy_tui/session旧JSON写),pyproject 移除 openai/anthropic
- B3 在 b3-thinking-tiers 分支(f5fcc06),未合并 master;B4/B5 可基于此分支或先合并再开


## Session 7: 阶段4-B4:AgentSettled 终端通知;B5 范围界定

**Date**: 2026-07-27
**Task**: 阶段4-B4:AgentSettled 终端通知;B5 范围界定
**Branch**: `master`

### Summary

B4 完成:AgentSettledEvent 触发 TerminalNotificationController.notify_turn_finished(),按 settings.turn_notification(默认 desktop;bell 写响铃字符,desktop 写 OSC9/99 序列到 sys.__stdout__ 绕过 Textual 捕获直达终端)。app.py __init__ 构造控制器,_run_prompt 事件流识别 AgentSettled 调用。B5 经调研界定范围:Core AgentEvent 联合无 compaction/retry 事件,二者在 agent.py 内部透明编排(_compact_core_context_if_needed 做阈值压缩并记 CompactionEntry;_with_retry 重试经 print_retry sink 报告);且 Lion 压缩为阈值式主动压缩,审计的 overflow->compaction->retry 链尚不存在。B5 需会话事件回调机制 + CompactionStart/End 与 AutoRetryStart/End 上浮 + 可能新增 overflow 触发路径,范围较大,留待下一会话专注实现。B3+B4 已合并 master。

### Main Changes

- tui/app.py:__init__ 用 settings.turn_notification 构造 TerminalNotificationController;_run_prompt 事件流识别 AgentSettledEvent 调 notify_turn_finished()
- tests/tui/test_tui_app:注入 spy 控制器(enabled 强制开),验证 settle 触发 bell、off 模式不写

### Git Commits

| Hash | Message |
|------|---------|
| `2c43910` | (see git log) |

### Testing

- [OK] [OK] tests/tui 14 passed(含 B4 两例);tests/tui+application 133 passed,13 skipped

### Status

[OK] **Completed**

### Next Steps

- B5:溢出压缩+AutoRetry 事件链(范围已界定:需会话事件回调机制 + 事件上浮 + 可能 overflow 触发路径)
- D 组小项:Windows 拖拽归一化、补全窗口按行测量
- 阶段5:删 legacy(_chat_*/旧压缩/legacy_tui/session旧JSON写),pyproject 移除 openai/anthropic
- master 领先 origin/master 11 提交(B3+B4+journal),未 push;真机冒烟 thinking 与通知后可 push


## Session 8: 阶段4-B5：溢出压缩与一次自动重试

**Date**: 2026-07-28
**Task**: 阶段4-B5：溢出压缩与一次自动重试
**Branch**: `master`

### Summary

完成 Core overflow 识别、强制压缩与应用层单次自动重试闭环，并补齐严格事件顺序和失败分支回归测试。

### Main Changes

- Agent 复用既有上下文压缩路径，新增可取消的 overflow 强制压缩入口并保护最近成功轮次与失败提示。
- LionCodingSession 在同一 drive 生命周期内发出 Compaction、AutoRetry、SessionAgentEnd 和唯一 AgentSettled 事件。
- 补齐 B5 设计、实施计划与 error-handling 可执行规范。

### Git Commits

| Hash | Message |
|------|---------|
| `7224a0a` | (see git log) |

### Testing

- [OK] python -m pytest -q：453 passed, 18 skipped, 6 subtests passed
- [OK] python -m pytest tests/memory_runtime/test_lifecycle.py tests/application/test_coding_session.py -q：24 passed
- [OK] python -m compileall -q lion_code tests 与 git diff --check 通过；当前环境未安装 ruff

### Status

[OK] **Completed**

### Next Steps

- 继续阶段4剩余 D 组或阶段5迁移清理工作，当前 Trellis 总任务保持 in_progress。


## Session 9: 阶段4-D组：Windows 拖拽与补全渲染行裁剪

**Date**: 2026-07-28
**Task**: 阶段4-D组：Windows 拖拽与补全渲染行裁剪
**Branch**: `master`

### Summary

完成阶段4最后两个代码子项：Windows 终端拖拽路径跨平台归一化，以及按完整 Rich 表格实际渲染行裁剪补全窗口。阶段4自动化验收已绿，仍待两后端新 TUI 手工冒烟矩阵。

### Main Changes

- D9 复用现有 normalize_dropped_paths，POSIX 解析失败后以 non-POSIX shlex 回退，file URI 使用 url2pathname，保留 Windows 盘符和反斜杠。
- D10 以 Tau 窗口算法为基础，改为测量完整 Rich 补全表格，覆盖分类标题、列宽挤压、description 换行、非法选中索引与零预算。
- 补齐 TUI 输入与补全可执行规范，并更新阶段4自动化验收状态。

### Git Commits

| Hash | Message |
|------|---------|
| `82b28d7` | (see git log) |
| `b29e9fe` | (see git log) |

### Testing

- [OK] python -m pytest -q：474 passed, 6 skipped, 6 subtests passed
- [OK] D 组目标测试：35 passed, 1 skipped（Windows 上仅跳过 POSIX 专用转义用例）
- [OK] python -m compileall -q lion_code tests 与 git diff --check 通过；环境未安装 lint/type-check 工具

### Status

[OK] **Completed**

### Next Steps

- 执行 OpenAI-compatible 与 Anthropic 两后端的新 TUI 手工冒烟矩阵；取得证据后归档阶段4，再建立阶段5 legacy 清理任务。


## Session 10: 阶段4双后端TUI验收：离线通过，真机受阻

**Date**: 2026-07-28
**Task**: 阶段4双后端TUI验收：离线通过，真机受阻
**Branch**: `master`

### Summary

双协议 Provider、Core 切换、工具/Plan 与新 TUI 文本、picker、补全、通知的离线验收通过；真实 Anthropic 网关已通过认证层但当前返回 503，OpenAI-compatible 未配置凭证，因此不勾选手工冒烟验收、不归档阶段4。

### Main Changes

- 确认当前无 ~/.lion-code/config.json、OPENAI_API_KEY、OPENAI_BASE_URL 或 ANTHROPIC_API_KEY；存在 ANTHROPIC_AUTH_TOKEN 与 AnyRouter Base URL。
- 最小 Anthropic 请求确认 claude-opus-4-6 已下线；切换 4-7 并启用网关要求的 1M beta 后服务返回 HTTP 503。
- 未修改产品代码，阶段4 Acceptance Criteria 的两后端真机矩阵保持未完成。

### Git Commits

(No commits - planning session)

### Testing

- [OK] 双协议 Core + 新 TUI 定向矩阵：27 passed, 35 deselected
- [OK] 上次全量回归仍为 474 passed, 6 skipped, 6 subtests passed；本轮无代码变化

### Status

[!] **Partial — external prerequisites missing**

### Next Steps

- 在本机配置可用的 OPENAI_API_KEY + OPENAI_BASE_URL，并等待或更换可用 Anthropic 网关后完成真机矩阵；随后归档阶段4并进入阶段5 legacy 清理。


## Session 11: 阶段4完成：TUI 真机验收与流式修复

**Date**: 2026-07-28
**Task**: 阶段4完成：TUI 真机验收与流式修复
**Branch**: `master`

### Summary

完成阶段4 TUI 能力补齐与 Core 灰度扩围；修复流式 transcript 全量重绘闪烁及 canonical 窗口边界问题，全量 475 项通过，用户真机确认后批准进入阶段5。

### Git Commits

| Hash | Message |
|------|---------|
| `f82959e` | (see git log) |
| `fa24b1d` | (see git log) |
| `b802bf1` | (see git log) |

### Status

[OK] **Completed**


## Session 12: 阶段5暂停：完成 Core Provider 单路径

**Date**: 2026-07-28
**Task**: 阶段5暂停：完成 Core Provider 单路径
**Branch**: `master`

### Summary

阶段5规划已补强并启动；切片1已完成、验证并推送，切片2尚未开始，工作树干净。

### Main Changes

- 补充 Provider 空闲态原子热切换、派生服务刷新、回滚门和无锁文件边界。
- 完成 Core/Provider 唯一主路径、标量配置、canonical history、空闲态热切换与 child/restore 迁移。
- 独立检查修复整轮未 settled 时 thinking 热切换可能关闭活跃 Provider 的问题。

### Git Commits

| Hash | Message |
|------|---------|
| `8e8071a` | (see git log) |
| `563121f` | (see git log) |
| `64e25b6` | (see git log) |

### Testing

- [OK] 目标文件：67 passed。
- [OK] runtime 与 memory Core 集成：10 passed。
- [OK] compileall、git diff --check、Core 开关和 legacy chat 主流程残留扫描通过。

### Status

[OK] **Completed**

### Next Steps

- 从切片2开始：删除 LegacySdkTextQueryService、SDK side-query、legacy chat 和旧压缩 pipeline。
- 保持切片1的热切换、canonical history、overflow recovery 与会话恢复契约。

## Session 13: 阶段5完成，等待用户验收

**Date**: 2026-07-29
**Task**: 阶段5：移除 legacy 路径与 SDK 依赖
**Branch**: `master`

### Summary

阶段5切片1–5已实现：Core/Provider、canonical history、JSONL Session 与 Textual TUI
成为产品唯一运行路径；旧 SDK 对话/压缩、旧 JSON writer、旧 TUI 与全局输出 bridge 已删除，
主运行依赖不再包含 OpenAI/Anthropic SDK。最终 Trellis check、全量验证和中文工作提交已
完成；任务保持 in_progress，等待推送与用户验收。

### Git Commits

| Hash | Message |
|------|---------|
| `64e25b6` | Core Provider 单路径 |
| `9e92d09` | 删除 SDK 对话与旧压缩路径 |
| `1f95fb0` | 收敛 JSONL 会话单一路径 |
| `3370351` | 删除旧 TUI 与全局输出桥 |
| `46f9dfe` | 完成阶段5依赖与文档收敛 |

### Testing

- [OK] 双协议/provider/application/session/TUI/CLI 目标矩阵：277 passed、1 skipped。
- [OK] compileall、CLI help、主依赖解析、产品禁止符号扫描通过。
- [OK] `agent.py` 实测 2116 行，低于 2500 行验收上限。
- [OK] 全量 pytest：473 passed、6 skipped、6 subtests passed；独立关键矩阵：183 passed。
- [OK] compileall、CLI help、依赖/JSON 解析、产品禁止符号扫描、阶段范围 Ruff F 与
  `git diff --check` 通过。
- [INFO] 仓库没有项目级 mypy 配置；临时 mypy 的 97 条诊断属于既有未配置基线。
- [OK] Trellis check 与中文工作提交完成；推送和用户验收仍待处理。

### Status

[WIP] **Implementation, final check, and work commit complete; push and user acceptance pending**


## Session 13: 完成并归档阶段5迁移

**Date**: 2026-07-30
**Task**: 完成并归档阶段5迁移
**Branch**: `master`

### Summary

用户确认阶段5迁移验收，更新完成状态并归档任务。

### Git Commits

| Hash | Message |
|------|---------|
| `cbc0195` | (see git log) |

### Status

[OK] **Completed**


## Session 14: 补齐 Lion 后端开发规范

**Date**: 2026-07-30
**Task**: 补齐 Lion 后端开发规范
**Branch**: `master`

### Summary

完成 Bootstrap Guidelines：以当前 Lion 代码为依据补齐后端规范、同步索引和任务验收，并通过任务、编译与差异检查。

### Git Commits

| Hash | Message |
|------|---------|
| `81d1cfd` | (see git log) |

### Status

[OK] **Completed**


## Session 15: 建立编码 Agent 评测基础设施

**Date**: 2026-07-31
**Task**: 建立编码 Agent 评测基础设施
**Branch**: `master`

### Summary

新增离线评测契约、隔离生命周期、MCP 禁用 seam、受控轨迹与回归测试；真实 Docker 路径保持 blocked。

### Git Commits

| Hash | Message |
|------|---------|
| `8bc7673` | (see git log) |

### Status

[OK] **Completed**


## Session 16: 建立自建编码任务集与准入证据

**Date**: 2026-07-31
**Task**: 建立自建编码任务集与准入证据
**Branch**: `master`

### Summary

基于 Lion 真实历史提交建立 30 条任务卡、18/12 split、冻结 catalog/lock 与三次 Git provenance 准入；明确历史回放不是官方语义成绩。

### Git Commits

| Hash | Message |
|------|---------|
| `67d0333` | (see git log) |

### Status

[OK] **Completed**


## Session 17: 建立 SWE-bench-Live 外部锚点评测

**Date**: 2026-07-30
**Task**: 接入 SWE-bench-Live 外部锚点
**Branch**: `master`

### Summary

冻结 20 条 Python-only SWE-bench-Live `verified` 外部锚点，建立三次 gold patch 预检、
官方 evaluator adapter、实际分母/区间报告、环境漂移拒绝与五 profile 校准。发现官方
evaluator 不支持 dataset revision 参数后，改为只接受哈希校验的本地 materialized JSONL，
避免把可变 Hugging Face dataset 名称误作冻结输入。本机 Docker daemon 不可用，因此未生成
或伪造任何外部通过率。

### Main Changes

- `external_anchor_assets/` 固定数据 revision、verified 文件 SHA、20 条 instance ID、分层
  规则、evaluator revision 与完整 selected-row canonical SHA-256。
- 官方 runner 对每题 gold 连跑三次；只有三次 `resolved=true` 的题目进入实际分母。
- 统一输出 `TaskResult` / `ExternalAnchorReport`，记录摘要、镜像 digest、Wilson 95% 区间；
  Docker、JSONL、镜像或官方结果异常一律 `blocked`/`invalid`，无成功率。
- 比较前严格校验数据/evaluator/platform/选择/镜像环境指纹；校准要求 baseline、三候选和
  故意退化 profile，阈值为 Spearman >= 0.70、方向一致率 >= 80%。

### Git Commits

| Hash | Message |
|------|---------|
| `5a4b26f` | 建立 SWE-bench-Live 外部锚点评测 |
| `829eebb` | chore(task): archive 07-30-evaluation-external-anchor |

### Testing

- [OK] 远端冻结 snapshot 的 500 行与确定性抽样交叉校验：仍得到相同 20 条锚点。
- [OK] `tests/benchmarks`：36 passed；外部锚点专项：12 passed。
- [OK] 新增路径 Ruff、compileall、`git diff --check` 与离线 manifest CLI 通过。
- [OK] 全量 pytest：509 passed、6 skipped、6 subtests passed。
- [INFO] 仍有既有 Windows GBK spinner 线程警告；与本任务无关。

### Status

[OK] **Completed — actual external score remains blocked until a controlled Linux Docker host and approved model budget are available**

### Next Steps

- 在受控 Linux Docker host materialize 并校验 20 行 JSONL，checkout 固定官方 evaluator，
  再执行 gold 预检和五 profile 校准。
- 继续父任务的回归门禁与失败回流子任务；任何 prompt、压缩或工具变更先走该外部锚点可比性检查。

## Session 18: 建立评测回归门禁与失败回流

**Date**: 2026-07-31
**Task**: 建立回归门禁与失败回流
**Branch**: `master`

### Summary

完成 prompt、压缩和工具策略变更的正式回归门禁，建立未合入拒绝项的累计拦截账本；将受控轨迹的失败候选、人工复现/责任审查与下一版 regression 任务回流连成防泄漏闭环。

### Main Changes

- `evaluate_regression_gate()` 严格比较冻结 catalog、任务/repeat、资源、模型和运行环境；只有显式声明的 prompt、compression、tool-policy 版本差异可比较。
- V1 使用 -10pp 非劣边界和 `3/3 -> 0/3` 灾难回退拒绝；`invalid` 不计算 delta，`waived` 必须提供原因，`reject && !merged` 才计入拦截账本。
- 无覆盖 baseline/candidate 的有效外部校准时结论为 `self_only`；满足五 profile、相关性、方向一致性并覆盖两边 profile 后才标为 `external_calibrated`。
- 基于脱敏 `TraceEvent` 分类 loop、context_decay、tool_misuse、premature_termination；blocked/invalid/offline 统一优先归为 infrastructure。
- 只有已复现、Agent 责任且未去重的失败能进入下一版 regression；来源 holdout 必须 retire，不能继续留在 active holdout。

### Git Commits

| Hash | Message |
|------|---------|
| `2ddbf66` | 建立评测回归门禁与失败回流 |
| `95d1b73` | chore(task): archive 07-30-evaluation-regression-feedback |
| `fe72cf7` | chore(task): archive 07-30-coding-agent-evaluation-loop |

### Testing

- [OK] 回归门禁专项：pass/reject/invalid/waived、故意 `3/3 -> 0/3` 劣化账本、self-only 与外部校准范围通过。
- [OK] 四类失败、基础设施优先级、签名去重和 holdout retire 回流测试通过。
- [OK] 新增路径 Ruff、compileall、`git diff --check` 及 Trellis task validate 通过。
- [OK] 全量 pytest：512 passed、6 skipped、6 subtests passed。
- [INFO] 仍有既有 Windows GBK spinner 线程警告；与本任务无关。

### Status

[OK] **Completed — 编码 Agent 评测闭环父任务已归档；外部通过率仍保持 blocked，需受控 Linux Docker host 和批准预算后才可真实执行**


## Session 19: 二阶段:清掉已知的架构债务

**Date**: 2026-08-01
**Task**: 二阶段:清掉已知的架构债务
**Branch**: `feat/phase2-arch-debt`

### Summary

按序处理 m-012/m-007/m-013/m-010 + 第二套路径扫描,保证每种核心行为只有一个权威实现

### Main Changes

- m-012: 删除 /skill: 半成品入口(tau <skill> 机器+TUI autocomplete/app.py/commands.py 特判+state.py 展示分支);接线转预留任务 08-01-tui-skill-wiring
- m-007: mcp_client 连接失败隔离/读循环 EOF 两条容错分支补测试 tests/test_mcp_client.py(5 例);确认无重连逻辑
- m-013: 合并两套 MEMORY 索引重建,memory.rebuild_memory_index_if_needed 唯一入口,删 tools._auto_update_memory_index
- m-010: 清理 TUI 零引用符号(terminal_title 薄化、state.py format_terminal_command_result_block)
- Task5: 扫描 Provider/Session/Tool/Memory,确认无第二套权威路径,均为分层;唯一重复(MEMORY 索引)已由 m-013 处理

### Git Commits

| Hash | Message |
|------|---------|
| `5238ae6` | (see git log) |

### Testing

- [OK] 全量 533 passed(532-4 /skill: 专项+5 MCP 容错)、6 skipped、compileall 通过
- [OK] ruff 218 / format 146(由 147 改善) / mypy 105 / vulture 5 均未超基线;CI format 阈值同步 147->146

### Status

[OK] **Completed**

### Next Steps

- 预留任务 08-01-tui-skill-wiring: 把 TUI /skill: 接到 lion_code.skills.resolve_skill_prompt(待 /skill 删除稳定后实施)
- 可选 defer: providers/provider.py 重导出 shim 收敛、core/session/memory.py 命名澄清


## Session 20: 三阶段-1:提取 autonomy_runtime,拆解 agent.py

**Date**: 2026-08-01
**Task**: 三阶段-1:提取 autonomy_runtime,拆解 agent.py
**Branch**: `feat/phase3-agent-decompose`

### Summary

把 /goal//loop/AutoMode 协调从 agent.py 迁入 autonomy_runtime.py(AutonomyHost 窄协议),agent.py 2397->2152

### Main Changes

- 新建 autonomy_runtime.py:AutonomyRuntime+AutonomyHost,迁入 6 状态字段+16 方法
- Agent 改薄委托+6 状态属性委托,公共 API 不变;side-query 工具暂留
- 先补 /goal//loop 特征测试 10 例(test_autonomy_goal_loop.py)再迁移

### Git Commits

| Hash | Message |
|------|---------|
| `3e3a188` | (see git log) |

### Testing

- [OK] 全量 543 passed(+10)、6 skipped、compileall 通过
- [OK] ruff 218 / format 146 / mypy 105 持平基线

### Status

[OK] **Completed**

### Next Steps

- 三阶段-2:session_memory_coordinator 提取(SessionMemory+dream+handoff+memory overlays)
- 预留 tui-skill-wiring 接线仍待办


## Session 21: 完成三阶段-2 Session Memory 协调器提取

**Date**: 2026-08-03
**Task**: 完成三阶段-2 Session Memory 协调器提取
**Branch**: `feat/phase3-session-memory-coordinator`

### Summary

完成父任务 07-30-project-session-memory 之后的三阶段-2 子任务：将 Session Memory、三层 Overlay、Dream 和轮后更新迁入 SessionMemoryCoordinator，保留 Agent 公共 API 与兼容边界。

### Main Changes

- 新增 SessionMemoryCoordinator 与 SessionMemoryHost 窄协议，Agent 改为薄委托。
- 补充协调器特征测试并同步 runtime boundary、维护台账和质量基线。

### Git Commits

| Hash | Message |
|------|---------|
| `952da7c` | (see git log) |

### Testing

- [OK] 547 passed, 6 skipped, 6 subtests passed；compileall 通过。
- [OK] ruff 218、format 146、mypy 102、vulture 5；import-linter 3 契约 KEPT。

### Status

[OK] **Completed**

### Next Steps

- 按路线继续评估 subagent_factory 提取。


## Session 22: 三阶段-3：提取子 Agent 工厂

**Date**: 2026-08-03
**Task**: 三阶段-3：提取子 Agent 工厂
**Branch**: `muyuzhong/phase3-subagent-factory`

### Summary

将子 Agent 与 Skill fork 的构造和工具策略迁入 SubagentFactory，保持懒导入、权限、共享环境和资源关闭边界；全量测试 551 passed、6 skipped。

### Git Commits

| Hash | Message |
|------|---------|
| `19709152b082183f2e2893aa79021a0387930c04` | (see git log) |

### Status

[OK] **Completed**


## Session 23: 三阶段-4：提取 Learning Runtime

**Date**: 2026-08-03
**Task**: 三阶段-4：提取 Learning Runtime
**Branch**: `muyuzhong/phase3-subagent-factory`

### Summary

将显式 /learn 的提示词、Core 转录、evaluator 决策解析和 Skill 创建迁入 LearningRuntime，保持 Agent 公共委托、导入兼容和错误语义；全量测试 555 passed。

### Git Commits

| Hash | Message |
|------|---------|
| `b17c9d6b30536fab988d1c3b45d938628d8e6987` | (see git log) |

### Status

[OK] **Completed**


## Session 24: 完成 S5 Agent 生命周期提取

**Date**: 2026-08-04
**Task**: 完成 S5 Agent 生命周期提取
**Branch**: `muyuzhong/phase3-subagent-factory`

### Summary

提取 AgentLifecycle，保持 Provider 原子热替换、Thinking 档位与 create_provider patch 锚点兼容；完成独立复核、规格同步和全量验证。

### Git Commits

| Hash | Message |
|------|---------|
| `9874f28` | (see git log) |

### Status

[OK] **Completed**


## Session 25: 收敛 Agent Runtime 协调

**Date**: 2026-08-04
**Task**: 收敛 Agent Runtime 协调
**Branch**: `muyuzhong/phase3-subagent-factory`

### Summary

提取 AgentRuntimeCoordinator，保持 Core 单一路径与兼容锚点，完成全量回归和边界规格更新。

### Git Commits

| Hash | Message |
|------|---------|
| `37385e3` | (see git log) |

### Status

[OK] **Completed**


## Session 26: 完成 Agent 运行时拆分路线验收

**Date**: 2026-08-04
**Task**: 完成 Agent 运行时拆分路线验收
**Branch**: `muyuzhong/phase3-subagent-factory`

### Summary

核对 S3-S6 的归档与提交证据，复跑全量测试并完成父任务验收、归档。

### Git Commits

| Hash | Message |
|------|---------|
| `921f5b7` | (see git log) |

### Status

[OK] **Completed**


## Session 27: 完成 Session 与 Cancellation 状态所有权迁移

**Date**: 2026-08-09
**Task**: 完成 Session 与 Cancellation 状态所有权迁移
**Branch**: `master`

### Summary

建立 SessionIdentityState、ExecutionControl 与共享 CancellationToken，删除 Agent 和 ToolContext 镜像状态，补齐架构契约及回归测试；全量 602 passed。

### Git Commits

| Hash | Message |
|------|---------|
| `2b77174` | (see git log) |

### Status

[OK] **Completed**


## Session 28: 完成 Permission 状态所有权迁移

**Date**: 2026-08-09
**Task**: 完成 Permission 状态所有权迁移
**Branch**: `master`

### Summary

建立 PermissionState、PermissionController 与只读 PermissionView，删除 Agent/ToolContext 权限镜像并补齐架构门禁；全量 609 passed。

### Git Commits

| Hash | Message |
|------|---------|
| `f8405f0` | (see git log) |

### Status

[OK] **Completed**


## Session 29: 完成 PlanRuntime 状态所有权迁移

**Date**: 2026-08-09
**Task**: 完成 PlanRuntime 状态所有权迁移
**Branch**: `master`

### Summary

建立 PlanState、PlanView 与唯一 PlanRuntime，删除 Agent/ToolContext Plan 镜像并补齐事务原子性与架构门禁；全量 623 passed。

### Git Commits

| Hash | Message |
|------|---------|
| `4010464` | (see git log) |

### Status

[OK] **Completed**


## Session 30: 完成 State Ownership 分阶段迁移

**Date**: 2026-08-09
**Task**: 完成 State Ownership 分阶段迁移
**Branch**: `master`

### Summary

完成 Session/Cancellation、Permission、PlanRuntime、Usage 四个独立状态所有权切片；最终全量 629 passed、6 skipped、20 subtests，架构与静态门禁通过。

### Git Commits

| Hash | Message |
|------|---------|
| `66a7a04` | (see git log) |

### Status

[OK] **Completed**


## Session 31: 完成 PR 23 CI 基线修复

**Date**: 2026-08-10
**Task**: 完成 PR 23 CI 基线修复
**Branch**: `muyuzhong/state-ownership-migration`

### Summary

更新五条因状态所有权迁移产生行号漂移的 Radon/Vulture 既有指纹；本地门禁与 GitHub Actions run 31324469250 全部通过。

### Git Commits

| Hash | Message |
|------|---------|
| `b25ea2c` | (see git log) |

### Status

[OK] **Completed**
