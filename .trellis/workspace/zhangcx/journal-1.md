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
