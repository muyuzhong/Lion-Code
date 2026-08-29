# Agent Note: 统一 provider 流式信封残留的重复协议与内联 finalize 循环

- Status: proposed
- 日期: 2026-08-29
- 范围: `lion_code/providers/openai_compatible.py`、`lion_code/providers/stream.py`

## Problem

`fold-provider-streaming-duplication`（PR #57）落地后仍有两处同构残留：

1. **协议逐字重复**：`openai_compatible.py:161-177` 的 `_StreamParser` 与 `stream.py:247-263` 的 `ProviderStreamParser` 除类名外逐字节相同（diff 验证，仅交换类名）；两侧各带一份 `feed`/`finalize`/`emitted_content`/`fatal` 的契约文档。
2. **finalize 收尾循环内联**：`openai_compatible.py:248-250` 仍内联 `[builder.build(index) for index, builder in sorted(...)]`，与共享版 `tool_build_finalize`（`stream.py:240-243`，`anthropic.py:222` 已使用）同构。

生产消费者：两处都是活代码的契约与收尾，但同一事实两份表示，修文档/改签名要改两处。

## Proposal

1. `openai_compatible.py` 的 `_StreamParser` 改为引共享版 `ProviderStreamParser`（或删除本地协议、直接使用 `stream.py` 的公开协议），删除本地重复定义。
2. `openai_compatible.py:248-250` 改调 `tool_build_finalize`，删除内联循环。

## Why not keep it

`fold-provider-streaming-duplication` 笔记的验收范围本应覆盖这两处（其「公共信封 + 端点专属 parser」形态已由 `stream_provider_post` 证明可行）；逐字节重复协议与内联收尾是折叠的漏网，改一处忘另一处即漂移。合并后「一个事实一个表示」，行为零变化。

## Acceptance criteria

- `rg -n "class _StreamParser" lion_code/` 零命中；`rg -n "builder.build(index) for index, builder in sorted" lion_code/providers/` 零命中。
- `tests/providers/test_openai_compatible.py`、`test_stream.py` 全绿。

## Risks

- 若 `openai_compatible.py` 与 `stream.py` 的 import 方向约束不允许直接引共享协议，则保留本地类型别名并附「与 ProviderStreamParser 保持一致」的注释——两处协议若未来演化出差异，需单独评估。