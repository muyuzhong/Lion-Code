# Agent Note: 移除 Profile 层无生产消费者的 permission_strategy 旋钮

- Status: proposed
- 日期: 2026-08-18
- 范围: `lion_code/composition/profiles.py`、`lion_code/composition/agent_builder.py`、`tests/architecture/test_composition_profiles.py`

## Problem

三个 Profile（`MinimalProfile`/`CodingProfile`/`FullProfile`）都带
`permission_strategy: ToolPermissionStrategy | None = None` 字段
（`profiles.py:40,57,78`），经 `_ProfileSelection`（`agent_builder.py:148`）与
`_normalize_profile`（:325/:338/:353）透传，在 builder 里作为唯一消费点
（:631）`selection.permission_strategy or PermissionPolicy(cwd=foundation.cwd)`。
但所有生产构造路径都不设置它：`Agent` 的 FullProfile（`agent.py:193-197`）、
`build_coding_agent`/`build_coding_agent` child 图（`meta_agent.py:286-306`）、
`build_meta_agent`（`meta_agent.py:238`）、子 Agent 图（`subagent_factory.py:82-91`
只传 model/key/base/system/permission_mode/tool_registry）——全部吃默认值 `None`。
只有 `tests/architecture/test_composition_profiles.py:164,233` 传过非默认策略。

## Proposal

1. 从三个 Profile、`_ProfileSelection`、`_normalize_profile` 删除
   `permission_strategy`；builder :631 改为无条件
   `PermissionPolicy(cwd=foundation.cwd)`。
2. 更新 `tests/architecture/test_composition_profiles.py:156-179,229-252` 的两个断言
   （改为断言默认策略即可），删除 :539-545 的注入路径（若有）。
3. `ToolPermissionStrategy` 协议本身保留（`tooling/permission.py:46`，
   `PermissionMiddleware` 在用，`tooling/middleware.py:108`）——只删 Profile 层的
   注入旋钮，不删类型。

## Why not keep it

最自然的辩护是「Coding Harness policy」这一措辞（`runtime-boundaries.md`）暗示
Profile 应能注入安全策略，且这是 embedder 唯一的安全注入缝。但没有任何 API 表面
暴露它（`Agent`/`build_coding_agent` 都不接受该参数），即使用未来的 embedder 也
无法触达；要注入策略只需给 builder 加一个参数，成本 3 行。按「不预防性抽象、
绝不为未完成的复杂度保留配置层」，等真实消费方出现再恢复。

## Acceptance criteria

- `rg -n "permission_strategy" lion_code tests` 零命中。
- `tests/architecture/test_composition_profiles.py` 全绿（断言改为默认策略）；
  权限路径无行为变化（`PermissionPolicy(cwd=...)` 与今天 `None` 分支的结果相同）。
- 全量可跑 unittest 通过；`git diff --check` 干净。

## Risks

- 术语「permission strategy」与 `PermissionMiddleware` 的 `policy` 概念相近，
  删除后读代码者仍能从 `PermissionPolicy` 看到默认策略，不损失可解释性。