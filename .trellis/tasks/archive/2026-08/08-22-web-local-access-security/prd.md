# Web 本机访问安全边界

## Goal

让本机 Web UI 成为唯一可用控制面，阻断远程网页、DNS rebinding、无 capability
客户端和局域网访问，同时不引入账号系统。

## Requirements

- 固定 `127.0.0.1` 监听并删除 `--host`/remote surface，无兼容 fallback。
- 每进程生成临时 capability；不持久化、不打印、不进入 query/access log。
- 受保护 REST 使用 Bearer capability，WebSocket 在 accept 前校验 capability、Host、
  Origin；开发 Vite 只允许精确 loopback Origin。
- 前端从启动 URL fragment 导入 capability 到当前 tab，随后清理 URL。
- `--no-browser` 是仅供 headless 健康探测的启动方式：不交付 capability、不提供
  匿名 bootstrap，因此无 capability 客户端只能访问公开 health，不能使用控制面。
- Server 仍只依赖 Application/Core；不得把认证状态放入 Session/Runtime。

## Acceptance Criteria

- [x] foreign Origin、非 loopback Host、错误/缺 token 无法读取 status 或控制 Agent。
- [x] 正确 token 的静态页面、REST、WebSocket 和 Vite proxy 正常。
- [x] token 不出现在日志、配置、session JSONL、URL query 或错误文本。
- [x] CLI 不再接受远程 host；现有 `--port` 保持；`--no-browser` 不打开浏览器、
  不交付 capability，且不因此开放匿名控制面。
- [x] 测试不打开真实浏览器且覆盖安全矩阵。

## Dependency

无子任务依赖；实现基于当前本地 Web baseline。完成 commit 是
`08-22-websocket-protocol-lifecycle` 的显式 base。

## Out of Scope

远程访问、用户账号、TLS、反向代理、持久 token 和匿名 capability bootstrap。
