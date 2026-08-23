# assistant-ui 协议适配：设计

## Components

```text
BackendBootstrap
   ├─ LionRestClient
   └─ LionWebSocketTransport
             ↓ decoded ServerEvent
      LionProtocolReducer
             ↓ projection
      LionAssistantRuntimeAdapter
             ↓
      AssistantRuntimeProvider
```

Transport、协议 reducer 和 assistant-ui Adapter 分离：Transport 只收发，Reducer 只折叠 Lion 事件，Adapter 只转换 assistant-ui 所需 message/thread/action 形态。

## Canonical Data Rules

- REST history 每次连接/切换 Session 后替换已完成消息快照。
- WS 只负责活动 run；连接关闭触发 `disconnected` 终态收敛，不伪造成功。
- 本地乐观追加只允许初始 `prompt` UserMessage；服务端 user `message_start` 必须按现有规则去重或消费队列。
- assistant-ui message IDs 由 Lion wire IDs 优先；临时 ID 只存在于当前投影且在 canonical history 替换时消失。

## Action Mapping

| assistant-ui/user intent | Lion action |
| --- | --- |
| submit new prompt | `prompt` |
| continue empty composer | `continue` |
| steer running turn | `steer` |
| enqueue after current turn | `follow_up` |
| stop | `cancel` |
| manual compact command | `compact` |
| permission answer | `confirm_response` |
| plan decision | `plan_approval_response` |

未批准的 regenerate/edit/branch/attachment assistant-ui action 不注册能力，UI 也不显示虚假入口。

## Tool and Reasoning Projection

- Tool 使用 `toolCallId` 稳定关联，result 内容按 Lion `ToolResult` 文本/图片块读取；MVP 只展示文本。
- Tool 分类只以 `toolName` 和已定义展示映射决定，禁止按 args 形状猜测 agent 工具。
- Reasoning 增量保留独立 part；流式结束后自动收敛，但不写回 Python history。
- Streamdown 只消费 assistant 文本 part，不参与消息状态或工具状态。

## Failure and Reconnect

- bootstrap/HTTP/WS 错误进入显式 transport 状态；协议非法事件产生 protocol error，不尝试宽松解析。
- 重连成功后先拉 REST canonical history，再继续 WS；queue 和本地 metrics 按既有契约重置。
- pending confirmation 在断连时清除，后端 Bridge 负责拒绝 pending future。

## Rollback

回滚本 PR 恢复 Child 1 的最小连接状态页；不改变 Python wire schema、Session JSONL 或 Provider 状态。

