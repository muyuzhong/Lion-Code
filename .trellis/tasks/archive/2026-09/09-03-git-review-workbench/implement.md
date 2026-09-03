# Git 审查工作台 — 实施计划

## 目标

把 Git 工作区相对 HEAD 的只读变更快照投影到现有 WorkPanel。后端应用层只读快照 + 两个 REST 端点 + 前端 WorkPanel Git 视图。不做任何 Git 写操作，不引入新依赖、新抽象。

## 步骤

### Step 1：后端应用层只读模块 `lion_code/application/git_review.py`

新增模块，纯同步函数，复用已验证子进程约束：

- `GIT_TIMEOUT = 2`、`MAX_FILES = 500`、`MAX_DIFF_BYTES = 64 * 1024`。
- `_git_output(cwd, *args) -> str`：仅认 `cwd/.git`、`stdin=DEVNULL`、临时文件 stdout、timeout、不捕获 PIPE；失败返回 `""`（与 `GitStatusLayer._git_output` 一致，注释说明非 git/unborn/git 失败靠前置检查区分）。
- `read_git_review(cwd: Path) -> GitReviewSnapshot`：
  - 无 `.git` → `state="non_git"`；`rev-parse --verify HEAD` 失败 → `state="unborn"`；`_git_output` 返回空但存在 `.git` 且 branch 也空 → 仍视为 git 失败需单独区分（见下）。
  - 读取 branch、`status --porcelain --untracked-files=normal`、`diff --numstat HEAD`、`rev-parse HEAD`（revision）。
  - 解析 porcelain 与 numstat，构造文件列表与总增删；超 MAX_FILES → truncated。
  - 区分 `git_failed`：用 `_git_run` 变体返回 returncode（`status`/`numstat` 命令 returncode != 0 或抛 OSError/SubprocessError → git_failed），避免把 Git 失败伪装成 clean。
- `read_git_file_diff(cwd, path) -> GitReviewFileDiff | None`：
  - 校验：`path` 相对、`Path(path).resolve()` 仍在 `cwd.resolve()` 内、且属于当前变更集（重新读 status 对比，防任意路径读取）。
  - `git diff HEAD -- <path>` 截断到 MAX_DIFF_BYTES → truncated；numstat `-` → binary；untracked → untracked=True, diff=""。
  - 越界/非变更 → `None`。

### Step 2：后端 pydantic 响应模型 `lion_code/server/models.py`

新增（REST 接口模型区，camelCase alias 与既有端点一致）：

```python
class GitReviewFileItem(BaseModel):
    path: str
    status: Literal["modified", "added", "deleted", "renamed", "untracked"]
    additions: int | None = None
    deletions: int | None = None
    binary: bool = False

class GitReviewResponse(BaseModel):
    state: Literal["ok", "non_git", "unborn", "git_failed"]
    branch: str
    revision: str
    clean: bool
    truncated: bool
    files: list[GitReviewFileItem]
    additions_total: int
    deletions_total: int

class GitReviewDiffResponse(BaseModel):
    path: str
    diff: str
    binary: bool
    truncated: bool
    untracked: bool = False
```

### Step 3：后端 REST 端点 `lion_code/server/app.py`

在 `api` router（已带 `require_local_capability`）新增同步 `def` 端点（FastAPI 自动线程池执行，不阻塞 WS/Provider）：

- `GET /api/git/review` → `GitReviewResponse`
- `GET /api/git/review/diff?path=...` → `GitReviewDiffResponse`，`None` → 422

`from lion_code.application.git_review import read_git_review, read_git_file_diff`；`cwd=session.cwd`。

### Step 4：后端测试 `tests/server/test_git_review.py`

- 用真实 git 在 `tmp_path` 建 fixture（`git init`、config user、提交基线）。
- 覆盖：modified/added/deleted/renamed/untracked/binary 归类与统计；clean；truncated（>MAX_FILES）；non-git；unborn；git_failed（mock subprocess 抛异常或伪造 returncode）。
- diff：正常、二进制、untracked、越界路径（绝对/`..`/非变更）→ None。
- 端点：需 capability（401）、`/api/git/review`、`/api/git/review/diff` 越界 → 422。
- 验证 workspace-local：祖先仓库不被发现。

### Step 5：前端 REST client `desktop/src/renderer/src/backend.ts`

- 类型 `GitReviewFile`/`GitReviewSnapshot`/`GitReviewDiff` + guard `isGitReviewSnapshot`/`isGitReviewDiff`（严格 schema）。
- `LionRestClient.fetchGitReview()` / `fetchGitReviewDiff(path)`。

### Step 6：前端 adapter `desktop/src/renderer/src/lionRuntime.ts` / `assistantRuntime.tsx`

- `LionAssistantRuntimeAdapter.fetchGitReview()` / `fetchGitReviewDiff(path)` 透传，沿用 `metadataError` 风格。

### Step 7：前端 WorkPanel `desktop/src/renderer/src/components/WorkPanel.tsx` + 样式

- 视图类型加 `"Git"`；`GitReviewTab` 组件：
  - 挂载 + 刷新按钮 → `adapter.fetchGitReview()`；请求序号丢弃陈旧返回。
  - 状态：loading / non_git / unborn / git_failed / clean / dirty(truncated)。
  - 文件列表：状态徽标 + `+adds/-dels`；点击展开 `fetchGitReviewDiff`，复用 `.diff-result` 高亮；binary 显示「二进制文件」。
- `shell.css` 增加 `.git-review-*` 少量样式。

### Step 8：前端测试 `desktop/tests/renderer/gitReview.test.tsx`

- mock fetch：快照渲染文件列表/clean/non_git；展开渲染 diff；快速刷新丢弃陈旧返回；非法 schema 拒绝。

### Step 9：验证门禁（targeted）

```bash
python -m pytest tests/server/test_git_review.py -q
cd desktop && npx vitest run tests/renderer/gitReview.test.tsx && npm run typecheck
```

架构 import-linter：仅新增 `application` → `core`（dataclass 无需额外 import）与 `server` → `application` 依赖，均在允许范围内；跑 `python -m pytest tests/architecture -q` 确认。

## 验收对照（prd.md）

全部 Acceptance Criteria 逐条核对通过后进入 finish。

## 回滚点

- Step 1-3 完成 + Step 4 通过后可独立提交后端；Step 5-8 前端独立提交。任一步骤失败只回退对应提交，不影响既有端点。

## 交付

- 单 PR 覆盖整个功能（后端 + 前端 + 测试），或按行为边界拆两个 PR（后端端口、前端投影）——视改动规模在提交前决定，保持一个独立可回滚 PR。
