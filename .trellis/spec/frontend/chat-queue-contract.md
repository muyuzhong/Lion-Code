# 聊天队列事件契约（queue_update / 消费出队）

## 1. Scope / Trigger

触碰以下任何一项时必读并遵守本契约：排队输入（follow_up/steer）、消息流内排队徽标、
队列计数、轨迹面板中的队列事件、`ChatProtocolState.queue` 及其 reducer。

契约来源：PR② 实现（PR #84 系）中对后端事件发射时序的源码核实；行号为 2026-08-22 锚点，漂移后按符号搜。

## 2. Signatures

- 协议事件：`queue_update`，负载 `{ queue: { steering: string[]; followUp: string[] } }`
  （定义 `frontend/src/lib/chatProtocol.ts` 事件表；后端构造 `lion_code/application/session.py` `queue_update_event`）
- 前端状态：`ChatProtocolState.queue: { steering: string[]; followUp: string[] }`（初始两项皆空）

## 3. Contracts（后端发射时序——非直觉部分）

- `queue_update` **只在入队时发射**：steer / follow_up action 处理后 yield
  （`session.py:170` 附近）。消费排队消息时**不发** queue_update。
- 消费回显走普通消息流：后端逐条以 **user 角色 `message_start`** 发出被消费的排队消息
  （`core/loop.py:115-118`）；轮末才处理 follow_ups（`loop.py:250-252`）。
- 消费顺序：**steering 先于 followUp**（`loop.py:105` 先装 steering pending）。
- 初始 prompt 也有服务端回显（`loop.py:92-93`），同样以 user `message_start` 到达。

## 4. 前端规则（Validation Matrix）

| 事件 | 正确行为 |
| --- | --- |
| `queue_update` 到达 | 全量快照直接替换 `state.queue`（单一事实源，禁止乐观 append） |
| user `message_start` 到达 | 入流转正式 UserMessage + 本地出队：按文本匹配（steering 优先，一次只移除一项） |
| user `message_start` 队列无匹配 | 返回原 state 引用（初始 prompt 回显场景，防重复入流） |
| `replace_history` | 清空 queue（重连/换会话后队列不在 canonical history，等下次快照自愈） |
| `disconnected`（含手动取消） | 不清 queue（后端队列保留残留项，下一轮运行消费时自愈入流） |

已知接受的精度限制：排队项与新 prompt 文本完全相同的极端场景可能产生一条重复消息。

## 5. Tests Required

`frontend/src/lib/chatProtocol.test.ts` 必须维持以下断言点：

1. queue_update 全量替换（旧条目消失，证明非 append）
2. user `message_start` 入流转正（string 与 blocks 两种 content 形态）
3. 同文本双队列单项移除 + steering 优先
4. 队列无匹配时状态引用不变（`toBe` 断言）
5. `replace_history` 清空队列

## 6. Wrong vs Correct

**Wrong**：期待后端在消费时发 queue_update 来"自动"出队；或在发送 follow_up 后乐观 append
本地队列（与服务端快照竞争，重连后漂移）。

**Correct**：入队信任 `queue_update` 快照；出队信任 user `message_start` 的本地文本匹配
（`frontend/src/lib/chatProtocol.ts` `consumeQueuedUserMessage`，2026-08-22 位于 :618-648）。
