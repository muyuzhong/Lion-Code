# Implementation Plan

本计划尚未启动。只有用户批准修订后的设计，并由 `task.py start` 将任务切换为 `in_progress` 后才能执行。

## 单一实施切片 — Memory Capability 最小端到端闭环

职责：实现一套 Memory 能力，以同一 repository、同一组工具支持 `长期/项目 × 定义/行为` 四个语义象限。不包含 AGENTS 加载、Skill 管理或 Trellis 集成。

### 1. 私有数据模型与双作用域存储

- [ ] 在 `lion_code/capabilities/memory/` 内实现 definition、behavior 和严格文档模型，不建立只有一个实现的 Protocol。
- [ ] 实现一个 `MemoryRepository`，同时管理用户级 `long-term.json` 与 `project_storage_dir(identity) / "memory.json"`。
- [ ] 实现缺失文件为空、严格读取、内容边界、唯一 key、项目相对 path 校验和长期 scope 禁止 path。
- [ ] 实现 exact-key upsert、物理 delete、临时文件 + flush/fsync + `os.replace` 的原子替换。
- [ ] 损坏文件必须阻止 mutation 覆盖；不实现迁移、兼容读取、备份链或 fallback。

### 2. 四个模型工具和 PromptLayer

- [ ] 实现 `recall_memory(query, paths=())`，按四象限分组返回有界、稳定、可解释的确定性结果。
- [ ] 实现 `remember_definition(scope, key, statement, evidence, paths=())`。
- [ ] 实现 `remember_behavior(scope, key, trigger, instruction, evidence, paths=())`。
- [ ] 实现 `forget_memory(scope, kind, key)`。
- [ ] 标记 recall 为只读/可并发；标记三个 mutation 工具 `requires_confirmation=True`。
- [ ] PromptLayer 只规定召回时机、trigger 检查和当前证据优先，不注入 Memory 内容。
- [ ] 所有操作只走现有 `ToolRuntime.execute`，不增加 hook、wrapper、后台任务或第二模型请求。

### 3. FullProfile 集成与架构边界

- [ ] 从现有 cwd 解析一次 `ProjectIdentity`，构造 Capability-private repository，并让 FullProfile 默认选择新 Capability。
- [ ] CodingProfile、MinimalProfile 及 `extension_specs` 现有契约保持不变。
- [ ] 不给 Agent Runtime、MetaAgent、Application、TUI、Session、ContextRuntime 或 PlanRuntime 增加 memory 字段、端口或 delegate。
- [ ] 不恢复 `_CAP_MEMORY` 或任何 legacy Memory / Dream / Learning 符号。
- [ ] 同步受影响的 active backend spec 和 architecture test 期望；文档明确 Trellis、Skill、AGENTS 不属于 Memory。

### 4. 测试矩阵

- [ ] 四象限各自能新增、精确替换、召回和删除，两个 scope 使用不同文件且互不污染。
- [ ] 定义与行为契约互斥清晰；同 kind 重复 key 被拒绝；不同 kind 可使用相同 key。
- [ ] 长期 path、项目 path 越界、未知字段、空 evidence、超长字段、非法 UTF-8、畸形 JSON 均失败且不覆盖原文件。
- [ ] 任一 scope 文件缺失时正常为空；一个 scope 损坏时另一个文件不被改写。
- [ ] 检索的 exact key/path、词命中、tie-break、空查询、无命中、条目上限和字符预算确定稳定。
- [ ] mutation 的 confirmation metadata 与 recall 的只读/concurrency metadata 正确。
- [ ] Full 包含新能力，Coding/Minimal 不变；Runtime 不可达 repository owner；Session/Compaction/Checkpoint schema 不变。
- [ ] `test_legacy_memory_removal.py` 继续通过，禁止旧对象图回归。

## 预期变更边界

实现应尽量限制在：

- `lion_code/capabilities/memory/` 新包；
- Full composition 的最小注册点；
- 对应 capability / composition / architecture 测试；
- 被真实行为改变触发的 `.trellis/spec/backend/` 文档。

不修改 AGENTS loader、Skill、Trellis runtime、Session entry、Compaction、Supervisor checkpoint、Plan 或 TUI。若实现需要突破这些边界，应停止并重新评审设计，而不是顺手扩张。

## Focused verification

```powershell
$env:GIT_CEILING_DIRECTORIES = 'C:\Users\暮羽中'
python -m pytest -q tests/capabilities/test_memory.py
python -m pytest -q tests/test_project_identity.py
python -m pytest -q tests/architecture/test_composition_profiles.py tests/architecture/test_legacy_memory_removal.py
python -m compileall -q lion_code tests
git diff --check
```

测试文件名以实现时项目实际布局为准，但验证范围不得省略双作用域、双 kind、原子写、确认边界和架构不可达性。

## Full quality gate before push

- [ ] 运行全量测试，并区分现有 Windows/baseline 噪声与本任务回归。
- [ ] 按 `.github/workflows/ci.yml` 运行 Ruff、format、mypy、Radon、Vulture、coverage、import-linter 和架构门禁，并与 `docs/quality-baseline-2026-08.json` 比对。
- [ ] 运行 `python ./.trellis/scripts/task.py validate .trellis/tasks/08-22-memory-system-design-convergence`。
- [ ] 确认 `git diff --stat` 只包含真实任务改动，无行尾污染和无关文件。
- [ ] 确认新增生产路径经过统一 ToolRuntime，reachable object graph 不破坏 Runtime/Plan/Session 边界。

## 提交、PR 与回滚

- 使用一个职责单一的 PR：新增 Memory Capability 的最小端到端闭环。
- 每个完成的代码改动按项目规则用中文描述提交，只暂存任务拥有的路径。
- PR 描述记录状态所有权、保持不变的不变量、测试矩阵、行数/依赖变化和回滚点。
- 回滚点是取消注册并回退 Capability 代码；保留两份 JSON 作为可恢复用户数据，除非用户另行授权删除。
- 如果预估超过 20 个文件或出现第二个独立职责，先重新拆分并请求评审，不把 AGENTS/Skill/Trellis 改动混入本 PR。
