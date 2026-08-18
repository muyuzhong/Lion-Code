# Agent Note: 裁剪 Capability 扩展契约的未使用槽位（requires 依赖解析与 per-turn 挂钩）

- Status: proposed
- 日期: 2026-08-18
- 范围: `lion_code/capabilities/`、`lion_code/agent_runtime.py`、`lion_code/session_lifecycle.py`、`tests/capabilities/`、`tests/test_agent_run.py`、`tests/architecture/test_runtime_boundaries.py`、`.trellis/spec/backend/capability-spi.md`

## Problem

`CapabilitySpec` 暴露两类扩展槽位，但任何投产的 Capability 都没有使用它们：

1. **`requires` 依赖解析**（`capabilities/types.py:121`；`capabilities/registry.py:53-113` 的
   Kahn 稳定拓扑排序 + `MissingDependencyError`/`CircularDependencyError`）：
   三个内置 Capability（plan/skill/subagent，见 `composition/agent_builder.py:566-570`）
   全部不传 `requires`；`rg "requires=" lion_code` 在生产目录零命中。
   所有使用 `requires` 的地方都在测试里（`tests/capabilities/test_capability_registry.py`
   的 :222/:234/:237/:247/:256/:268/:276/:283-285/:310/:313/:422/:467/:564/:571/:600，
   `tests/capabilities/test_capability_runtime.py:73,120`）。由于没有任何依赖，
   每次属性访问触发的解析结果恒等于注册顺序——排序是空转。
2. **`TurnParticipant` per-turn 挂钩**（`capabilities/types.py:55-66`、registry 的
   `turn_participants` 槽 :210-217、`capabilities/runtime.py:31-37` 的
   `before_turn/after_turn` 分发）：生产代码零实现；`agent_runtime.py:730-737`
   在每轮热路径上对空元组做两次空迭代。Plan 用 `session_participants`（
   `capabilities/plan.py:67-77`），但没有任何 Capability 实现 `TurnParticipant`
   ——只有测试里的 fake（`tests/test_agent_run.py:249-259`、
   `tests/capabilities/test_capability_registry.py:66-73`、
   `tests/capabilities/test_capability_migration.py:25-29`）和架构测试的字段断言
   （`tests/architecture/test_runtime_boundaries.py:1470` 的 `_before_turn_capabilities`）。

附带发现：
- `CapabilityRegistry.resolve()`（`registry.py:155-166`）与私有
  `_ensure_resolved()`（:168-172）是同一份逻辑的两份拷贝，而生产代码只走属性路径
  （`tool_sources`/`prompt_layers`/`session_participants`/`resources` 内部调
  `_ensure_resolved`）；`resolve()` 无任何生产调用者，只为测试存在。
- 查询面 `get`（:181-183）、`__len__`（:185-186）、`__contains__`（:188-189）、
  `names`（:176-179）同样零生产引用，只有 `tests/capabilities/test_capability_registry.py`
  在使用；`CapabilityError` 基类（:32-34）从不被 import、raise 或 catch，也未导出到
  `capabilities/__init__.py` 的 `__all__`——三个子类各有用途，基类没有。

说明：`resources`/`close_all`（`registry.py:229-259`）保留——它是 `extension_specs`
公共扩展契约的一部分（`capability-spi.md` 明文承诺 closeable resources），且
`capabilities/runtime.py:51` 有生产调用点。`session_participants` 保留（Plan 在用）。

## Proposal

1. 删除 `requires` 字段与整条依赖解析链路：`_topological_sort`、
   `MissingDependencyError`、`CircularDependencyError`、cache 失效逻辑
   （`register` 置 `_order=None`）；四个聚合属性改为按注册顺序直接迭代
   `self._specs.values()`；`close_all` 按注册顺序的逆序关闭。保留
   `DuplicateCapabilityError`。
