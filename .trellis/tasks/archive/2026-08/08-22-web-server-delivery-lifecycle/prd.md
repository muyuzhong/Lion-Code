# Web 服务生命周期与发布

## Goal

让 Web Session 在进程结束时完整关闭，并让 Python 安装产物自带可加载的前端，而不是
依赖源码 checkout 的 ignored `frontend/dist`。

## Requirements

- FastAPI lifespan 按 owner 顺序关闭 Web connection 与 LionCodingSession，均 exactly once。
- Vite 产物进入 `lion_code.server` package data；运行时用 package resource 定位。
- 缺失静态产物时启动明确失败，不提供静默 API-only fallback。
- wheel/sdist 和隔离安装态 smoke test 纳入验证。

## Acceptance Criteria

- [ ] 正常 shutdown、启动失败和重复 close 都不会泄漏/重复关闭 Session。
- [ ] wheel 包含 index 与 hashed assets，从隔离安装可打开页面并调用受保护 API。
- [ ] 前端源码改变后有唯一明确 rebuild 命令，产物差异可审计。

## Dependency

最后执行，基于 S1-S4 的最终 app factory、token 启动 URL 与前端 bundle。

## Out of Scope

CDN、独立前端部署、服务工作进程集群和自动发布流水线。
