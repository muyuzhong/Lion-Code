# Agent Note: 删除 AssistantMessage 上零消费者线格式字段（response_model/response_id）

- Status: proposed
- 日期: 2026-08-29
- 范围: `lion_code/core/messages.py`、`desktop/src/shared/chat.ts`（核对用）

## Problem

`AssistantMessage`（`core/messages.py`）的两个线格式字段没有任何消费者——既无人写也无人读：

1. **`response_model` / `response_id`**（`messages.py:127-128`）：`rg "response_model|response_id"` 全仓（`lion_code/`、`tests/`、`desktop/src/`）唯一命中是定义行本身；desktop `chat.ts` 的 `AssistantMessage` 类型镜像也无此二字段；没有任何 Producer 设置、没有任何 Reader 读取，按构造恒为 `None`。

## Proposal

删除 `messages.py:127-128` 两个字段定义。无测试、无文档、无 TS 协议需要同步（已核对 `desktop/src/shared/chat.ts` 无此字段）。

## Why not keep it

这是一对「Pi 兼容线格式预留字段」（响应追踪 id 类）：项目已按 `zero-constructed-message-roles` 笔记先例清理过同类零构造面。若未来接入 responses-API 系模型或需要对拍 response id，加回成本两行；按「不保留向后兼容 + 没有调用者就不存在」删除。

## Acceptance criteria

- `rg -n "response_model|response_id" lion_code/ tests/ desktop/src/` 零命中。
- `tests/core/`、`tests/providers/`、`tests/integration/` 全绿（无测试引用这两个字段）。

## Risks

- 若某个 provider 适配器未来要暴露响应级追踪信息，需要重新加字段——恢复成本 2 行；当前 `AssistantMessage.api/provider/model` 三个身份字段仍在，足够表达来源。