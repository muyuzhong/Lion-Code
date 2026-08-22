# FastAPI Web 前后端边界修复

## Goal

把当前 FastAPI + React 初版从仅能演示的 happy path 收敛为安全、类型一致、
可恢复且可发布的本地 Web 前端；保留现有 UI 与 Application/Core 所有权边界，
不全盘重写前端，也不新增兼容层。

## Background

- 当前 REST、会话恢复和基础 WebSocket 流式路径可运行，定向服务端测试为
  `8 passed`，Server Ruff 与 Frontend TypeScript 检查通过。
- `lion_code/server/app.py:43-49,221-225` 接受任意跨域 REST 与 WebSocket
  连接；实测外部 Origin 可连接并控制 Agent/审批通道。
- `lion_code/server/app.py:176-201` 对稀疏 Provider 配置先改运行时、后以缺失
  参数调用 `save_api_config`；实测模型单字段更新返回 500 且运行时已改变。
- `lion_code/server/bridge.py:107-159` 未使用 `server/models.py` 已定义的上行
  模型；实测字符串 `false` 被解释为批准。
- `frontend/src/hooks/useLionChat.ts:105-175` 与 Core camelCase 事件字段漂移，
  且未处理 Server error、断线重同步和并行工具结果关联。
- Session 交互回调是实例级单一所有者；当前多个 Bridge 会互相覆盖，先断开的
  Bridge 会清空仍在线 Bridge 的回调。
- `frontend/src/components/chat/SettingsModal.tsx:14-38` 缓存初始化默认值并覆盖
  延迟加载的真实配置；Plan 按钮把 `/plan` 当普通 prompt 发送。
- `lion_code/server/app.py:133-135` 在当前 workspace 无会话时回退为全部会话。
- `tests/server/test_server_api.py:132-152` 写入真实 `~/.lion-code/config.json`；
  已确认必须改为临时/注入配置存储。
- FastAPI 无关闭 lifespan，`frontend/dist` 也未进入 Python 发布物。

## Requirements

- R1 安全接入：Web 模式只允许本机浏览器。服务固定监听 loopback，删除任意远程
  host 暴露语义；未持有每进程临时 capability token 或来源不合法的请求不得调用
  REST、建立 WebSocket、提交提示或回应审批；开发态 Vite 代理仍可使用。
- R2 上行协议：所有 WebSocket action 使用判别联合校验；类型错误返回明确协议
  错误，绝不通过 Python truthiness 改变安全语义。
- R3 下行协议：前端以明确的事件联合消费 canonical camelCase wire contract，
  工具调用按 `toolCallId` 关联，正确显示结构化结果与错误。
- R4 连接生命周期：一次会话只有一个明确的 Web 交互所有者；断线、重连、取消、
  活动 run、审批 future 与 notice task 均有确定收敛行为，不允许静默丢事件。
- R5 配置一致性：Provider/model/API key/base URL 的局部更新必须原子地形成完整有效
  配置；失败不留下磁盘与运行时分叉，设置草稿以服务器状态为准。
- R6 功能接线：Plan/command、continue、compact、cancel、steer/follow-up 及相关
  queue/compaction/retry/error 事件按现有 Application contract 接入；Skills 若无
  当前 UI 消费场景，只保留 API 并明确延后 UI。
- R7 workspace 隔离：列表和恢复只允许当前 cwd 的会话；没有匹配项时返回空集。
- R8 生命周期与发布：服务关闭必须调用 `session.aclose()`；安装后的 Web 模式必须
  包含并能加载已构建前端，或在构建/安装阶段明确失败，不能静默 404。
- R9 测试隔离：任何测试不得读写真实用户配置、会话或浏览器；覆盖安全来源、非法
  载荷、部分配置、并行工具、异常、断线/多连接、workspace 空集与 shutdown。
- R10 保持分层：Server 只经 Application/Core 接触运行时；不把 Web 状态塞回
  Runtime，不创建第二份 canonical history，不修改既有 compaction/permission
  所有权。
- R11 最小实现：删除失效代码与旧分支，不保留兼容别名、fallback 或预防性抽象。

## Acceptance Criteria

- [ ] 外部 Origin 和缺少有效会话凭证的 REST/WS 请求在执行任何 Agent 操作前被拒绝。
- [ ] `approved: "false"`、非法 action/choice、缺字段和错误类型均不能进入回调。
- [ ] 模型单字段切换与不重新输入 API key 的设置保存成功；任一步失败时运行时与磁盘
  保持旧值。
- [ ] 两个并行工具调用的开始、结果和错误在前端按 ID 正确关联；Server/provider 错误
  会结束 streaming 并展示给用户。
- [ ] 断线期间不会留下无人拥有的审批或静默运行；重连后的 transcript 与 canonical
  history 一致；多标签页行为符合选定的连接所有权策略。
- [ ] Plan 按钮实际调用 command contract；已声明纳入 MVP 的控制 action 与事件有
  前后端测试。
- [ ] 当前 cwd 无历史时 `/api/sessions` 返回空列表，且不能恢复其他 cwd 会话。
- [ ] FastAPI shutdown 恰好关闭一次 Session；wheel/sdist 的 Web 启动可加载前端。
- [ ] Server 定向测试、前端协议/Hook 测试、架构门禁、全量质量门禁通过，测试后用户
  配置内容和 mtime 均未变化。
- [ ] 每个子 PR 只承载一个职责迁移，包含状态所有权、不变量、测试矩阵、行数/依赖
  变化和回滚点。

## Out of Scope

- 重写现有 React 视觉组件或更换 UI 框架。
- 多用户账号、云端部署、数据库会话服务或跨设备同步。
- 修改 Core/Harness/Runtime 的 canonical event、session 或 permission 语义。
- 为已删除或错误的 Web 协议保留兼容层。

## Notes

- 采用父任务统筹、子任务独立提交/PR；父任务不直接承载跨职责实现。
- 当前工作树原有未跟踪文件 `after1.tmp`、`mypy_human.txt` 不在本任务范围内。
- 用户已决定 Web 模式只支持本机访问；远程认证、TLS、反向代理明确不在范围内。
- 当前 Web 初版只存在于本地 HEAD，尚未进入 `origin/master`；当前分支对应的 PR #73
  已合并且远端分支不代表本地树。实现可以在新分支基于当前 HEAD 分职责提交，但在
  Web 基线被单独落地前，不创建会把既有 161 文件差异一并带入的误导性 master PR。
