# Electron 宿主与 Python sidecar：执行计划

## Checklist

1. 建立 `desktop/` package、electron-vite 三进程入口和测试配置。
2. 实现 `lion://app` 资源协议、安全 `BrowserWindow` 与 CSP/导航策略。
3. 定义 shared/preload 类型，建立 sender-checked IPC handlers。
4. 实现工作区选择与最小连接状态页。
5. 提取 Python API-only app 构造能力并增加 sidecar 进程入口；不删除旧 Web 入口。
6. 实现动态端口、capability、ready JSON 与 stderr 日志分流。
7. 实现 `SidecarController` 启动状态机和有界关闭。
8. 增加 Python、Main、Preload 与 Electron E2E 测试。
9. 运行定向检查和全量 Python/desktop 构建检查。

## Validation

```powershell
python -m pytest -q tests/server
python -m compileall -q lion_code tests
cd desktop
npm test
npm run typecheck
npm run build
npm run test:e2e -- --project=bootstrap
```

## Review Gate

- 审查 capability 数据流、IPC sender 校验、路径穿越、进程回收和 stderr 秘密泄漏。
- 确认 Electron 只在 Interfaces 层，Python Runtime/Capability 不 import desktop/server。
- PR 描述必须列出新增依赖、sidecar 所有权、测试矩阵和删除本 PR 的回滚点。

