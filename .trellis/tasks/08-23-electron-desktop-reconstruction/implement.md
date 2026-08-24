# Electron 桌面客户端重构：执行计划

## Ordered Delivery

### Gate 0：开始前

- 等待当前 `memory-system-design-convergence` 子链完成并回到干净、基于 `master` 的工作树。
- 父任务不作为直接实现目标；按四个子任务逐个 `task.py start`。
- 每个子任务使用独立 `muyuzhong/<topic>` 分支和独立 PR。

### Child 1：Electron 宿主与 sidecar

- 按 `08-23-electron-host-sidecar` 的 PRD/design/implement 执行。
- 完成安全窗口、Preload、workspace、sidecar ready/退出契约与开发态 E2E。
- 通过后再允许 Child 2/3 接入真实桌面运行时。

### Child 2：assistant-ui 协议适配

- 按 `08-23-assistant-ui-protocol-adapter` 执行。
- 保持协议 reducer 契约测试，建立单一 assistant-ui Runtime。
- 不同时重做最终视觉。

### Child 3：Lion 桌面聊天体验

- 按 `08-23-lion-desktop-chat-experience` 执行。
- 使用 Child 2 的 Runtime 完成页面、组件与设计系统。
- 不加入 Out of Scope 能力。

### Child 4：切换与 Web 删除

- 仅在 Child 1–3 合并且各自 CI 通过后开始。
- 完成 PyInstaller/electron-builder Windows x64 打包与安装态烟测。
- 删除 Web 产品和旧 UI，更新文档、package data、测试与质量基线。

## Parent Integration Validation

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

- 对照 `.github/workflows/ci.yml` 跑 Python 全套质量门禁并同步基线。
- 在干净 Windows x64 环境安装 NSIS 包，验证选择工作区、首轮配置、流式聊天、审批、会话恢复和退出无残留进程。
- 运行 `git diff --check`，复核删除后的 wheel/sdist 不再包含静态前端。

## Review Gates

- 每个 PR 描述状态所有权、保持不变的不变量、测试矩阵、行数/依赖变化和回滚点。
- 每个 PR 不超过一个职责迁移；超过 20 个文件时拆出机械资源或生成产物提交。
- 链式 PR 按依赖顺序合并，上游 squash 后 rebase 下游并等待真实 merge-result CI。
- 最终集成检查确认 Runtime 不依赖 Electron/Application，Electron 不持有 Provider/Session 可写状态。

## Risk and Rollback Points

- sidecar ready 协议失败：回滚 Child 1，不触碰 Python session 数据。
- Adapter 语义漂移：回滚 Child 2，并以现有协议契约测试定位差异。
- 视觉重构不达标：回滚 Child 3，不影响宿主与协议层。
- 打包或删除遗漏：回滚 Child 4，恢复旧 Web 入口后修复，不引入兼容双入口。

