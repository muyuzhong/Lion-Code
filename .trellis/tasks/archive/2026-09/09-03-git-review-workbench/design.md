# Git 审查工作台 — 技术设计

## 1. 边界与真值来源

- 真值：当前工作区 Git 状态（`HEAD`、porcelain status、numstat、diff）。UI 只读投影，不产生持久状态。
- `GitStatusLayer`（`lion_code/capabilities/git_status/capability.py`）保持 ContextLayer 不动；本功能新增独立只读实现，Desktop 不反向 import capability。
- 依赖方向：`server/app.py`（REST 端点）→ 应用层只读函数（新模块）→ `subprocess`（Git）。`lion_code.server` 只允许依赖 application/config/core/prompt/server/version，因此新读取逻辑放在 `lion_code.application` 包内，由 server 调用。
- Git 子进程约束复用 `_git_output` 已验证模式：仅认 `cwd/.git` 自身、`stdin=DEVNULL`、临时文件 stdout、`timeout`、不捕获 PIPE 读线程。但 `_git_output` 返回 `""` 无法区分「non-git / unborn / git 失败」，且限制为 3 条路径，故新模块需要自己的读取实现（保留相同子进程约束）。

## 2. 后端：应用层只读快照模块

新增 `lion_code/application/git_review.py`，提供纯同步函数（由 FastAPI 同步端点在线程池运行，不阻塞事件循环 / Provider）：

```python
# 快照 DTO（dataclass，server 层转 pydantic）
@dataclass(frozen=True)
class GitReviewFile:
    path: str
    status: Literal["modified", "added", "deleted", "renamed", "untracked"]
    additions: int | None = None   # None 表示 untracked/binary 无 numstat
    deletions: int | None = None
    binary: bool = False

@dataclass(frozen=True)
class GitReviewSnapshot:
    state: Literal["ok", "non_git", "unborn", "git_failed"]
    branch: str
    revision: str                  # HEAD sha（stale-return 判别）
    clean: bool
    truncated: bool
    files: tuple[GitReviewFile, ...]
    additions_total: int
    deletions_total: int

@dataclass(frozen=True)
class GitReviewFileDiff:
    path: str
    diff: str
    binary: bool
    truncated: bool
    untracked: bool = False
```

读取流程 `read_git_review(cwd)`：

1. `(cwd / ".git").exists()` 为 False → `state="non_git"`。
2. `git rev-parse --verify HEAD` 失败 → `state="unborn"`（无提交），files 为空、clean=False。
3. 读取 `branch --show-current`、`status --porcelain --untracked-files=normal`（目录折叠，兼顾 untracked 采集与爆量控制；刷新是显式动作，不受 ContextLayer 每次渲染的阻塞约束）、`diff --numstat HEAD`。
4. 解析 porcelain：`XY path`（X/Y 位为 M/A/D/R/U），映射 modified/added/deleted/renamed/untracked。
5. 解析 numstat：`adds\tdels\tpath`，二进制行 `-\t-` → binary=True。匹配路径得到每文件增删；untracked 无 numstat，增删为 None 且不计入总增删。
6. 汇总 `additions_total/deletions_total`；文件数超上限（例如 500）→ `truncated=True`，只保留前 N 条。
7. `revision = git rev-parse HEAD` 的 sha。

单文件 diff `read_git_file_diff(cwd, path)`：

- 校验 `path` 是相对路径、resolve 后仍在 cwd 内、且属于当前变更集（重新跑一次 status 对比，防止任意路径读取）。
- `git diff HEAD -- <path>` 有界截断（例如 64KB）→ `truncated=True`；二进制（numstat 为 `-`）→ `binary=True, diff=""`；untracked → `untracked=True`。
- 越界/非变更路径返回 `None`。

### 上限常量（模块内）

- `MAX_FILES = 500`、`MAX_DIFF_BYTES = 64 * 1024`、`GIT_TIMEOUT = 2`（与 `_git_output` 一致）。

## 3. 后端：server REST 端点

`lion_code/server/app.py` 的 `api` router（已带 `require_local_capability`）新增：

