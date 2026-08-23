# 桌面切换与 Web 删除：执行计划

## Checklist

1. 在最新 master 验证前三个子任务的 desktop 开发态全链路。
2. 添加可重复的 PyInstaller `onedir` 构建 spec/script 和 sidecar artifact 检查。
3. 配置 electron-builder Windows x64 `extraResources`、NSIS 与 license notices。
4. 添加 package pipeline、安装态资源和版本一致性测试。
5. 在打包态运行 chat MVP/退出回收烟测。
6. 将 FastAPI 收敛为 API-only，删除 Web 启动 helper 和静态挂载。
7. 删除 CLI Web flags/branch、旧 frontend/static、构建脚本、package data、测试和文档引用。
8. 全仓扫描 Web 交付残留与孤儿 import/path。
9. 更新 README、开发命令、目录树、CI 和质量基线。
10. 跑全套门禁与干净 Windows 安装态验收。

## Validation

```powershell
$env:GIT_CEILING_DIRECTORIES='C:\Users\暮羽中'
python -m compileall -q lion_code tests
python -m pytest -q
cd desktop
npm test
npm run typecheck
npm run build
npm run test:e2e
npm run package:win
```

- 按 `.github/workflows/ci.yml` 运行 ruff、format、mypy、radon、vulture、coverage 与 changed-lines 基线检查。
- `rg` 扫描 `--web|server/static|build_frontend|verify_web_delivery|lion-code-capability`，每个剩余命中必须有非旧产品理由。
- 解包 wheel/sdist/NSIS，检查文件清单和许可证。
- 干净 Windows VM 人工 smoke：安装、启动、选择目录、配置、聊天、审批、恢复、退出、卸载。

## Review Gate

- 删除前提供准确 inventory，确认共享协议已迁移且无 CI/user 引用。
- 检查 PyInstaller/electron-builder 许可证 notice 与安装包内容。
- PR 描述记录 Web → Electron 状态所有权迁移、测试矩阵、行数/依赖变化和切换回滚点。

