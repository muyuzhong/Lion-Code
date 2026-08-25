# 实施计划：桌面客户端模型输出闭环

## 阶段 0：基线与复现

1. 启动任务前复核 `git status`，只保留本任务文件和既有用户改动；不暂存 `desktop/src/main/protocol.ts`、`docs/assets/`。
2. 先运行现有 Provider、application、server、Renderer 定向测试，记录当前基线。
3. 增加隔离本地 OpenAI-compatible fixture，使用真实 Electron + Python sidecar 复现成功、HTTP 错误、首响应停滞和失败后重试。
4. 依据 fixture 收到请求、Provider 事件和 WS 下行事件定位唯一丢失层；若当前代码已能在超时后报错，则先验证是否只是默认等待窗口过长。

## 阶段 1：最小后端修复

1. 若高概率假设成立，在 `stream_provider_post` 共享边界补明确的请求/首响应 timeout 收敛，把超时与网络错误映射为安全的 `ProviderErrorEvent`。
2. 验证重试不会吞掉最终错误；保持取消能够立即中止，正常 SSE 流和工具闭环不回归。
3. 若响应兼容性被证实，修正当前 OpenAI-compatible payload/parser 的统一契约；不添加厂商名称 fallback。
4. 若异常路径仍无法让 Session/bridge 消费者归位，再做最小 Session/bridge 终态修复，并补事件顺序测试。

## 阶段 2：Renderer 终态修复（仅在证据需要时）

1. 若事件已经到达但页面仍显示运行中，补 `shared/chat.ts` reducer 或 `lionRuntime.ts` transport 状态清理。
2. 保证 provisional assistant 只保留一个错误终态，发送框恢复后可再次 prompt；严格 decoder 继续 fail closed。
3. 不通过 localStorage 或 Renderer 自有 store 规避 Python canonical history。

## 阶段 3：回归与质量门禁

1. 补齐 Python provider/stream、application/session、server/bridge 和 Renderer protocol 定向测试。
2. 运行 `cd desktop && npm test`、`npm run typecheck`、`npm run build`，以及真实 sidecar Playwright 项目；配置本地 SSE fixture，不访问第三方 API。
3. 运行项目要求的 `py_compile`、定向 unittest/pytest、ruff/质量基线；区分本次新增失败与既有基线噪声。
4. 按 `.trellis/spec/` 实际变化同步必要规范与 cross-layer thinking guide，检查模板同步要求。
5. 每个完成的独立改动使用中文提交描述；只暂存本任务拥有的文件，最终再汇报提交和验证结果。

## 停止条件

- 若本地 fixture 成功闭环、错误也能在明确 timeout 内归位，而用户实际 endpoint 仍无输出，则不继续猜测第三方协议；请求用户提供脱敏的 Provider 类型、endpoint 是否含 `/v1`、模型名和等待时长。
- 若实现需要改变配置格式、磁盘凭证或主进程协议，超出本任务，先停下请求新的范围授权。

## 实际完成记录

- 真实 Electron + Python sidecar 复现确认：发送后 Provider 一次请求都未收到，sidecar 事件循环被同步 Git 上下文扫描阻塞在 `GitStatusLayer`。
- 修复 `GitStatusLayer` 与基础动态提示：仅读取 workspace 自身的 `.git`，状态命令不展开未跟踪文件；非 Git workspace 直接跳过 Git 上下文，避免发现用户目录祖先仓库。
- 增加真实本地 OpenAI-compatible SSE 回归：验证配置保存/读回、合法流输出、HTTP 400 错误终态、发送框恢复及失败后再次发送。
- 验证通过：Python 定向 pytest 60 项、上下文/提示测试 21 项、全量 unittest 415 项（2 项既有 skip）、桌面 Vitest 55 项、typecheck、build、完整 `sidecar-real` 3 项 Playwright。
- 保留未参与本任务的 `desktop/src/main/protocol.ts` 与 `docs/assets/`，未修改 Provider 配置格式或凭证存储策略。
