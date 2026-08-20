# PR5 执行计划

实施前提：已确认本地 PR4 基线 `01b1555`；不 checkout 到旧的
`origin/master`。保留 `.ci-venv/`、`.pi/`、`.tmp-ci/`、`.zcode/`、`after1.tmp`
等无关未跟踪项。每个独立改动完成后运行最小验证并以中文描述提交。

## Step 1 — Provider read projection（单一 Runtime 改动）

1. 在 `lion_code/runtime/provider.py` 增加独立
   `ProviderConfigurationProjection`，复用 `ProviderState` 引用，暴露
   `api_configured` 和 child API read projection；不引用 Controller。
2. 给 `ProviderController` 注入 projection，并在 target state 成功提交后同步
   projection；保留 `_state` 为唯一 writable ProviderState owner。
3. 删除 `ProviderController.child_api_kwargs()` 的 builder 依赖（若无其他消费
   则删除旧方法），更新 runtime docstring/typing。

验证：`python -m py_compile lion_code/runtime/provider.py`；ProviderController
focused tests、provider switching/thinking tests。

提交：`refactor(runtime): 解耦 Provider 配置只读投影`。

## Step 2 — Composition Root 拓扑接线

1. 在 `build_agent_composition()` 中于 identity/capability graph 前构造
   projection。
2. 将 `RuntimeIdentityPort` 的 API read 与 SubagentFactory child config 改为
   projection-bound callable/partial；删除未来 `provider_controller` 声明及两处
   closure。
3. 保留 Conversation/Context/Session/AgentRuntime/ProviderController 的既有
   构造顺序与窄端口，不改 Profile/Capability 语义。

验证：三 Profile composition、FullProfile child execution、session restore、
provider switching、thinking switching、`python -m compileall -q lion_code`。

提交：`refactor(composition): 消除 Provider late-bound closure`。

## Step 3 — Reachable-object-graph architecture gate

1. 在 `tests/architecture/test_runtime_ownership.py` 增加受限 traversal、路径
   报告和 visited set。
2. 分别构造 Minimal/Coding/Full 图，断言 AgentRuntime、SessionRuntime、
   CapabilityRuntime、SubagentFactory 到达不到 ProviderController。
3. 增加 closure cell/partial/bound method 覆盖及 builder AST static gate。
4. 保留既有 shallow ownership/deferred/class/import gates，不以新 helper 替代。

验证：

```powershell
$env:PYTHONPATH = "tests"
python -m pytest -q -p no:cacheprovider tests/architecture/test_runtime_ownership.py tests/architecture/test_composition_profiles.py tests/architecture/test_bare_composition.py tests/architecture/test_composition_root.py tests/architecture/test_provider_manager_boundaries.py
```

提交：`test(architecture): 增加 Runtime reachable DAG 门禁`。

## Step 4 — Product Composition Root relocation

1. 新建 `lion_code/composition/full_product.py`，移动 Full factory 与默认
   provider/dynamic-context/renderer bindings。
2. `adapters/coding_session_backend.py` 只保留 Adapter class 与产品委托依赖，
   删除 factory 和兼容导出。
3. 更新 `lion_code/__main__.py`、应用/benchmark/集成/架构测试 imports 与
   factory patch seam；不改 Adapter public behavior。
4. 增加/更新 architecture test：factory 只位于 composition bootstrap，Adapter
   不导出 factory、不调用 `build_agent_composition`。

验证：Product Adapter、CLI help、Application/TUI、FullProfile composition、
SubAgent/Skill child execution 和 import-linter focused checks。

提交：`refactor(composition): 迁移 Full product bootstrap`。

## Step 5 — Spec 与精确 residual gates

1. 更新 `.trellis/spec/backend/four-layer-ownership.md`、
   `runtime-boundaries.md`、`directory-structure.md`，只记录当前事实。
2. 增加或同步精确 residual scan：用户给出的旧 symbols/path、
   `lambda ... provider_controller`、builder closure cell → ProviderController。
3. `git diff --check`、AST/compile 预检；只更新质量基线中因真实行号漂移而需要
   更新的 fingerprint，不修无关 baseline。

提交：`docs(spec): 同步 PR5 Runtime DAG 与 Composition 边界`。

## Step 6 — Full verification and handoff

按仓库 CI 与用户矩阵运行 runtime ownership、FullProfile composition、SubAgent/
Skill child execution、provider/thinking switching、session restore、context
compaction、Product Adapter、Application、Supervisor、full pytest，以及
compileall、ruff、format、mypy baseline、import-linter、radon、vulture、coverage
和 quality baseline。分离 scoped regressions 与原有 dirty/baseline noise。

最后执行一次精确 residual scan，读取全部相关 spec 和 diff，形成 PR5 最终报告；
check 阶段才允许调用 `trellis-check` subagent，实施阶段不调用 subagent。
