# PR② 运行中交互：排队输入与转向

## Goal

流式期间可继续输入：Enter 默认 `follow_up` 排队，`steer`（立即改向）为显式
次级按钮，队列状态双向呈现。对应设计 PR②（依据归档设计 P0-2 与 D1/D7/D8；
后端语义见 research/frontend-current-state.md §3、§5.5：运行中 `prompt` 被拒，
steer/follow_up 同队列机制）。

## Requirements

- R1：`isStreaming` 时输入框保持可用；Enter / 主发送按钮发送 `follow_up`
  （hook 已有 `sendFollowUp`，App 接线）。
- R2："立即转向"次级图标按钮：仅 `isStreaming` 时出现在发送按钮旁，点击把
  当前输入按 `steer` 发送（D8：不做模式切换）。停止按钮保留。
- R3：`ChatProtocolState` 增加 `queue: { steering: string[]; followUp: string[] }`，
  `queue_update` 全量快照直接替换（单一事实源，不做乐观 append）。
- R4：排队消息在消息流内以带"排队中"徽标的用户消息样式呈现；被消费转为
  正式 UserMessage 后徽标消失——需让 reducer 处理 user 角色 `message_start`
  （当前直接忽略）。
- R5：输入框上方显示 `已排队 ×N` 计数徽标（D7：流内呈现 + 计数徽标双呈现）。

## Acceptance Criteria

- [ ] 流式期间排队一条消息：流内出现带徽标用户消息、计数 +1；当前轮结束后
      该消息转为正式消息、队列清空。
- [ ] 流式期间点"立即转向"：执行方向改变，消息以"转向"徽标呈现。
- [ ] 非流式期间行为不变（Enter = prompt），停止按钮不受影响。
- [ ] `chatProtocol.test.ts` 新增：queue_update reducer 行为、user 角色
      message_start 入流转换、消费后去重。
- [ ] `npm run build` 通过，dist 产物已更新。

## Out of Scope

- 排队撤销/编辑（需新协议 action）；自动判断 steer vs follow_up；
  WS 断线重连期间的队列恢复语义（后端快照自愈，不特殊处理）。

## Notes

- 无前置依赖，可与 PR①③ 并行。触碰面：ChatInput / chatProtocol /
  useLionChat / App / ChatArea（排队消息渲染）。
