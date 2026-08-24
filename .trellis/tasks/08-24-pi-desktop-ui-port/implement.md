# PI-Desktop UI 移植：执行计划

## Gate 0：隔离

1. 验证当前主工作树只有用户未提交的 `desktop/src/renderer/src/styles.css` 修改。
2. 从提交 `ee6095f` 创建独立 worktree 和 `muyuzhong/pi-desktop-ui-port` 分支。
3. 在独立 worktree 中启动本任务；不得 stash、reset 或暂存原工作树修改。

## Implementation

1. 增加 `lucide-react`，建立 PI 风格语义 Token 与模块化样式入口。
2. 提取纯展示 `DesktopSidebar` 与 `ConversationTopbar`，让 `WorkspaceShell` 保留所有状态/动作接线。
3. 将 `ChatThread` 的消息布局改为连续工作流样式，保留 assistant-ui Thread/Message/Composer primitives。
4. 增加 Tool、Reasoning、运行结果、Permission 和 Plan 的小型展示组件；继续消费 Lion canonical projection。
5. 重做 Composer chrome、运行/停止状态、模型/权限/队列提示，但不增加新动作或 store。
6. 收敛设置、空状态、连接/错误状态和主题表现。
7. 增加组件契约测试、窗口尺寸断言与关键状态截图。

## Validation

```powershell
Set-Location desktop
npm test
npm run typecheck
npm run build
npm run test:e2e -- --project=chat-protocol --workers=1
npm run test:e2e -- --project=bootstrap --workers=1
```

- 运行 1280x720 与 2560x1440 的 document overflow、Composer/审批可达性和深浅主题截图检查。
- 对比修改前后 ClientAction、REST/WS 和 assistant-ui Runtime 文件哈希/diff，确认行为边界未改变。
- 在原工作树复核 `git status --short`，确认用户未提交 `styles.css` 修改未变化。
- 运行 `git diff --check`。

## Review Gate

- 审查是否存在 PI `app-store`、API、shared type 或 workspace package 残留 import。
- 审查是否新增消息/session/provider/approval 可写状态。
- 审查工具结束乱序、重连、审批 send failure 和 Escape 安全动作是否仍由既有契约处理。
- 审查所有新增图标、样式和组件是否确实被使用，无隐藏工作面板或未来功能占位实现。

## Rollback Point

回滚本任务 UI 提交即可恢复 `ee6095f` 的 Renderer；无需回滚 Electron Main、Python sidecar 或 session 数据。
