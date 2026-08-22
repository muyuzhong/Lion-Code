# WebSocket 协议与连接生命周期

## Goal

让 WebSocket 上下行协议与 canonical Application/Core event 完全一致，并为单个
LionCodingSession 建立唯一、可关闭、可恢复的浏览器连接所有权。

## Requirements

- strict discriminated action union；禁止 raw dict truthiness/coercion。
- 第二连接不覆盖现有 callback owner；断线必须 deny approvals、cancel run、收集 task、
  unbind callbacks。
- 前端使用 canonical camelCase event union；tool/error/final message 按真实结构归并。
- 重连从 `/api/messages` 恢复 canonical transcript，丢弃 provisional state。
- Plan/slash command、continue、compact 可从输入控制面访问；steer/follow-up 保留类型化
  Hook 入口，不在本 PR 增加复杂队列 UI。

## Acceptance Criteria

- [x] 字符串 false 与非法 choice/action 不进入审批/Plan callback。
- [x] parallel tool 结果按 toolCallId 对应，isError 正确呈现，结果显示文本内容。
- [x] Server/provider/protocol error 结束 streaming 并可见。
- [x] 第二连接被拒绝且不改变第一个 owner；断线后无 pending future/background task。
- [x] 重连 transcript 等于 canonical `/api/messages`。
- [x] Plan 按钮实际走 command contract；continue/compact 有端到端测试。

## Dependency

必须基于 `08-22-web-local-access-security` 的 capability-aware API/WS client。

## Out of Scope

多浏览器协作、服务端 event replay buffer、Web 层第二份历史和队列编辑 UI。
