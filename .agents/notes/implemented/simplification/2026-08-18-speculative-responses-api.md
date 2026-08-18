# Agent Note: 删除 OpenAI-compatible 适配器里投机性的 /v1/responses 子系统

- Status: implemented
- 日期: 2026-08-18
- 范围: `lion_code/providers/openai_compatible.py`、`lion_code/providers/config.py`、`tests/providers/test_openai_compatible.py`

## Problem

`openai_compatible.py`（1128 行）里约 450 行是 **`/v1/responses` API 子系统**，
没有任何生产者能选中它：

- 入口：`_use_responses_api()`（:54-57）按硬编码前缀 `("gpt-5.5", "gpt-5.4")`
  （:51）和模型名含 `"codex"` 判断；`api="openai-responses"`（config.py:39）也走
  responses 路径（:115）。
- 子系统本体：`_stream_responses`（:161-186）、`_ResponsesStreamParser`
  （:443-568，~125 行）、`_ResponsesToolCallBuilder`（:605-657）、
  `_build_responses_payload`（:754+）等。
- 生产构造（`providers/factory.py:43-51`）只传 `api_key`/`base_url`/
  `provider_name`/`max_tokens`/thinking 参数——`api` 恒为默认
  `"openai-completions"`；`rg` 全仓（生产/测试/文档/README）除
  `openai_compatible.py` 自身外没有任何 `gpt-5.5`/`gpt-5.4`/`openai-responses`
  引用。整条路径当前不可达，也没有任何测试覆盖 responses 路径。

## Proposal

1. 删除 `_use_responses_api`、`_RESPONSES_ONLY_PREFIXES`、"codex" 分支、
   `_stream_responses`、`_ResponsesStreamParser`、`_ResponsesToolCallBuilder`、
   `_build_responses_payload` 及其在 `stream_response` 里的分发（:115/:171/:183）。
2. 删除 config.py 的 `api` 字段（或固定为 "openai-completions" 语义并去掉分支）。
3. 保留 `/chat/completions` 路径与 `reasoning_effort`/thinking 映射
   （生产实际使用）。

## Why not keep it

辩护是「OpenAI 未来的 reasoning 模型（codex/gpt-5.x 系）马上要用 responses
API，先铺好」。但按 `AGENTS.md` 原则 2（不预防性抽象、绝不为未完成的复杂度
保留配置层）：没有生产模型、没有配置入口、没有测试，450 行不可达代码是仓库里
最大的投机泛化单体。真需要支持时，参照 `_use_responses_api` 的分发点按需加回
（成本与今天删除对称），且届时会有真实 API 响应可对拍测试。

## Acceptance criteria

- `rg -n "responses|_use_responses_api|gpt-5" lion_code/providers` 零命中
  （保留 chat completions 相关字样）。
- `tests/providers/test_openai_compatible.py` 全绿（删除相关路径后无引用残留）；
  全量可跑 unittest 通过。

## Risks

- 若短期内真接入 codex 类模型，需重建 responses 解析——已评估成本对称；
  作为 mitigation，删除前把 responses 的行为语义（tool call 累积、usage 解析）
  摘录进本笔记的 git 历史即可。
## 落地

- 提交: f7b1c80（分支 simplify/remove-responses-api）
- 验证: openai_compatible.py 1128→~600 行；删除 TestOpenAIResponsesApi；同步 PROVIDER_STATE_ALLOWLIST。门禁：全量 711 passed（5 个沙箱环境/既有失败除外）、ruff 48<54、mypy 38<68、radon 9≤12。
