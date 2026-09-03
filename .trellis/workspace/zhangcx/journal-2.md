# Journal - zhangcx (Part 2)

> Continuation from `journal-1.md` (archived at ~2000 lines)
> Started: 2026-08-31

---



## Session 67: DeepEval 安全语义轨迹

**Date**: 2026-08-31
**Task**: DeepEval 安全语义轨迹
**Branch**: `muyuzhong/deepeval-analysis-trace`

### Summary

新增安全 Analysis Trace、DeepEval 两项动作诊断及 Harbor/Verified 受控运输；专项验证通过，Linux 在线 smoke 因环境不可用。

### Git Commits

| Hash | Message |
|------|---------|
| `572afc3d` | (see git log) |

### Status

[OK] **Completed**


## Session 68: 修复 DeepEval Analysis Trace 边界并推送

**Date**: 2026-09-01
**Task**: 修复 DeepEval Analysis Trace 边界并推送
**Branch**: `muyuzhong/deepeval-analysis-trace`

### Summary

隔离 Analysis Trace 采集、构造和写盘失败，禁止伪造 sequence 引用，删除 DeepEval aggregate score gate；定向测试 60 passed，Ruff、compileall、diff check 通过。

### Git Commits

| Hash | Message |
|------|---------|
| `ba4b8fed` | (see git log) |

### Status

[OK] **Completed**

## Session: Git 审查工作台 (P0)

**Date**: 2026-09-03
**Task**: Git 审查工作台：在 WorkPanel 提供只读变更快照
**Branch**: `muyuzhong/git-review-workbench`
**PR**: https://github.com/muyuzhong/Lion-Code/pull/156

从 `agents/notes/` 决策包中选定最高优先级 P0（Git 审查工作台）完成：

- 后端：新增 `lion_code/application/git_review.py` 只读快照（non_git/unborn/git_failed/clean/truncated 状态严格分离，untracked 目录折叠采集，单文件有界 diff + 越界路径拒绝），复用 workspace-local/DEVNULL/timeout 约束。
- REST：`GET /api/git/review`、`GET /api/git/review/diff`，走既有 capability 校验。
- 前端：WorkPanel 新增 "Git" 视图（状态渲染 + 文件列表增删统计 + 有界 diff 展开，请求序号丢弃陈旧返回）。
- 测试：`tests/server/test_git_review.py`（真实 git fixture 覆盖状态归类、binary/untracked/truncated、越界路径、端点校验）。

关键经验：
- `_run_git` 不能对 status 输出做 `.strip()`，会破坏 porcelain 首行列对齐导致路径截断（如 `a.py` 变 `.py`）。
- Desktop tsconfig `noUnusedLocals` 下，HEAD 已有 `ChatMessage` unused 基线报错，非本次引入。
- WSL DNS 失效时改用 Windows 侧 git/gh 推送与建 PR。
