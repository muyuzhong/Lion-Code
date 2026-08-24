# 修复桌面客户端配置持久化、消息无响应与空会话落盘

## Goal

一次性修复 Lion 桌面客户端（Cherry Studio 风格分支 `muyuzhong/desktop-cutover-web-removal`，Python sidecar + assistant-ui Renderer）的三个运行时缺陷。三者均属运行时行为层（`lion_code/config.py`、server/application 会话生命周期、Renderer adapter），不涉及 08-24 纯 UI 移植任务范围；不通过迁移层、兼容层或 fallback 保留旧行为。

## Requirement

### R1. 配置的模型在重启后保持

- 用户通过设置面板保存的 provider/model/base_url/api_key 写入 `~/.lion-code/config.json`；
- 重启（sidecar 重建）后 `resolve_api_credentials` 必须读回已保存的 `model`，使 `/api/status` 与模型选择器显示保存值；
- **env 凭证只覆盖 api_key/base_url**，不导致已保存 model 丢失或回落默认 `claude-opus-4-6`。

### R2. 发送消息后 agent 必须有可感知的回应或明确错误

- 用户输入非空并发送后，agent 不能"卡住不动"、不能无任何消息/错误/notice 回显；
- 未配置 API（或配置失效）时必须表现为明确的不可用提示 / 错误消息，而不是静默；
- 已配置时正常流式回复不受影响（保持协议与 assistant-ui 行为不变）。

### R3. 新建会话不产生零消息持久会话

- 点击"新建任务"只切换内存中的会话身份，**不立即写入 JSONL 文件到磁盘**；
- 会话文件在收到首条真实用户消息（`record_message`）后才落盘；
- 会话列表不出现 `messageCount=0` 的僵尸会话；历史中已存在的 0 消息会话（若有）不在本任务改动所有权（视为遗留数据，不删不改，除非列表过滤成本为零）。

## Constraints

- 不修改 WebSocket/REST wire 协议；不新增可写会话/provider 状态 Owner（继续由 Python 持有 canonical 状态，Renderer 保持投影）。
- 不引入新依赖；优先复用现有 `lion_code.config`、`SessionRecorder`、现有测试基座。
- 遵循四层架构边界：改动落在 `lion_code/config.py`、`lion_code/application/*` 或 `lion_code/runtime/*`（Kernel 层改动需同步架构测试期望值）。若 R2 根因指向 Renderer adapter，则限定 `desktop/src/renderer/src/assistantRuntime.tsx` 等运行时文件，不触碰纯展示组件。
- 保持 `desktop/src/renderer/src/styles.css` 未提交修改不被覆盖/暂存/删除（08-24 任务的隔离约束延续）。
- 每个 bug 独立可验证、独立可回滚；用独立的 commit 承载。

## Acceptance Criteria

- [ ] 写入 config.json 后重启 sidecar，`/api/status` 的 `model` 与模型候选返回保存值；`resolve_api_credentials(env=含 OPENAI/ANTHROPIC key)` 场景下 model 仍来自 config。
- [ ] `resolve_api_credentials` 回归测试覆盖：无凭证 / 有 config 无 env / 有 config + env key / env key + config model 四象限。
- [ ] 未配置 API 时发送消息，客户端有明确错误或 notice 表现，不再无响应；已配置时端到端流式回复正常（e2e/集成用例证明）。
- [ ] POST `/sessions/new` 后 `SessionRepository.list_sessions()` 不含新建的空会话；发首条消息后该会话出现且有 messageCount。
- [ ] `npm test`、`npm run typecheck`、桌面 `vitest`/`playwright chat-protocol` 通过；Python 全量质量门禁与基线比对通过。
- [ ] 三处修复为三个独立 commit，各含对应回归测试；diff 不包含 styles.css 未提交修改。
