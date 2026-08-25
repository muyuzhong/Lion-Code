# 执行计划：桌面客户端配置恢复与会话错误链路

## 阶段 0：基线与真实复现

1. 确认当前任务为 `08-25-desktop-config-session-recovery`，保留 `desktop/src/main/protocol.ts` 与 `docs/assets/` 的既有改动。
2. 用隔离 `LION_SIDECAR_STATE_HOME` 启动真实 Electron/sidecar，记录配置 POST、重启后的 GET/status、WebSocket prompt 的完整事件序列。
3. 先定稿真实未配置 API 的丢失层和保存后 Provider 不可用的重启路径，再修改实现。

## 阶段 1：Python 配置恢复与读取契约

1. 修复 `lion_code/config.py` 的 OpenAI 默认 base URL 解析，覆盖保存 OpenAI + 空 base URL 和环境 key 场景。
2. 在 `lion_code/server/models.py` 定义最小 Provider 配置响应模型，在 `lion_code/server/app.py` 增加 GET 读取路由；复用 `session.get_provider_config()`，不改变 POST 回滚语义。
3. 增加 Python 测试：配置响应映射、配置保存后读取、sidecar 重建后 Provider kind/base/api_configured。

## 阶段 2：Renderer 回显与密文切换

1. 在 `desktop/src/renderer/src/backend.ts` 增加 GET client contract 与 guard。
2. 在 `desktop/src/renderer/src/lionRuntime.ts` 增加配置读取方法或等价 adapter port，保证设置打开时读取 canonical state。
3. 在 `desktop/src/renderer/src/WorkspaceShell.tsx` 初始化配置字段、加入 password/text 切换按钮、处理加载/错误/保存状态；保持 key 不进入普通状态显示。
4. 补 Vitest/组件测试，验证重新打开回显、默认掩码、眼睛按钮切换、保存失败不关闭。

## 阶段 3：会话错误与真实 preview 回归

1. 补 Python bridge/application 集成测试和 Renderer 协议测试，确认无 API 的 assistant error 与终态。
2. 必要时对真实缺失层做最小修复；不新增平行 notice/error 协议，不让协议错误吞掉运行终态。
3. 扩展 Playwright 真实 sidecar fixture：隔离 home，验证无 API 发送后 UI 可见错误、streaming 复位；验证配置写入后 sidecar 重建能读回配置。

## 阶段 4：质量与交付

1. `py_compile`、Python 定向测试、桌面 `npm test`、`npm run typecheck`、相关 Playwright。
2. 运行全量测试和质量基线，区分既有 corpus/baseline 噪声与本次回归。
3. 更新 `.trellis/spec/frontend/desktop-chat-experience.md` 与必要的 backend config/sidecar spec，记录显式配置读取、UI 密文和真实 preview 验收契约。
4. 只暂存任务拥有的源代码、测试和规范文件，提交中文描述；不提交 `protocol.ts` 或 `docs/assets/`。

## 风险检查

- 配置读取响应不得进入 `/api/status` 或历史消息。
- 配置读取失败不能让保存流程永久 pending。
- provider/base URL 的修复必须同时覆盖无 env、env key、保存 OpenAI 空 base URL 三种启动路径。
- 真实 preview 回归必须确认使用当前源码构建的 `desktop/out` 和当前 Python sidecar。
