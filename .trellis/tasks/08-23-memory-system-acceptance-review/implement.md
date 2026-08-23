# Acceptance Review Plan（已完成）

用户批准后已启动并完成；执行阶段只读产品代码，结果见 `research/acceptance-report.md`。

## 1. 锁定证据

- [x] fetch/recheck `origin/master`，记录审查 SHA 与 PR #89–#94 的 tree 范围。
- [x] 记录审查前 `git status`，确认五个 Electron/Trellis 未跟踪目录不属于本任务。
- [x] 从 commit `6c9fddd` 提取最终 R1–R9 和 Acceptance Criteria。
- [x] 读取归档 parent 与 PR1–PR4 artifacts，记录其与最终方案的已知分叉点。

## 2. 建立 contract matrix

- [x] 对 Task Ledger、semantic schema、write policy、review、pinned、explicit recall、storage identity、ownership、lexical prototype 逐项标记状态。
- [x] 对 PR1 AGENTS loader、PR2 Session handoff、PR3 FTS/revision/stale、PR4 relevant auto-recall 标记 `required / deferred / out-of-scope-added`。
- [x] 每项附 current source/test anchor；缺少实现时用全仓符号搜索证明 absence。

## 3. 追踪当前实现

- [x] Store：schema bootstrap、triggers/FTS、transactions、remember/revision、manage/review/search/pinned。
- [x] Capability：工具 schema、ToolCapabilities、错误映射、项目路径与 evidence 校验。
- [x] Recall：query 提取、清洗/转义、scope/status/path filter、排序/阈值/budget、prepared-only 写入位置。
- [x] Composition：FullProfile 默认构造、DB path/project key、resource lifecycle、Coding/Minimal 不变量。
- [x] Session/Prompt：handoff 与 AGENTS loader 的跨层调用和回滚行为，并判断它们是否属于最终 Memory 范围。
- [x] Architecture：legacy-removal、Runtime/Session store 不可达、Context transientness。

## 4. 定向验证

优先运行：

```powershell
$env:GIT_CEILING_DIRECTORIES = 'C:\Users\暮羽中'
python -m pytest -q tests/capabilities/test_memory_store.py tests/capabilities/test_memory_capability.py
python -m pytest -q tests/capabilities/test_memory_query_layer.py tests/context/test_query_context_layer.py
python -m pytest -q tests/architecture/test_memory_auto_recall.py tests/architecture/test_legacy_memory_removal.py tests/architecture/test_composition_profiles.py
python -m pytest -q tests/integration/test_session_handoff.py tests/test_prompt.py
```

- [x] 对疑似 confirmation bypass、restore conflict、stale/path、两字中文 query、special-token query 和 tool-loop query 构造最小复现。
- [x] 所有 DB 实验使用 `TemporaryDirectory`；不得打开默认用户 Memory DB。
- [x] 若现有定向测试全部通过但 finding 仍成立，说明测试为何只证明旧 contract 或遗漏负向场景。

## 5. 输出报告

- [x] 写 `research/acceptance-report.md`：findings、contract matrix、commands/results、residual risks。
- [x] 重新读取每条 P0–P2 的当前 file:line，删除未证实或重复 finding。
- [x] 报告明确区分缺失、bug、架构违规、scope drift/过度设计和测试缺口。
- [x] 最终 `git status` 与审查前对比，确认没有产品代码变化。

## Stop conditions

- 发现测试失败不会自动授权修复；只记录并继续审查其他独立维度。
- 发现真实用户数据库需要迁移、清除或打开时停止该实验，改用临时构造。
- master 在审查期间变化时重新锁定 SHA；不混合两个版本的行号和结论。
- 不运行 `trellis-check` 全套、不更新 spec、不创建修复 child task，除非用户在收到报告后另行授权。
