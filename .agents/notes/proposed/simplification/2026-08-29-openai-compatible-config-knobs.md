# Agent Note: 删除 OpenAI-compatible 适配器死配置旋钮（reasoning_effort_parameter/thinking_format/compat/include_reasoning_effort_none）

- Status: proposed
- 日期: 2026-08-29
- 范围: `lion_code/providers/config.py`、`lion_code/providers/openai_compatible.py`、`tests/providers/test_openai_compatible.py`

## Problem

`OpenAICompatibleConfig` 上四个配置旋钮没有任何生产者会设置它们，对应代码分支按构造不可达：

1. `reasoning_effort_parameter`（`config.py:30`）、`thinking_format`（:31）、`compat`（:32）、`include_reasoning_effort_none`（:33）。
2. 生产唯一构造点 `providers/factory.py:43-49` 只传 `api_key`/`base_url`/`provider_name`/`max_tokens`/thinking kwargs，四个旋钮恒为默认值；`rg "reasoning_effort_parameter=|thinking_format=|compat=|include_reasoning_effort_none="` 全仓（生产+测试）零命中。
3. `openai_compatible.py:99-103` 把四旋钮透传给请求构造（:318-322 默认、:353-355 使用），对应分支（reasoning 参数名选择、compat 键注入、`include_reasoning_effort_none`）生产恒走默认路径。

## Proposal

1. 删除 `config.py:30-33` 四个字段。
2. `openai_compatible.py`：删除四旋钮的透传与分支，内联默认行为（`reasoning_effort_parameter="reasoning_effort"`、`thinking_format="openai"`、不注入 compat 键、不传 `reasoning_effort=None`）。
3. 核对并清理 `tests/providers/test_openai_compatible.py` 中对这些旋钮的构造依赖（若有）。

## Why not keep it

这是 `provider-layer-migration-residue`（PR #54，已删同类认证/thinking 旋钮）同域的新残留：OAI-compatible 双适配器是受保护设计，但「写而无人读的配置旋钮」不属于保护面。按「不保留向后兼容 + 没有调用者就不存在」，删除后 Config 更接近真实契约。

## Acceptance criteria

- `rg -n "reasoning_effort_parameter|thinking_format|include_reasoning_effort_none|\.compat\b" lion_code/` 零命中。
- `tests/providers/test_openai_compatible.py`、`test_factory.py` 全绿；线上行为（默认路径）不变。

## Risks

- 若未来某个第三方 OAI-compatible 端点需要自定义 reasoning 参数名或 compat 键，需要重新加旋钮——当前零消费方（连测试都不钉非默认值），风险可接受。