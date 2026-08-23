# Implementation Plan（handoff UX 已确认：显式 handoff_session，2026-08-23 批准启动）

计划已批准。按 child task 逐个实施：

本范围包含四个可独立回滚的职责，不能放进一个超过项目阈值的大 PR。最终批准后应把本任务作为 parent，创建对应 child task，并在每个 child artifact 中写明以下依赖。

## PR1 — 修复默认 Full 项目指令加载

类型：`fix`

依赖：无。

职责：让已有 AGENTS/CLAUDE loader 真正进入默认 Full product system prompt，先修复“规则根本没被看见”的根因。

- [ ] 为 root-to-cwd AGENTS/CLAUDE 顺序、空文件、重复加载和 custom prompt 现有语义增加测试。
- [ ] 在 Full dynamic prompt 构造中复用现有 `load_project_context_files` / `load_claude_md`，不增加第二个 loader/cache。
- [ ] 不读取 Trellis/Skill，不写回项目文件，不引入 Memory 依赖。
- [ ] 同步 prompt/composition spec 和测试。

回滚：回退接线，无持久数据变化。

## PR2 — 新增 Session handoff

类型：`feature`

依赖：无；复用当前已存在的 Compaction/Session 合约。

职责：把未完成任务以九段有界摘要带入新 Session，保留旧 Session 完整历史。

- [ ] 根据用户最终 UX 决策定义 application/facade/SessionPort 的 handoff 操作；普通 new/clear 语义必须明确。
- [ ] 复用 `ContextCompactor` 与固定 `SUMMARY_HEADINGS`，不得发明第二套 handoff prompt。
- [ ] 给 `SessionRecorder` 增加窄 `record_branch_summary` 路径，并用 `BranchSummaryEntry` 作为 canonical 新 Session 首段上下文。
- [ ] handoff 失败时不得清空旧 Session 或留下半初始化新 Session；确定创建/切换顺序和失败回滚。
- [ ] TUI/server 只增加必要入口和清晰通知，不增加独立 Task store。
- [ ] 测试摘要内容、source branch root、旧历史保留、新上下文有界、restore/handoff chain 和失败原子性。

回滚：删除 handoff 入口与 writer；旧 Session 和已存在 BranchSummaryEntry 仍可 replay。

## PR3 — SQLite Semantic Memory Store 与治理工具

类型：`feature`

依赖：无；先通过 `extension_specs` 测试闭环，不默认启用自动召回。

职责：完成四象限、FTS5、revision 生命周期和显式管理工具。

- [ ] 在 `lion_code/capabilities/memory/` 实现 `MemoryStore`、严格 schema 初始化、integrity/version fail-closed 和 transaction boundary；不建立单实现 Protocol。
- [ ] 建立 `memory_entries`、`memory_fts`、`memory_meta`，添加 scope/kind/status/recall_mode CHECK、project_key 约束和 active stable-key 唯一性。
- [ ] 实现 revision supersede、active/stale/archived、path validation、stale candidate review、mark-stale/archive/restore/validate/purge。
- [ ] 实现 FTS5 BM25 + exact key/path boost、scope/status filter、最低门槛、stable tie-break 和预算裁剪。
- [ ] 实现 `recall_memory`、`remember_definition`、`remember_behavior`、`review_memory`、`manage_memory`；mutation 标记 confirmation。
- [ ] DB 使用 `~/.lion-code/memory.sqlite3`、WAL、foreign key、busy timeout；不引入第三方依赖。
- [ ] 测试四象限隔离、schema 约束、corrupt/version mismatch、FTS index 一致性、revision chain、stale、archive/restore/purge、并发读写与 ToolRuntime metadata。

回滚：取消/回退 Capability tools，保留数据库作为可恢复用户数据。

## PR4 — Query-aware 自动召回与 FullProfile 集成

类型：`feature`

依赖：PR3 已合并；PR1 建议先合并以建立清晰权威优先级，但不是代码依赖。

职责：让 pinned 和 relevant memory 在 prepared context 中可靠、低噪声地出现，而不依赖模型主动工具调用。

- [ ] 增加窄 `QueryContextLayer` SPI，输入最新 user query + immutable ContextView，输出 prepared-only text。
- [ ] CapabilityRegistry/ContextManager 只聚合和渲染该层；不向 Session/Runtime 暴露 MemoryStore，不恢复旧 TurnParticipant/ProjectionLayer。
- [ ] Memory layer 渲染 long-term + current-project active pinned，并按 latest user query 召回 relevant；保持纯读取且不增加缓存失效协议。
- [ ] 固定 pinned 400-token、relevant 800-token、top 6 等预算常量，并测试空结果不注入。
- [ ] FullProfile 默认选择新 Memory Capability；Coding/Minimal 和 caller `extension_specs` 契约保持。
- [ ] 添加 prompt ordering、权威性说明、每 user turn 刷新、tool-loop 稳定、restore/new/handoff 交互和架构不可达测试。
- [ ] 扩展 legacy-removal gate：允许新 capability-owned store/query layer，继续禁止旧模块与符号。

回滚：取消 QueryContextLayer 注册/FullProfile 选择；手动 Memory tools 与数据库仍可用。

## 可选后续：硬行为门控（不属于本任务）

若用户要求 CI 规则从“高显著性提醒”升级为“技术上禁止违规”，单独设计 Hook/Permission/workflow gate PR。不得把自然语言 behavior memory 直接变成 shell 拦截规则。

## Focused verification

实际 child task 按所属 PR 细化，至少覆盖：

```powershell
$env:GIT_CEILING_DIRECTORIES = 'C:\Users\暮羽中'
python -m pytest -q tests/test_prompt.py
python -m pytest -q tests/context/test_compaction.py tests/session_runtime/test_recorder.py tests/session_runtime/test_repository.py
python -m pytest -q tests/capabilities/test_memory_store.py tests/capabilities/test_memory_capability.py
python -m pytest -q tests/context/test_query_context_layer.py
python -m pytest -q tests/architecture/test_composition_profiles.py tests/architecture/test_legacy_memory_removal.py
python -m compileall -q lion_code tests
git diff --check
```

SQLite 环境门禁：

```powershell
python -c "import sqlite3; c=sqlite3.connect(':memory:'); c.execute('create virtual table x using fts5(v)'); print(sqlite3.sqlite_version)"
```

## Full quality gate before each push

- [ ] 运行该 PR 定向测试、全量测试和 `.github/workflows/ci.yml` 中 Ruff/format/mypy/Radon/Vulture/coverage/import-linter/architecture 基线门禁。
- [ ] 运行 `python ./.trellis/scripts/task.py validate <child-task-dir>`。
- [ ] `git diff --stat` 只包含 child task 的真实改动，无行尾污染或无关文件。
- [ ] PR 描述列出状态所有权、不变量、测试矩阵、行数/依赖变化和回滚点。
- [ ] 标明 PR 类型，推送后等待 CI；失败则修复并重新等待，CI 通过后才合并。

## Parent 收口验证

- [ ] 从真实 AGENTS 规则启动 Full，确认 system prompt 含项目指令。
- [ ] 建立四象限样例、pinned PR 行为和互不相关 path 记忆，验证自动召回与防串扰。
- [ ] 执行一段有修改/测试/失败记录的任务，handoff 到新 Session，确认无需手工复述即可继续。
- [ ] 制造 path stale、revision correction、archive/restore/purge，验证 review 与自动召回排除。
- [ ] 确认 Session/Compaction/Checkpoint/Plan ownership 与旧 Memory 移除门禁保持。
