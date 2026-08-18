# Agent Note: 折叠两个 provider 适配器间重复的流式信封与工具函数（不合并适配器）

- Status: proposed
- 日期: 2026-08-18
- 范围: `lion_code/providers/anthropic.py`、`lion_code/providers/openai_compatible.py`、`lion_code/providers/stream.py` 或 `lion_code/providers/http.py`、`lion_code/providers/http_errors.py`

## Problem

`anthropic.py` 与 `openai_compatible.py` 各自带一份逐字节相同/几乎相同的流式信封
与工具函数（两适配器的协议差异保留，仅公共基建重复）：

- `_parse_sse_line`：`anthropic.py:434-437` vs `openai_compatible.py:1002-1006`；
- `_loads_object`：`anthropic.py:440-445` vs `openai_compatible.py:1009-1016`
  vs 第三份 `http_errors.py:60-64`——三份**已出现漂移**（捕获的异常类型不同：
  `JSONDecodeError` ⊂ `ValueError`）；
- `_int_or_none`（:452-453 vs :1033-1034，逐字节相同）与
  `_string_or_empty`/`_str_or_none`（:448-449 vs :945-946）；
- transient 状态集合 `{408,409,425,429} ∪ {>=500}`：`anthropic.py:320` 内联 vs
  `openai_compatible.py:1127-1128` 的 `_is_transient_status`；
- tool-call builder 的收尾链（join parts → `_loads_object` →
  `{"_raw_arguments": …}` 回退）：`_AnthropicToolBuilder.build`（:329-338）与
  `_ToolCallBuilder.build`（:592-602）同构；
- 整个 HTTP 重试流式信封（约 110 行）：`anthropic.py:97-310` 的迭代器 vs
  `openai_compatible.py:204-316`——`client.stream` POST、status≥400 读 body +
  重试判定、`provider_retry_event`/`retry_delay_seconds`/`wait_for_retry`、
  `ProviderResponseStartEvent`、cancel-check 循环、`httpx.HTTPError` 在
  `not emitted_content` 时重试。

测试只断言行为（`tests/providers/test_anthropic.py`、`test_openai_compatible.py`、
`test_stream.py`），不钉 helper 的位置；`providers/stream.py` 的
`_StreamParser` seam（`openai_compatible.py:187-346`）已经证明了
「公共信封 + 端点专属 parser」的形态可行。

## Proposal

1. 在 `providers/stream.py`（或 `providers/http.py`）新增共享
   `stream_provider_post(client, url, payload, headers, *, signal, max_retries,
   max_retry_delay_seconds, provider_name, model, parser_factory)` 信封与
   `parse_sse_line`/`loads_object`/`int_or_none`/`is_transient_status`/
   `tool_build_finalize` 工具。
2. 两个适配器改调共享实现，各自保留 payload builder、消息序列化与端点 parser
   ——**不合并为通用适配器**（零 SDK 双适配器是受保护设计，本提案不动它）。
3. 删除本地的重复拷贝；`http_errors.py` 的 `_loads_object` 一并改引共享版
   （消除异常类型漂移）。
4. 行为对齐：合并后两个适配器的重试时机/SSE 解析保持现有测试语义
   （`test_stream.py` 覆盖重试与取消路径）。

## Why not keep it

纯复制粘贴的维护风险：`_loads_object` 已经漂移（异常类型不一致），逐字节拷贝
意味着修一个 bug 要记着改三个地方。公共信封参数化后每端只需自己的 parser，
「一个事实一个表示」；删除净收益约 110 行 + 5 组重复工具函数，行为零变化。

## Acceptance criteria

- `rg -n "def _parse_sse_line|def _loads_object|def _int_or_none|_is_transient_status" lion_code/providers/anthropic.py lion_code/providers/openai_compatible.py` 零命中（全部走共享版）。
- `tests/providers/` 全绿（重试/取消/SSE 语义不变）；全量可跑 unittest 通过。

## Risks

- 信封参数化若过度，会退化成「又一个抽象层」——实施时保持信封窄（只收现状
  两个适配器共用的参数），不收未来假设；不满足即拆回两份。
- 两个适配器的重试判定在细节上（如 OAI 对 429 的 Retry-After 处理，若有）需逐
  行对齐——对齐时以 `test_stream.py`/`test_openai_compatible.py` 现有断言为准。

## 落地

- 提交: `850de7d`
- PR: #57（标题：refactor: 折叠两个 provider 适配器间重复的流式信封与工具函数（不合并适配器））
- 门禁证据: 定向测试全绿（排除 5 个已知环境性/既有失败：test_coding_session_ports、test_composition_profiles::test_all_profiles_return_meta_facade、test_capability_migration::test_session_participant、test_agent_core_runtime::test_plan_clear、test_cli::test_repl_routes_generic_command）；CI Quality gates 待绿。
