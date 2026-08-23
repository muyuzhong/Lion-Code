# assistant-ui 协议适配：执行计划

## Checklist

1. 锁定兼容的 assistant-ui/Streamdown 版本与许可证并更新 desktop 依赖。
2. 迁移 chat types、ClientAction、ServerEvent decoder、reducer 和纯工具函数。
3. 将 REST/capability/WebSocket 访问改为显式 `BackendBootstrap` 注入，删除 window URL/sessionStorage 假设。
4. 实现 `LionAssistantRuntimeAdapter` 与 AssistantRuntimeProvider 装配。
5. 实现历史加载、session switch、重连与 disconnect 收敛。
6. 实现 prompt/continue/steer/follow-up/cancel/compact/审批动作映射。
7. 将 Tool、Reasoning 与 Streaming Markdown 投影为 assistant-ui parts。
8. 迁移并扩充协议契约测试；增加 Runtime Adapter 和 transport 集成测试。
9. 删除 `useLionChat` 的状态 Owner 角色，但保留 Child 3 尚需的最小过渡入口时必须明确为同一 Adapter 包装。

## Validation

```powershell
cd desktop
npm test -- chatProtocol
npm test -- assistantRuntime
npm run typecheck
npm run build
npm run test:e2e -- --project=chat-protocol
python -m pytest -q tests/server tests/application
```

## Review Gate

- 逐项对照 frontend queue/runtime/tool display specs。
- 检查 assistant-ui 未成为 Session/Provider canonical state Owner。
- 检查断连、审批、取消和协议非法输入的 fail-closed 行为。
- PR 描述列出协议不变量、依赖变化、测试矩阵和回滚点。