```python
@api.get("/git/review", response_model=GitReviewResponse)
async def get_git_review() -> GitReviewResponse:
    snapshot = read_git_review(session.cwd)
    return _to_response(snapshot)   # dataclass → pydantic

@api.get("/git/review/diff", response_model=GitReviewDiffResponse)
async def get_git_review_diff(path: str) -> GitReviewDiffResponse:
    result = read_git_file_diff(session.cwd, path)
    if result is None:
        raise HTTPException(status_code=422, detail="路径不在当前 Git 变更中")
    return _to_diff_response(result)
```

- `session.cwd` 为当前 workspace 根（`LionCodingSession.cwd`）。
- pydantic 响应模型加到 `lion_code/server/models.py`（REST 接口模型区），字段名沿用 camelCase alias（与既有端点一致）。
- 同步端点（`def` 而非 `async def`，或用 `run_in_threadpool`）→ FastAPI 线程池执行，不阻塞 WS / Provider。`read_git_review` 是纯同步函数，定义 `def` 端点即可。
- 不新增 WebSocket 事件；无写操作端点。

## 4. 前端：REST client + WorkPanel 视图

### `desktop/src/renderer/src/backend.ts`

- 新增类型 `GitReviewFile`、`GitReviewSnapshot`、`GitReviewDiff` 与 `isGitReviewSnapshot` / `isGitReviewDiff` guard（沿用严格 schema 校验风格）。
- `LionRestClient.fetchGitReview()`、`fetchGitReviewDiff(path)`：走 `readJson/readArray` 既有授权路径。

### `desktop/src/renderer/src/lionRuntime.ts` / `assistantRuntime.tsx`

- `LionAssistantRuntimeAdapter` 增加 `fetchGitReview()` / `fetchGitReviewDiff(path)`，透传 REST 结果（不做持久化），沿用 `metadataError` 错误处理风格。

### `desktop/src/renderer/src/components/WorkPanel.tsx`

- 视图类型扩展：`"工作面板" | "浏览器" | "文件" | "Git"`。
- `"Git"` 视图渲染 `GitReviewTab`：
  - 挂载 + 刷新按钮触发 `adapter.fetchGitReview()`；用递增请求序号丢弃陈旧返回。
  - 状态渲染：loading / non_git / unborn / git_failed（错误态文案）/ clean / dirty（含 truncated 提示）。
  - 文件列表：状态徽标（M/A/D/R/U）、`+adds/-dels`；点击展开拉 `fetchGitReviewDiff`，用既有 diff 高亮（`.diff-result` span 类）渲染有界 diff；binary 显示「二进制文件」。
- 不引入全局状态；面板本地 `useState` 即够，符合「UI 只是投影」。

### 样式

- 复用 `transcript.css` 的 `.diff-result/.diff-add/.diff-remove/.diff-hunk`；文件列表新增少量 `.git-review-*` 样式（`shell.css`）。

## 5. 测试计划

### Python `tests/server/test_git_review.py`

- fixture：`tmp_path` 内 `git init`、配置 user、提交基线，构造 modified/added/deleted/renamed/untracked/binary。
- 断言：状态归类正确、增删统计正确、binary 标记、`clean`、`truncated`（>MAX_FILES）。
- 非 git 目录 → `non_git`；只 `git init` 无提交 → `unborn`；mock `subprocess.run` 抛异常 → `git_failed`。
- `read_git_file_diff`：正常 diff、二进制、untracked、越界路径（绝对/`..`/非变更文件）→ None。
- 端点级：`GET /api/git/review`、`/api/git/review/diff` 需 capability（沿用 `test_server_api.py` 模式）；diff 越界返回 422。

### Desktop `desktop/tests/renderer/`

- `WorkPanel` Git 视图：mock fetch 返回快照 → 渲染文件列表、clean/non_git 状态；展开文件 → 渲染 diff；快速刷新序号丢弃陈旧返回。
- REST guard：非法快照 schema 拒绝（可并入 `assistantRuntime.test.ts` 或新建 `gitReview.test.ts`）。

## 6. 不做（明确边界）

- 不做 stage/unstage/commit/discard/checkout/apply patch、远程 PR、评论、Review Manager、Git Repository 抽象、事件总线。
- 不把 `GitStatusLayer` 改造成 UI 服务；不新增第二真值源。
- 不引入任何新依赖。
