# assistant-ui 协议适配

## Goal

以 `assistant-ui` 为唯一聊天交互 Runtime，将 Lion 的 REST 历史、WebSocket 流式事件和客户端动作映射为稳定的桌面聊天状态，同时保持 Python Application 的 canonical 状态所有权。

## Dependencies

- 依赖 `08-23-electron-host-sidecar` 提供 `desktop/` package、Renderer 启动与 backend bootstrap 类型。
- 协议 reducer、类型和纯单测迁移可先准备，但本 PR 合并前必须基于 Child 1 最新 master。
- `08-23-lion-desktop-chat-experience` 必须等待本任务的 Adapter API 与契约测试稳定。

## Requirements

- 将现有 `chatProtocol` 解码、reducer、队列、轨迹所需的共享事件类型迁入 `desktop/src/shared` 或 Renderer 无关模块。
- 使用 assistant-ui 自定义/External Store Runtime 接入现有状态，不接入 Vercel AI SDK 消息状态。
- REST `/api/messages` 是已完成历史的 canonical bootstrap；WS 事件驱动当前 run 的增量状态。
- 保留 `queue_update` 全量替换与 user `message_start` 本地消费出队规则。
- 保留 retry/compaction notice 生命周期、Reasoning 计时和 Tool 按 `toolCallId` 配对规则。
- 将 assistant-ui composer/thread actions 映射到现有 ClientAction，不新增同义 action。
- 审批请求在断连或连接关闭时按后端契约 fail closed；不能由 UI 静默批准。
- Provider、Session 与 Skill REST API 继续使用现有 Application 门面，不进入 assistant-ui Runtime 可写状态。
- 删除 `useLionChat` 的产品状态所有权；允许留下极薄的 React Provider/transport 装配。

## Acceptance Criteria

- [ ] assistant-ui Thread 能从 REST history 渲染当前 Session。
- [ ] WS text/thinking delta 只更新当前 assistant message，不产生重复消息。
- [ ] Tool start/update/end 正确映射 running/completed/error，并支持乱序工具结束。
- [ ] Prompt、Continue、Steer、Follow-up、Cancel、Compact、Confirm 与 Plan Approval 编码符合后端严格模型。
- [ ] queue、retry、compaction、disconnect 和 session switch 保持现有契约测试语义。
- [ ] assistant-ui 是唯一 Thread/Composer 消息状态源；不存在并行自研 React chat store。
- [ ] Provider/Session canonical state 仍由 Python 持有，Adapter 只做投影。
- [ ] 协议单测、Adapter 单测和与 Fake WebSocket/REST 的集成测试通过。

## Out of Scope

- 最终视觉、主题、侧栏和设置页面。
- 新增附件、分支消息、重新生成或编辑已发送消息。
- 修改 Python Core event schema，除非现有协议无法满足已批准的 MVP 行为且先回到父任务重新评审。

