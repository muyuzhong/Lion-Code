# FastAPI Web 前后端边界修复执行计划

## 0. 开始前

- [ ] 用户批准本 PRD/design/implement 的最终摘要后，再启动第一个子任务。
- [ ] 从当前 HEAD 创建 `muyuzhong/web-local-access-security`，保留
  `docs/security-design.md`、`tests/integration/test_provider_core_tool_runtime.py`、
  `after1.tmp`、`mypy_human.txt` 等非任务改动；不 stage 它们。
- [ ] 记录 `origin/master` 与当前 HEAD tree 差异；在 Web 基线未独立落地前不创建
  对 master 的混杂 PR。

## 1. S1 `08-22-web-local-access-security`

- [ ] 固定 loopback，删除 CLI/server remote host surface。
- [ ] 实现进程 token、REST dependency/middleware、WS pre-accept 校验与精确 Origin/Host。
- [ ] 前端 API 与 WebSocket 加 capability，fragment 导入后清理 URL。
- [ ] 测试 foreign Origin、错误/缺 token、正确 token、Vite proxy 与 token 不落日志/磁盘。
- [ ] 静态预检、定向测试、提交中文说明；记录 S2 基线 commit。

## 2. S2 `08-22-websocket-protocol-lifecycle`

- [ ] 完成子任务 design/implement 所列 strict action union、single owner 与 Bridge close。
- [ ] 将前端 event handler 抽成可测 reducer/adapter，删除 `any` 与别名 fallback。
- [ ] 修复 tool ID/error/result、server error、message_end、reconnect history。
- [ ] 接通 slash command、continue、compact，并保留类型化 steer/follow-up Hook 入口。
- [ ] 覆盖双 prompt、第二连接、断线 active run、pending approval、并行工具与错误事件。
- [ ] 质量检查并独立提交。

## 3. S3 `08-22-web-provider-settings-integrity`

- [ ] 实现完整配置合并、事务/补偿与原子文件写入。
- [ ] 修复 SettingsModal 草稿同步与 provider/model 配对。
- [ ] 所有配置测试使用 `tmp_path` 或注入 store；增加真实 home 内容/mtime 不变断言。
- [ ] 覆盖 model-only、同 Provider 保留 key、Provider 切换、构建失败、写盘失败。
- [ ] 质量检查并独立提交。

## 4. S4 `08-22-web-session-workspace-isolation`

- [ ] 删除空过滤回退；共享一个 cwd/id eligibility helper 给 list 与 resume。
- [ ] 覆盖零匹配、legacy cwd 缺失、Windows 大小写/resolve 异常和跨 cwd resume。
- [ ] 质量检查并独立提交。

## 5. S5 `08-22-web-server-delivery-lifecycle`

- [ ] 增加 lifespan close 顺序和 exactly-once 测试。
- [ ] 将 Vite 输出纳入 `lion_code.server` package data，移除源码树 fallback。
- [ ] 构建前端、wheel/sdist，检查归档内容并从隔离安装目录 smoke test Web 启动。
- [ ] 质量检查并独立提交。

## 6. 集成检查

- [ ] `python -m py_compile` 覆盖所有改动 Python 文件。
- [ ] `python -m pytest tests/server tests/application/test_coding_session_ports.py -q`。
- [ ] 前端 no-emit typecheck、协议/reducer/Hook tests、生产 build。
- [ ] Application/Server 架构测试与 `lint-imports`。
- [ ] `PYTHONPATH=tests python -m unittest discover tests -p "test_*.py"`。
- [ ] 按 `.github/workflows/ci.yml` 运行 ruff check/format、mypy、radon、vulture、coverage
  基线门禁；只修任务新增 fingerprint，基线漂移按实际输出同步。
- [ ] 核对 `git diff --stat`、任务 owned paths、依赖与净行数；不包含用户现有 dirty files。
- [ ] 父任务做一次跨子任务安全/状态所有权复核并记录回滚点。

## 7. 发布门禁

- [ ] 仅在 Web 基线已形成干净 master 基础后，为每个职责创建独立
  `muyuzhong/<topic>` PR；上游合并后按 tree-equivalent rebase 下游。
- [ ] 每条 PR 描述状态所有权、不变量、测试矩阵、行数/依赖变化、回滚点。
- [ ] 等真实 merge-result CI 全绿后按顺序合并；不把当前 161 文件差异一次推入 PR。
