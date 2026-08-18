# Agent Note: 清理 Provider 层迁移残留（死认证旋钮、死 thinking 方法、vendored 死声明）

- Status: proposed
- 日期: 2026-08-18
- 范围: `lion_code/providers/config.py`、`lion_code/providers/anthropic.py`、`lion_code/providers/openai_compatible.py`、`lion_code/providers/factory.py`、`lion_code/provider_manager.py`、`lion_code/meta_agent.py`、`lion_code/application/commands.py`、`lion_code/application/events.py`、`tests/`（引用处）

## Problem

Provider/application 层有三组互不相关的迁移残留，共同点是「写而无人读 / 声明而
无人构造 / 仅测试引用」：

1. **死认证/凭据旋钮**（`providers/config.py`）：`oauth_system_prompt`（:67）、
   `bearer_auth`（AnthropicConfig）、`omit_authorization_header`、`credential_resolver`
   （`OpenAICompatibleConfig` :45/:48）、`RuntimeProviderAuth`（:18-24）——
   `factory.py` 构造配置时不传任何一个，生产恒为默认值，代码分支
   （`anthropic.py:113/:362-365`、`openai_compatible.py:209-220`）按构造不可达；
   测试也不构造它们（`rg` 验证）。
2. **死 thinking 方法**：`ProviderManager.resolve_thinking_mode`（`provider_manager.py:258`，
   全仓零调用）、`ProviderManager.set_thinking`（:237）+ `MetaAgent.set_thinking`
   （`meta_agent.py:164`）——生产只用 `set_thinking_level`（`tui/app.py:966`、
   `application/commands.py:181`），`agent.set_thinking(True)` 只有
   `tests/integration/test_agent_core_runtime.py:626` 一个引用（`Agent._resolve_thinking_mode`
   的删除见另一笔记，`agent.py:245` 是它唯一调用点）。
3. **vendored-Tau 死声明**（`application/commands.py` 的 `CommandResult` 与
   `application/events.py`）：`CommandResult` 的 13+ 个标志
   （`tree_picker_requested`/`prompts_picker_requested`/`login_picker_requested`/
   `custom_provider_login_requested`/`login_provider`/`login_method`/
   `logout_picker_requested`/`export_requested`/`export_destination`/
   `export_format`/`reload_requested`/`resume_session_id` 等，:63-79）
   从未被任何实现 set 或任何消费方 read（TUI 只读
   `new_session_requested`/`compact_summary`/`resume_picker_requested` 等少量标志）；
   `SessionChangedEvent`/`ProviderChangedEvent`/`ThinkingLevelChangedEvent`
   （`events.py:83/:91/:99`）从未被构造，只被 `application/__init__.py` 导出。

## Proposal

1. 删除 `oauth_system_prompt`/`bearer_auth`/`omit_authorization_header`/
   `credential_resolver`/`RuntimeProviderAuth` 及相关不可达分支；若保留
   `RuntimeProviderAuth` 作为公开扩展类型则至少删除无生产者的配置字段。
2. 删除 `ProviderManager.resolve_thinking_mode`、`MetaAgent.set_thinking` 与
   `ProviderManager.set_thinking`（保留 `set_thinking_level` 全家桶）；
   同步删除 `test_agent_core_runtime.py:626` 用例。
3. 删除 `CommandResult` 未用标志与三个未构造事件（含 `application/__init__.py`
   导出与事件 union 成员）；顺带清理 `application/events.py` 的过期 phase 文档注释。

## Why not keep it

分组共同点就是 Tau 迁移期的「先铺后接」：认证旋钮为未来 OAuth 登录、picker 标志为
未来 TUI 选择器、thinking 布尔 API 为旧版本兼容——今天的生产路径一条也没用上。
按「不保留向后兼容 + 最简单实现」，无生产者的旋钮/声明删除后，
`CommandResult`/事件 union/config 类型都更接近真实契约。

## Acceptance criteria

- `rg -n "oauth_system_prompt|bearer_auth|omit_authorization_header|credential_resolver|RuntimeProviderAuth|set_thinking\b|resolve_thinking_mode|tree_picker_requested|login_picker_requested|export_requested|SessionChangedEvent\(|ProviderChangedEvent\(|ThinkingLevelChangedEvent\("` 全仓零命中。
- `tests/providers/`、`tests/application/`、`tests/integration/test_agent_core_runtime.py`、
  `tests/tui/` 全绿；全量可跑 unittest 通过。

## Risks

- `RuntimeProviderAuth` 若是给未来 OAuth/自定义认证 embedder 的公共类型，删除
  是公共 API 缩减——当前零生产者零消费者，`AGENTS.md` 明示不做向后兼容，可接受。
- `set_thinking` 若被 TUI 未来「Thinking 开关节能」复用，恢复成本 4 行。

## 落地

- 提交: `731316423ec2d714e1e12783425731f40113a9a3`（squash merge）
- PR: #54（标题：refactor: 清理 Provider 层迁移残留（死认证旋钮、死 thinking 方法、vendored 死声明））
- 门禁证据: 定向测试全绿（排除 5 个已知环境性/既有失败：test_coding_session_ports、test_composition_profiles::test_all_profiles_return_meta_facade、test_capability_migration::test_session_participant、test_agent_core_runtime::test_plan_clear、test_cli::test_repl_routes_generic_command）；CI Quality gates 已通过（2026-08-18）。
