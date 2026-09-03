# Git 审查工作台：在 WorkPanel 提供只读变更快照

## Goal

把 Git 工作区相对 HEAD 的只读变更快照投影到现有 WorkPanel，复用 GitStatusLayer 的 workspace-local/DEVNULL/timeout 约束，但不复用其 3 文件上下文限制。明确状态：non-git/unborn/git-failed/truncated/clean，禁止 Git 写操作。依据 agents/notes/2026-08-30-maka-git-review-workbench.md 与 2026-08-30-maka-to-lion-functional-decision-pack-v2.md。

## Requirements

### 后端只读端口（Python 应用层）

- 新增应用层只读快照读取（独立于 `GitStatusLayer`，不反向耦合 ContextLayer）：
  1. 仅读取当前 workspace 自身 `.git`，不发现祖先仓库；无 `.git` 返回 `non_git` 状态。
  2. 相对 `HEAD` 的只读快照：分支、revision、modified/added/deleted/renamed/untracked 文件列表、单文件增删统计、总增删统计。
  3. 明确状态：`non_git` / `unborn`（无提交）/ `git_failed` / `clean` / `truncated`。Git 读取失败必须呈现为错误，不能伪装成 clean。
  4. 单文件有界 unified diff（按字节上限截断并标记 truncated）；二进制文件只报类型，不做文本化。
  5. 子进程复用已验证约束：`stdin=DEVNULL`、临时文件 stdout、可收敛 timeout；不捕获 PIPE 读线程。
- 仅暴露 REST 只读端点（受既有 capability/本地主机校验保护），不新增 WebSocket 事件，不做任何 Git 写操作。

### 前端投影（Desktop WorkPanel）

- WorkPanel 新增 "Git 审查" 视图：
  1. 显式刷新；连续快速刷新时用请求序号 / revision 丢弃陈旧返回。
  2. 呈现 loading / non_git / unborn / git_failed / clean / dirty(truncated) 等明确状态，不把错误伪装成空列表。
  3. 文件列表带状态徽标与增删统计；展开单文件显示有界 diff（复用既有 diff 高亮）。
  4. Renderer 只通过 REST 读取，不直接启动 Git 进程。

## Acceptance Criteria

- [ ] 后端快照：modified/added/deleted/untracked/binary/rename 均正确归类并统计。
- [ ] 非 Git 工作区返回 `non_git`；unborn 仓库返回 `unborn`；Git 子进程失败返回 `git_failed`，均不伪装为 clean。
- [ ] 文件数超上限或单文件 diff 超字节上限时返回有界结果并标记 `truncated`。
- [ ] REST 端点沿用既有 capability / 本地主机校验；diff 端点拒绝越界路径（绝对路径、`..`、非当前变更文件）。
- [ ] 前端显示所有明确状态；快速刷新不出现旧快照覆盖新快照。
- [ ] 面板打开/刷新不阻塞 Provider 请求开始（同步 REST 走 FastAPI 线程池）。
- [ ] 无任何 Git 写入口（无 stage/commit/discard/checkout/apply patch）。

## Notes

- 真值始终来自当前工作区 Git 状态，UI 只是投影，不引入第二持久真值源。
- 不引入 Review Manager / Git Repository 抽象 / 事件总线；改动最小化为「应用层只读端口 + 两个 REST 端点 + WorkPanel 视图 + targeted tests」。
- 复用时遵循 `.trellis/spec/backend/desktop-sidecar.md`（workspace-local、`--porcelain`、DEVNULL、timeout）与 `server` 层 import 边界（`lion_code.server` 只允许依赖 application/config/core/prompt/server/version）。