2. 合并 `resolve()` 与 `_ensure_resolved()` 为单一方法（保留 `resolve()` 名称或私有名，
   只留一份）；测试改经 `tool_sources` 等属性断言顺序，或直接删除顺序断言。
3. 删除 `CapabilityError` 基类、`get`、`__len__`、`__contains__`、`names`——注册
   唯一性（`DuplicateCapabilityError`）与槽位聚合属性保留，这是 `capability-spi.md`
   实际承诺的契约；顺序断言测试改为注册带序的 fake `ToolSource` 后经 `tool_sources`
   断言。
4. 删除 `TurnParticipant` 协议、`CapabilitySpec.turn_participants` 槽、
   `CapabilityRuntime.before_turn/after_turn`、`CapabilityLifecycle` 中对应方法、
   `agent_runtime.py:730-737` 的热路径分发调用；同步删除测试里的 fake 与
   `tests/architecture/test_runtime_boundaries.py` 的 `_before_turn_capabilities` 断言。
5. 同步契约文档：`capability-spi.md` 的 Public slots 删除 `TurnParticipant` 与
   `requires` 字段、Invariant 3（"Missing and circular dependencies fail"）、
   第 39-42 行 "resolves explicit dependencies ... in dependency order" 表述、
   `CapabilityRuntime` 分发描述（:44-46 只保留 session/close）；
   `runtime-boundaries.md` 与 `four-layer-ownership.md` 若提及 per-turn 能力分发也一并修正。
6. 测试：删除 `test_capability_registry.py` 中依赖排序/成环/缺依赖用例与
   `_FakeTurnParticipant`，保留唯一性、聚合、生命周期用例；删除
   `test_agent_run.py` 的 `SlowTurnParticipant` 用例、`test_capability_runtime.py` 的
   对应参与者用例与 `test_capability_migration.py` 的 `_RecordingTurnParticipant`。

## Why not keep it

最强的反方论证来自 `capability-spi.md` 本身：它把这两个槽位明文写进公共扩展契约，
并说 "Future capabilities may add the existing generic slots"——即它们是为未来
Capability 预留的。但按 `AGENTS.md` 原则 2（选能满足当前需求的最简单实现，不预防性抽象）
与原则 1（不保留兼容层），一个没有任何投产使用者的热路径分发与一套空转的排序器，
正是"未完成的复杂度"；registry 只有 ~260 行，未来某个真实 Capability 需要依赖序或
per-turn 挂钩时按需加回的成本很低，且届时会有真实用例来验证设计（今日的测试 fake
无法证明设计正确）。per-turn 挂钩尤其可疑——它把 on-turn 扩展点放进每轮热路径，
与鹰架上一个无人消费的"中途转向"能力同类。

## Acceptance criteria

- `rg -n "requires=|TurnParticipant|before_turn|after_turn" lion_code` 在生产目录零命中
  （`after_turn` 需确认 `context/` 或 tooling 无同名符号被误伤）。
- 全量可跑 unittest 通过；架构测试期望值同步后通过（修字段断言、删除的能力槽位无残留）。
- 改 `capability-spi.md`/`runtime-boundaries.md`/`four-layer-ownership.md` 后跑
  `lint-imports` 与 CI 门禁；`git diff --stat` 只含真实改动。
- `FullProfile` 带 `extension_specs` 的图仍可构造、Plan/Skill/SubAgent 行为不变
  （集成测试 `test_composition_profiles.py`/`test_meta_agent.py` 保持绿）。

## Risks

- 对第三方 `extension_specs` 作者是公共 API 缩减：`requires` 与 `TurnParticipant`
  一旦发布过就被视为契约。当前仓库无外部消费者证据（个人项目、未发布），
  且 `AGENTS.md` 明示不做向后兼容，风险可接受。
- `resolve()` 删除后测试断言顺序的写法会变（改经聚合属性），属于测试重写而非行为变化。
- 未来 Capability 若真的需要依赖序，需重建排序器——成本与今天删除它对称。