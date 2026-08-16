"""Lion Code 上下文管理可复现基准。

默认只运行离线探针；传入 --online 后才会调用 OpenAI 兼容 API。
API Key 只从环境变量读取，绝不写入结果文件。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import statistics
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lion_code.context import (  # noqa: E402
    ContextManager,
    ContextPolicy,
    ContextRuntimeState,
    PreparedContext,
    fallback_context_window,
)
from lion_code.core import (  # noqa: E402
    AgentMessage,
    AssistantMessage,
    TextContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
    message_text,
)
from lion_code.tooling.builtin import create_builtin_tools  # noqa: E402
from lion_code.tooling.execution import LocalCommandExecutionBackend  # noqa: E402
from lion_code.tooling.internal import create_internal_tools  # noqa: E402
from lion_code.tooling.result_store import ResultStore  # noqa: E402
from lion_code.tooling.types import ToolResult  # noqa: E402


HERE = Path(__file__).resolve().parent
DATASET_PATH = HERE / "dataset.json"
RESULTS_DIR = HERE / "results"
REPORT_PATH = HERE / "REPORT_CN.md"
DEFAULT_CONTEXT_POLICY = ContextPolicy()
MICROCOMPACT_IDLE_S = DEFAULT_CONTEXT_POLICY.cache_idle_seconds
SNIP_PLACEHOLDER = DEFAULT_CONTEXT_POLICY.snip_placeholder


@dataclass
class BenchmarkContext:
    """基准专用的 canonical Active Context，不构造 Agent。"""

    system_prompt: str
    effective_window: int
    messages: list[AgentMessage]
    manager: ContextManager
    result_store: ResultStore
    tools_by_name: dict[str, Any]
    last_prompt_tokens: int = 0
    last_model_call_at: float | None = None

    @classmethod
    def create(
        cls,
        *,
        system_prompt: str,
        effective_window: int,
        result_root: Path | None = None,
    ) -> "BenchmarkContext":
        tools = [
            *create_builtin_tools(LocalCommandExecutionBackend()),
            *create_internal_tools(),
        ]
        tools_by_name = {tool.name: tool for tool in tools}

        def is_snippable(name: str) -> bool:
            tool = tools_by_name.get(name)
            return bool(
                tool is not None
                and tool.capabilities.result_policy == "snippable"
            )

        return cls(
            system_prompt=system_prompt,
            effective_window=effective_window,
            messages=[],
            manager=ContextManager(is_snippable_tool=is_snippable),
            result_store=ResultStore(root=result_root),
            tools_by_name=tools_by_name,
        )

    def runtime_state(self, *, eager_ablation: bool = False) -> ContextRuntimeState:
        return ContextRuntimeState(
            effective_window_tokens=self.effective_window,
            last_prompt_tokens=self.last_prompt_tokens,
            # eager 消融不声明缓存热度，因此触发 Snip、但不会触发冷缓存 Microcompact。
            last_model_call_at=(
                None if eager_ablation else self.last_model_call_at
            ),
            now=time.time(),
        )

    def prepare(self, variant: str) -> PreparedContext:
        if variant == "raw":
            projected = tuple(message.model_copy(deep=True) for message in self.messages)
            return PreparedContext(messages=projected)
        if variant not in {"managed", "eager_ablation"}:
            raise ValueError(f"未知变体：{variant}")
        return self.manager.prepare(
            self.messages,
            self.runtime_state(eager_ablation=variant == "eager_ablation"),
        )

    def openai_messages(
        self,
        messages: list[AgentMessage] | tuple[AgentMessage, ...] | None = None,
    ) -> list[dict[str, Any]]:
        return to_openai_messages(
            self.system_prompt,
            self.messages if messages is None else messages,
        )

    def openai_tools(self) -> list[dict[str, Any]]:
        return [
            tool.to_openai_schema()
            for tool in self.tools_by_name.values()
            if not tool.capabilities.deferred
        ]


@dataclass
class Price:
    cache_hit_input: float
    cache_miss_input: float
    output: float


@dataclass
class Budget:
    limit_cny: float
    price: Price
    spent_cny: float = 0.0

    def reserve_or_raise(self, estimated_prompt_chars: int, max_output_tokens: int) -> None:
        # 以 1.5 token/字符做非常保守的预检查；真正费用仍以 API usage 为准。
        worst_prompt_tokens = int(estimated_prompt_chars * 1.5)
        estimate = (
            worst_prompt_tokens / 1_000_000 * self.price.cache_miss_input
            + max_output_tokens / 1_000_000 * self.price.output
        )
        if self.spent_cny + estimate > self.limit_cny:
            raise RuntimeError(
                f"预算保护触发：已花费 {self.spent_cny:.4f} 元，"
                f"下一请求最坏估算 {estimate:.4f} 元，预算上限 {self.limit_cny:.2f} 元。"
            )

    def add_usage(self, usage: dict[str, int]) -> float:
        cost = usage_cost(usage, self.price)
        self.spent_cny += cost
        if self.spent_cny > self.limit_cny:
            raise RuntimeError(
                f"实际费用 {self.spent_cny:.4f} 元已超过预算 {self.limit_cny:.2f} 元，停止测试。"
            )
        return cost


@dataclass
class EventCounts:
    persisted_results: int = 0
    budget_rewrites: int = 0
    snipped_results: int = 0
    microcompacted_results: int = 0
    summaries: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "persisted_results": self.persisted_results,
            "budget_rewrites": self.budget_rewrites,
            "snipped_results": self.snipped_results,
            "microcompacted_results": self.microcompacted_results,
            "summaries": self.summaries,
        }


@dataclass
class ReplayResult:
    scenario_id: str
    scenario_name: str
    variant: str
    calls: list[dict[str, Any]] = field(default_factory=list)
    events: EventCounts = field(default_factory=EventCounts)
    retention: dict[str, Any] = field(default_factory=dict)

    def totals(self) -> dict[str, Any]:
        normal = [c for c in self.calls if c["kind"] != "summary"]
        all_usage = sum_usage(c["usage"] for c in self.calls)
        normal_usage = sum_usage(c["usage"] for c in normal)
        return {
            "all_calls": len(self.calls),
            "summary_calls": sum(1 for c in self.calls if c["kind"] == "summary"),
            "all_usage": all_usage,
            "normal_usage": normal_usage,
            "total_cost_cny": sum(c["cost_cny"] for c in self.calls),
            "peak_prompt_tokens": max((c["usage"]["prompt_tokens"] for c in normal), default=0),
            "over_effective_window_calls": sum(
                1 for c in normal if c["usage"]["prompt_tokens"] > c["effective_window_tokens"]
            ),
            "cache_hit_rate": ratio(all_usage["cache_hit_tokens"], all_usage["prompt_tokens"]),
            "retention_score": self.retention.get("score", 0.0),
            "retention_normalized_score": self.retention.get("normalized_score", 0.0),
            "retention_value_score": self.retention.get("value_score", 0.0),
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lion Code 上下文管理中文基准")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--online", action="store_true", help="运行真实 API 回放")
    mode.add_argument("--offline", action="store_true", help="只运行本地分层探针（默认）")
    mode.add_argument("--merge-results", nargs="+", metavar="JSON", help="合并互不重叠的分批结果，不调用 API")
    parser.add_argument("--base-url", default="https://api.deepseek.com")
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY")
    parser.add_argument("--budget-cny", type=float, default=7.8)
    parser.add_argument("--timeout-seconds", type=float, default=90.0)
    parser.add_argument("--only-scenario", action="append", default=[])
    return parser.parse_args()


def read_dataset() -> dict[str, Any]:
    return json.loads(DATASET_PATH.read_text(encoding="utf-8"))


def source_snapshot(paths: list[str]) -> tuple[str, list[dict[str, Any]]]:
    parts: list[str] = []
    metadata: list[dict[str, Any]] = []
    for rel in paths:
        path = ROOT / rel
        raw = path.read_bytes()
        text = raw.decode("utf-8", errors="replace")
        parts.append(f"\n\n===== {rel} =====\n{text}")
        metadata.append(
            {
                "path": rel,
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    return "".join(parts), metadata


def expand_to_bytes(seed: str, target_bytes: int, marker: str) -> str:
    if target_bytes <= 0:
        return ""
    unit = f"[{marker}]\n{seed}\n"
    unit_bytes = len(unit.encode("utf-8"))
    repeated = unit * (target_bytes // max(unit_bytes, 1) + 2)
    lo, hi = 0, len(repeated)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if len(repeated[:mid].encode("utf-8")) <= target_bytes:
            lo = mid
        else:
            hi = mid - 1
    return repeated[:lo]


def make_tool_messages(
    scenario: dict[str, Any],
    turn: int,
    payload: str,
) -> list[AgentMessage]:
    call_id = f"call_{scenario['id']}_{turn:02d}"
    source = scenario["source_files"][(turn - 1) % len(scenario["source_files"])]
    return [
        AssistantMessage(
            content=[
                ToolCall(
                    id=call_id,
                    name=scenario["tool_name"],
                    arguments={"file_path": source, "benchmark_turn": turn},
                )
            ],
            stop_reason="toolUse",
        ),
        ToolResultMessage(
            tool_call_id=call_id,
            tool_name=scenario["tool_name"],
            content=[TextContent(text=payload)],
        ),
    ]


def facts_for_turn(scenario: dict[str, Any], turn: int) -> str:
    rows = [f"{f['key']}={f['value']}" for f in scenario["facts"] if f["turn"] == turn]
    if not rows:
        return ""
    return "\n这些是后续验收必须精确保留的事实：\n" + "\n".join(rows)


def tool_content_stats(messages: list[AgentMessage]) -> dict[str, tuple[int, str]]:
    stats: dict[str, tuple[int, str]] = {}
    for index, message in enumerate(messages):
        if not isinstance(message, ToolResultMessage):
            continue
        content = message.text
        marker = "normal"
        if content == SNIP_PLACEHOLDER:
            marker = "snipped"
        elif content == "[Old result cleared]":
            marker = "microcompacted"
        elif "[... budgeted:" in content:
            marker = "budgeted"
        stats[f"{index}:{message.tool_call_id}"] = (len(content), marker)
    return stats


def apply_pipeline(context: BenchmarkContext, variant: str, events: EventCounts) -> None:
    if variant == "raw":
        return
    prepared = context.prepare(variant)
    context.messages = list(prepared.messages)
    for action in prepared.actions:
        if action.type == "budget_tool_result":
            events.budget_rewrites += 1
        elif action.type == "snip_tool_result":
            events.snipped_results += 1
        elif action.type == "clear_tool_result":
            events.microcompacted_results += 1


def process_tool_result(
    context: BenchmarkContext,
    tool_name: str,
    content: str,
) -> str:
    """让基准数据经过与运行时相同的结果策略。"""
    tool = context.tools_by_name.get(tool_name)
    if tool is None:
        return content
    return context.result_store.process(tool, ToolResult(content=content)).content


def to_openai_messages(
    system_prompt: str,
    messages: list[AgentMessage] | tuple[AgentMessage, ...],
) -> list[dict[str, Any]]:
    """只在 API 边界把 canonical messages 序列化为 OpenAI 格式。"""

    output: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt}
    ]
    for message in messages:
        if isinstance(message, UserMessage):
            output.append({"role": "user", "content": message.text})
            continue
        if isinstance(message, AssistantMessage):
            row: dict[str, Any] = {
                "role": "assistant",
                "content": message.text or None,
            }
            if message.tool_calls:
                row["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(
                                call.arguments,
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ),
                        },
                    }
                    for call in message.tool_calls
                ]
            output.append(row)
            continue
        if isinstance(message, ToolResultMessage):
            output.append(
                {
                    "role": "tool",
                    "tool_call_id": message.tool_call_id,
                    "content": message.text,
                }
            )
            continue
        output.append({"role": "user", "content": message_text(message)})
    return output


def usage_from_response(response: Any) -> dict[str, int]:
    dumped = response.usage.model_dump() if response.usage else {}
    prompt = int(dumped.get("prompt_tokens") or 0)
    completion = int(dumped.get("completion_tokens") or 0)
    details = dumped.get("prompt_tokens_details") or {}
    hit = dumped.get("prompt_cache_hit_tokens")
    if hit is None:
        hit = details.get("cached_tokens") or 0
    hit = min(max(int(hit or 0), 0), prompt)
    miss = dumped.get("prompt_cache_miss_tokens")
    if miss is None:
        miss = prompt - hit
    miss = max(int(miss or 0), 0)
    # 某些兼容端点的 hit+miss 可能因计量粒度略有偏差，优先保持总量一致。
    if hit + miss != prompt:
        miss = max(prompt - hit, 0)
    return {
        "prompt_tokens": prompt,
        "cache_hit_tokens": hit,
        "cache_miss_tokens": miss,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
    }


def create_benchmark_client(
    *,
    api_key: str,
    base_url: str,
    timeout: float,
    max_retries: int,
) -> Any:
    """仅为在线研究基准加载可选 SDK，基础安装和离线校验不依赖它。"""

    try:
        from openai import OpenAI
    except ImportError as error:
        raise SystemExit(
            '在线基准需要可选依赖，请先运行 python -m pip install -e ".[benchmark]"'
        ) from error
    return OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        max_retries=max_retries,
    )


def usage_cost(usage: dict[str, int], price: Price) -> float:
    return (
        usage["cache_hit_tokens"] / 1_000_000 * price.cache_hit_input
        + usage["cache_miss_tokens"] / 1_000_000 * price.cache_miss_input
        + usage["completion_tokens"] / 1_000_000 * price.output
    )


def sum_usage(usages: Any) -> dict[str, int]:
    keys = ("prompt_tokens", "cache_hit_tokens", "cache_miss_tokens", "completion_tokens", "total_tokens")
    total = {key: 0 for key in keys}
    for usage in usages:
        for key in keys:
            total[key] += int(usage.get(key, 0))
    return total


def ratio(numerator: int | float, denominator: int | float) -> float:
    return float(numerator) / float(denominator) if denominator else 0.0


def prompt_chars(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> int:
    return len(json.dumps({"messages": messages, "tools": tools or []}, ensure_ascii=False))


def api_call(
    client: Any,
    *,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    max_tokens: int,
    budget: Budget,
    response_format: dict[str, str] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
) -> tuple[Any, dict[str, int], float]:
    budget.reserve_or_raise(prompt_chars(messages, tools), max_tokens)
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0,
        "extra_body": {"thinking": {"type": "disabled"}},
    }
    if tools:
        kwargs["tools"] = tools
    if tool_choice is not None:
        kwargs["tool_choice"] = tool_choice
    if response_format:
        kwargs["response_format"] = response_format
    response = client.chat.completions.create(**kwargs)
    usage = usage_from_response(response)
    cost = budget.add_usage(usage)
    return response, usage, cost


def record_call(
    result: ReplayResult,
    *,
    kind: str,
    turn: int,
    usage: dict[str, int],
    cost: float,
    effective_window: int,
) -> None:
    result.calls.append(
        {
            "kind": kind,
            "turn": turn,
            "usage": usage,
            "cost_cny": cost,
            "effective_window_tokens": effective_window,
            "utilization": ratio(usage["prompt_tokens"], effective_window),
        }
    )


def compact_with_metrics(
    client: Any,
    context: BenchmarkContext,
    result: ReplayResult,
    *,
    model: str,
    budget: Budget,
    turn: int,
) -> None:
    messages = context.messages
    if len(messages) < 4:
        return
    last_user_msg = messages[-1]
    summary_system = "你是对话摘要器。请简洁总结，但必须保留明确标注的事实、关键决策、文件路径和继续工作所需上下文。"
    summary_context = [
        *messages[:-1],
        UserMessage(
            content="请用中文总结此前对话，必须逐字保留所有标为‘必须精确保留’的键和值，以及关键决策、文件路径和命令。"
        ),
    ]
    response, usage, cost = api_call(
        client,
        model=model,
        messages=to_openai_messages(summary_system, summary_context),
        tools=None,
        max_tokens=2048,
        budget=budget,
    )
    summary_text = response.choices[0].message.content or "[摘要为空]"
    context.messages = [
        UserMessage(content=f"[Previous conversation summary]\n{summary_text}"),
        AssistantMessage(content="已理解此前上下文，可以继续。"),
    ]
    if isinstance(last_user_msg, UserMessage):
        context.messages.append(last_user_msg)
    context.last_prompt_tokens = 0
    result.events.summaries += 1
    record_call(
        result,
        kind="summary",
        turn=turn,
        usage=usage,
        cost=cost,
        effective_window=context.effective_window,
    )


def maybe_compact(
    client: Any,
    context: BenchmarkContext,
    result: ReplayResult,
    *,
    variant: str,
    model: str,
    budget: Budget,
    turn: int,
) -> None:
    if variant == "raw":
        return
    if context.manager.should_compact(context.runtime_state()):
        compact_with_metrics(
            client,
            context,
            result,
            model=model,
            budget=budget,
            turn=turn,
        )


def flatten_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        out: list[str] = []
        for key, item in value.items():
            out.append(str(key))
            out.extend(flatten_strings(item))
        return out
    if isinstance(value, list):
        out = []
        for item in value:
            out.extend(flatten_strings(item))
        return out
    return [str(value)]


def normalize_fact(value: str) -> str:
    """只忽略结构分隔符两侧空白，不吞掉命令或自然语言中的有效空格。"""
    return re.sub(r"\s*([=:])\s*", r"\1", value.strip())


def evaluate_retention(
    client: Any,
    context: BenchmarkContext,
    scenario: dict[str, Any],
    result: ReplayResult,
    *,
    variant: str,
    model: str,
    budget: Budget,
) -> None:
    expected = {fact["key"]: fact["value"] for fact in scenario["facts"]}
    query = (
        "这是基准测试的最终验收。请回忆此前所有标为‘必须精确保留’的事实。"
        "只输出一个 JSON 对象；键使用原始事实名称，值必须逐字一致。需要返回的键："
        + "、".join(expected)
    )
    context.messages.append(UserMessage(content=query))
    maybe_compact(
        client,
        context,
        result,
        variant=variant,
        model=model,
        budget=budget,
        turn=scenario["turns"] + 1,
    )
    response, usage, cost = api_call(
        client,
        model=model,
        messages=context.openai_messages(),
        tools=None,
        max_tokens=512,
        budget=budget,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content or ""
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = {"_unparsed": content}
    haystack = "\n".join(flatten_strings(parsed))
    matched = {key: value in haystack for key, value in expected.items()}
    normalized_haystack = normalize_fact(haystack)
    normalized_matched = {
        key: normalize_fact(value) in normalized_haystack for key, value in expected.items()
    }
    value_matched: dict[str, bool] = {}
    for key, expected_value in expected.items():
        candidates = {normalize_fact(expected_value)}
        if "=" in expected_value:
            candidates.add(normalize_fact(expected_value.split("=", 1)[1]))
        actual_value = parsed.get(key) if isinstance(parsed, dict) else parsed
        actual_haystack = normalize_fact("\n".join(flatten_strings(actual_value)))
        value_matched[key] = any(candidate == actual_haystack or candidate in actual_haystack for candidate in candidates)
    result.retention = {
        "expected": expected,
        "response": parsed,
        "matched": matched,
        "score": ratio(sum(matched.values()), len(matched)),
        "normalized_matched": normalized_matched,
        "normalized_score": ratio(sum(normalized_matched.values()), len(normalized_matched)),
        "value_matched": value_matched,
        "value_score": ratio(sum(value_matched.values()), len(value_matched)),
    }
    record_call(
        result,
        kind="retention",
        turn=scenario["turns"] + 1,
        usage=usage,
        cost=cost,
        effective_window=context.effective_window,
    )


def run_replay(
    client: Any,
    scenario: dict[str, Any],
    *,
    variant: str,
    model: str,
    budget: Budget,
    effective_window: int,
    run_id: str,
) -> tuple[ReplayResult, list[dict[str, Any]]]:
    seed, source_meta = source_snapshot(scenario["source_files"])
    # run_id 放在首部，确保试跑或上一次完整运行留下的服务端缓存不会污染本轮冷启动。
    salt = f"[运行={run_id}；场景={scenario['id']}；变体={variant}]"
    result = ReplayResult(scenario["id"], scenario["name"], variant)

    with tempfile.TemporaryDirectory(prefix="lion-context-bench-") as temp_home:
        context = BenchmarkContext.create(
            system_prompt=(
            salt + "\n你正在参与 Lion Code 上下文管理的固定回放测试。"
            "基准计量点只需简短回复，不要主动调用工具。"
        ),
            effective_window=effective_window,
            result_root=Path(temp_home) / "tool-results",
        )
        tools = context.openai_tools()
        for turn in range(1, scenario["turns"] + 1):
            source = scenario["source_files"][(turn - 1) % len(scenario["source_files"])]
            user_payload = expand_to_bytes(
                seed,
                int(scenario.get("user_payload_bytes", 0)),
                f"{scenario['id']}-user-{turn}-{source}",
            )
            user_text = (
                f"第 {turn} 轮固定回放：继续分析 {source}。"
                f"{facts_for_turn(scenario, turn)}"
            )
            if user_payload:
                user_text += "\n以下是本轮设计讨论记录：\n" + user_payload
            context.messages.append(UserMessage(content=user_text))

            maybe_compact(
                client,
                context,
                result,
                variant=variant,
                model=model,
                budget=budget,
                turn=turn,
            )

            tool_payload = expand_to_bytes(
                seed,
                int(scenario["tool_payload_bytes"]),
                f"{scenario['id']}-tool-{turn}-{source}",
            )
            if variant != "raw":
                persisted = process_tool_result(
                    context,
                    scenario["tool_name"],
                    tool_payload,
                )
                if persisted != tool_payload:
                    result.events.persisted_results += 1
                tool_payload = persisted
            context.messages.extend(make_tool_messages(scenario, turn, tool_payload))
            context.messages.append(
                UserMessage(content="基准计量点：只需回复‘继续’，不要调用工具。")
            )

            if variant == "managed" and turn in scenario.get("idle_before_turns", []):
                context.last_model_call_at = time.time() - MICROCOMPACT_IDLE_S - 1
            apply_pipeline(context, variant, result.events)

            _, usage, cost = api_call(
                client,
                model=model,
                messages=context.openai_messages(),
                tools=tools,
                max_tokens=8,
                budget=budget,
            )
            record_call(
                result,
                kind="turn",
                turn=turn,
                usage=usage,
                cost=cost,
                effective_window=effective_window,
            )
            context.last_prompt_tokens = usage["prompt_tokens"] + usage["completion_tokens"]
            context.last_model_call_at = time.time()
            # 固定回放使用脚本化回复，避免模型随机输出成为 A/B 混杂变量。
            context.messages.append(AssistantMessage(content="继续"))

        evaluate_retention(
            client,
            context,
            scenario,
            result,
            variant=variant,
            model=model,
            budget=budget,
        )
    return result, source_meta


def make_probe_context(effective_window: int) -> BenchmarkContext:
    return BenchmarkContext.create(
        system_prompt="离线上下文压缩探针",
        effective_window=effective_window,
    )


def populate_probe_tools(
    context: BenchmarkContext,
    count: int,
    content: str,
) -> None:
    for i in range(count):
        context.messages.extend(
            [
                AssistantMessage(
                    content=[
                        ToolCall(
                            id=f"probe_{i}",
                            name="read_file",
                            arguments={"file_path": "probe.txt"},
                        )
                    ],
                    stop_reason="toolUse",
                ),
                ToolResultMessage(
                    tool_call_id=f"probe_{i}",
                    tool_name="read_file",
                    content=[TextContent(text=content)],
                ),
            ]
        )


def offline_probes(dataset: dict[str, Any]) -> list[dict[str, Any]]:
    effective = int(dataset["effective_window_tokens"])
    seed, _ = source_snapshot(["lion_code/agent.py", "lion_code/tools.py"])
    probes: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="lion-context-probe-") as temp_home:
        context = BenchmarkContext.create(
            system_prompt="离线上下文压缩探针",
            effective_window=effective,
            result_root=Path(temp_home) / "tool-results",
        )
        raw = expand_to_bytes(seed, 120000, "offline-persistence")
        stored = process_tool_result(context, "read_file", raw)
        probes.append(
            {
                "probe": "large_result_persistence",
                "before_chars": len(raw),
                "after_chars": len(stored),
                "reduction": 1 - ratio(len(stored), len(raw)),
                "full_copy_persisted": stored.startswith("[Result too large"),
            }
        )

    for utilization in (0.55, 0.72):
        context = make_probe_context(effective)
        populate_probe_tools(context, 4, "x" * 60000)
        before = sum(v[0] for v in tool_content_stats(context.messages).values())
        context.last_prompt_tokens = int(effective * utilization)
        context.last_model_call_at = time.time()
        apply_pipeline(context, "managed", EventCounts())
        after = sum(v[0] for v in tool_content_stats(context.messages).values())
        probes.append(
            {
                "probe": f"dynamic_budget_{utilization:.2f}",
                "before_chars": before,
                "after_chars": after,
                "reduction": 1 - ratio(after, before),
            }
        )

    for name, utilization, age_seconds in (
        ("snip_hot_below_override", 0.65, 1),
        ("snip_cold", 0.65, MICROCOMPACT_IDLE_S + 1),
        ("snip_hot_override", 0.78, 1),
    ):
        context = make_probe_context(effective)
        populate_probe_tools(context, 8, "x" * 10000)
        context.last_prompt_tokens = int(effective * utilization)
        context.last_model_call_at = time.time() - age_seconds
        apply_pipeline(context, "managed", EventCounts())
        stats = tool_content_stats(context.messages)
        probes.append(
            {
                "probe": name,
                "snipped_results": sum(1 for _, marker in stats.values() if marker == "snipped"),
                "kept_results": sum(1 for _, marker in stats.values() if marker != "snipped"),
            }
        )

    context = make_probe_context(effective)
    populate_probe_tools(context, 8, "x" * 10000)
    context.last_model_call_at = time.time() - MICROCOMPACT_IDLE_S - 1
    apply_pipeline(context, "managed", EventCounts())
    stats = tool_content_stats(context.messages)
    probes.append(
        {
            "probe": "microcompact_after_idle",
            "cleared_results": sum(1 for _, marker in stats.values() if marker == "microcompacted"),
            "kept_results": sum(1 for _, marker in stats.values() if marker != "microcompacted"),
        }
    )
    return probes


def aggregate_by_variant(results: list[ReplayResult]) -> dict[str, dict[str, Any]]:
    variants = sorted({r.variant for r in results})
    output: dict[str, dict[str, Any]] = {}
    for variant in variants:
        selected = [r for r in results if r.variant == variant]
        calls = [call for result in selected for call in result.calls]
        normal = [call for call in calls if call["kind"] != "summary"]
        usage = sum_usage(call["usage"] for call in calls)
        normal_usage = sum_usage(call["usage"] for call in normal)
        retention_scores = [r.retention.get("score", 0.0) for r in selected]
        normalized_retention_scores = [
            r.retention.get("normalized_score", 0.0) for r in selected
        ]
        value_retention_scores = [r.retention.get("value_score", 0.0) for r in selected]
        output[variant] = {
            "scenario_count": len(selected),
            "call_count": len(calls),
            "summary_call_count": sum(1 for call in calls if call["kind"] == "summary"),
            "all_usage": usage,
            "normal_usage": normal_usage,
            "total_cost_cny": sum(call["cost_cny"] for call in calls),
            "peak_prompt_tokens": max((call["usage"]["prompt_tokens"] for call in normal), default=0),
            "over_effective_window_calls": sum(
                1 for call in normal if call["usage"]["prompt_tokens"] > call["effective_window_tokens"]
            ),
            "cache_hit_rate": ratio(usage["cache_hit_tokens"], usage["prompt_tokens"]),
            "retention_mean": statistics.mean(retention_scores) if retention_scores else 0.0,
            "retention_normalized_mean": (
                statistics.mean(normalized_retention_scores) if normalized_retention_scores else 0.0
            ),
            "retention_value_mean": (
                statistics.mean(value_retention_scores) if value_retention_scores else 0.0
            ),
            "events": {
                key: sum(result.events.as_dict()[key] for result in selected)
                for key in EventCounts().as_dict()
            },
        }
    return output


def comparison(raw: dict[str, Any], managed: dict[str, Any]) -> dict[str, float]:
    return {
        "normal_input_token_reduction": 1
        - ratio(managed["normal_usage"]["prompt_tokens"], raw["normal_usage"]["prompt_tokens"]),
        "all_input_token_reduction_including_summary": 1
        - ratio(managed["all_usage"]["prompt_tokens"], raw["all_usage"]["prompt_tokens"]),
        "peak_prompt_reduction": 1 - ratio(managed["peak_prompt_tokens"], raw["peak_prompt_tokens"]),
        "actual_total_cost_reduction": 1 - ratio(managed["total_cost_cny"], raw["total_cost_cny"]),
        "raw_cache_hit_rate": raw["cache_hit_rate"],
        "managed_cache_hit_rate": managed["cache_hit_rate"],
        "raw_retention": raw["retention_mean"],
        "managed_retention": managed["retention_mean"],
        "raw_retention_normalized": raw["retention_normalized_mean"],
        "managed_retention_normalized": managed["retention_normalized_mean"],
        "raw_retention_value": raw["retention_value_mean"],
        "managed_retention_value": managed["retention_value_mean"],
    }


def replay_from_dict(item: dict[str, Any]) -> ReplayResult:
    result = ReplayResult(
        scenario_id=item["scenario_id"],
        scenario_name=item["scenario_name"],
        variant=item["variant"],
        calls=item["calls"],
        events=EventCounts(**item["events"]),
        retention=item["retention"],
    )
    return result


def merge_result_files(paths: list[str], dataset: dict[str, Any], probes: list[dict[str, Any]]) -> dict[str, Any]:
    inputs = [json.loads(Path(path).read_text(encoding="utf-8")) for path in paths]
    if not inputs:
        raise ValueError("至少需要一个结果文件")
    first_meta = inputs[0]["metadata"]
    scenario_results: list[dict[str, Any]] = []
    source_snapshots: dict[str, Any] = {}
    seen: set[tuple[str, str]] = set()
    for payload in inputs:
        for item in payload.get("scenario_results", []):
            key = (item["scenario_id"], item["variant"])
            if key in seen:
                raise ValueError(f"合并结果存在重复场景/变体：{key[0]} / {key[1]}")
            seen.add(key)
            scenario_results.append(item)
        source_snapshots.update(payload.get("source_snapshots", {}))

    expected = {
        (scenario["id"], variant)
        for scenario in dataset["scenarios"]
        for variant in (["raw", "managed", "eager_ablation"] if scenario["id"] == "hot_cache_progressive" else ["raw", "managed"])
    }
    missing = expected - seen
    if missing:
        formatted = ", ".join(f"{scenario}/{variant}" for scenario, variant in sorted(missing))
        raise ValueError(f"合并后仍缺少结果：{formatted}")

    replays = [replay_from_dict(item) for item in scenario_results]
    aggregate = aggregate_by_variant(replays)
    merged = {
        "metadata": {
            **first_meta,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "online": True,
            "run_id": "merged-" + uuid.uuid4().hex[:8],
            "benchmark_spend_cny": sum(float(p["metadata"].get("benchmark_spend_cny", 0.0)) for p in inputs),
            "merged_from": [str(Path(path)) for path in paths],
        },
        "pricing": dataset["pricing_cny_per_million_tokens"],
        "offline_probes": probes,
        "source_snapshots": source_snapshots,
        "scenario_results": scenario_results,
        "aggregate": aggregate,
        "comparison": comparison(aggregate["raw"], aggregate["managed"]),
    }
    return merged


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def render_report(payload: dict[str, Any]) -> str:
    meta = payload["metadata"]
    aggregate = payload.get("aggregate", {})
    lines = [
        "# Lion Code 上下文管理基准报告",
        "",
        f"- 生成时间：{meta['generated_at']}",
        f"- 模型：`{meta['model']}`",
        f"- API：`{meta['base_url']}`",
        f"- 测试模式：{'真实 API 回放' if meta['online'] else '仅离线探针'}",
        f"- 当前代码模型窗口：{meta['code_model_context_tokens']:,} token",
        f"- 本次有效窗口：{meta['effective_window_tokens']:,} token",
        "- API Key：未写入报告",
        "",
        "## 分层离线探针",
        "",
        "| 探针 | 结果 |",
        "|---|---|",
    ]
    for probe in payload["offline_probes"]:
        if "reduction" in probe:
            result = (
                f"{probe['before_chars']:,} → {probe['after_chars']:,} 字符，"
                f"减少 {pct(probe['reduction'])}"
            )
        elif "snipped_results" in probe:
            result = f"清理 {probe['snipped_results']} 条，保留 {probe['kept_results']} 条"
        else:
            result = f"清理 {probe['cleared_results']} 条，保留 {probe['kept_results']} 条"
        lines.append(f"| `{probe['probe']}` | {result} |")

    if not meta["online"]:
        lines.extend(
            [
                "",
                "## 说明",
                "",
                "离线探针只验证本地压缩行为，不能证明真实 token、缓存命中和 API 成本。",
            ]
        )
        return "\n".join(lines) + "\n"

    lines.extend(
        [
            "",
            "## 在线汇总",
            "",
            "| 变体 | 场景 | 全部输入 token | 缓存命中率 | 峰值输入 | 超过有效窗口 | 逐字/规范化/事实值保留率 | 实际费用（元） |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for variant in ("raw", "managed", "eager_ablation"):
        if variant not in aggregate:
            continue
        item = aggregate[variant]
        lines.append(
            f"| `{variant}` | {item['scenario_count']} | "
            f"{item['all_usage']['prompt_tokens']:,} | {pct(item['cache_hit_rate'])} | "
            f"{item['peak_prompt_tokens']:,} | {item['over_effective_window_calls']} | "
            f"{pct(item['retention_mean'])} / {pct(item['retention_normalized_mean'])} / "
            f"{pct(item['retention_value_mean'])} | "
            f"{item['total_cost_cny']:.4f} |"
        )

    comp = payload["comparison"]
    lines.extend(
        [
            "",
            "## 主要结论：`managed` 相对 `raw`",
            "",
            f"- 常规会话请求累计输入 token：减少 **{pct(comp['normal_input_token_reduction'])}**。",
            f"- 把摘要调用也计入后，全部输入 token：减少 **{pct(comp['all_input_token_reduction_including_summary'])}**。",
            f"- 单次请求峰值输入：减少 **{pct(comp['peak_prompt_reduction'])}**。",
            f"- 按图片费率计算的 API 总费用：减少 **{pct(comp['actual_total_cost_reduction'])}**。",
            f"- 缓存命中率：`raw` {pct(comp['raw_cache_hit_rate'])}，`managed` {pct(comp['managed_cache_hit_rate'])}。",
            f"- 逐字事实保留率：`raw` {pct(comp['raw_retention'])}，`managed` {pct(comp['managed_retention'])}。",
            f"- 规范化事实保留率：`raw` {pct(comp['raw_retention_normalized'])}，`managed` {pct(comp['managed_retention_normalized'])}。",
            f"- 事实值保留率：`raw` {pct(comp['raw_retention_value'])}，`managed` {pct(comp['managed_retention_value'])}。",
            "",
            "## 压缩事件",
            "",
            f"`managed` 共发生：{json.dumps(aggregate['managed']['events'], ensure_ascii=False)}。",
            "",
            "## 费用与限制",
            "",
            f"- 基准脚本记录费用：**{meta['benchmark_spend_cny']:.4f} 元**；手工连通性与缓存预检另约 0.016 元。",
            "- `deepseek-v4-flash` 在当前代码中未登记 1M 窗口，本报告按代码实际回退值 200K、有效预算 180K 测试。",
            "- 测试集是由当前项目源码构造的固定长会话回放，不等同于真实用户生产流量；简历应明确写“长会话回放测试集”。",
            "- OpenAI 兼容后端没有 Anthropic 风格的显式双断点；本次测到的是服务端自动前缀缓存与客户端热度感知清理的组合效果。",
        ]
    )

    if "eager_ablation" in aggregate:
        eager = aggregate["eager_ablation"]
        managed_hot = next(
            (r for r in payload["scenario_results"] if r["scenario_id"] == "hot_cache_progressive" and r["variant"] == "managed"),
            None,
        )
        eager_hot = next(
            (r for r in payload["scenario_results"] if r["scenario_id"] == "hot_cache_progressive" and r["variant"] == "eager_ablation"),
            None,
        )
        if managed_hot and eager_hot:
            m = managed_hot["totals"]
            e = eager_hot["totals"]
            lines.extend(
                [
                    "",
                    "## 热缓存保护消融",
                    "",
                    f"- 生产策略缓存命中率：{pct(m['cache_hit_rate'])}。",
                    f"- 提前改写旧前缀的消融策略：{pct(e['cache_hit_rate'])}。",
                    f"- 消融策略费用：{e['total_cost_cny']:.4f} 元；生产策略费用：{m['total_cost_cny']:.4f} 元。",
                    f"- 消融变体共运行 {eager['call_count']} 次 API 调用，仅用于解释热度机制，不纳入主结论。",
                ]
            )
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    dataset = read_dataset()
    probes = offline_probes(dataset)
    online = bool(args.online)
    if args.merge_results:
        payload = merge_result_files(args.merge_results, dataset, probes)
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        latest = RESULTS_DIR / "latest.json"
        latest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        history = RESULTS_DIR / f"{payload['metadata']['run_id']}.json"
        history.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        REPORT_PATH.write_text(render_report(payload), encoding="utf-8")
        print(f"合并结果：{latest}")
        print(f"报告：{REPORT_PATH}")
        return 0
    effective_window = int(dataset["effective_window_tokens"])
    payload: dict[str, Any] = {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "online": online,
            "model": args.model,
            "base_url": args.base_url,
            "code_model_context_tokens": fallback_context_window(args.model),
            "effective_window_tokens": effective_window,
            "dataset_version": dataset["version"],
            "benchmark_spend_cny": 0.0,
            "run_id": uuid.uuid4().hex[:12],
        },
        "pricing": dataset["pricing_cny_per_million_tokens"],
        "offline_probes": probes,
        "source_snapshots": {},
        "scenario_results": [],
    }

    if online:
        api_key = os.environ.get(args.api_key_env)
        if not api_key:
            raise SystemExit(f"缺少环境变量 {args.api_key_env}；密钥不会从文件或参数读取。")
        price = Price(**dataset["pricing_cny_per_million_tokens"])
        budget = Budget(args.budget_cny, price)
        client = create_benchmark_client(
            api_key=api_key,
            base_url=args.base_url,
            timeout=args.timeout_seconds,
            max_retries=1,
        )
        scenarios = dataset["scenarios"]
        if args.only_scenario:
            allowed = set(args.only_scenario)
            scenarios = [s for s in scenarios if s["id"] in allowed]
            missing = allowed - {s["id"] for s in scenarios}
            if missing:
                raise SystemExit(f"未知场景：{', '.join(sorted(missing))}")

        results: list[ReplayResult] = []
        for scenario in scenarios:
            variants = ["raw", "managed"]
            if scenario["id"] == "hot_cache_progressive":
                variants.append("eager_ablation")
            for variant in variants:
                print(f"运行：{scenario['name']} / {variant}（当前已花费 {budget.spent_cny:.4f} 元）", flush=True)
                replay, source_meta = run_replay(
                    client,
                    scenario,
                    variant=variant,
                    model=args.model,
                    budget=budget,
                    effective_window=effective_window,
                    run_id=payload["metadata"]["run_id"],
                )
                results.append(replay)
                payload["source_snapshots"][scenario["id"]] = source_meta

        payload["scenario_results"] = [
            {
                "scenario_id": result.scenario_id,
                "scenario_name": result.scenario_name,
                "variant": result.variant,
                "calls": result.calls,
                "events": result.events.as_dict(),
                "retention": result.retention,
                "totals": result.totals(),
            }
            for result in results
        ]
        aggregate = aggregate_by_variant(results)
        payload["aggregate"] = aggregate
        if "raw" in aggregate and "managed" in aggregate:
            payload["comparison"] = comparison(aggregate["raw"], aggregate["managed"])
        payload["metadata"]["benchmark_spend_cny"] = budget.spent_cny

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    latest = RESULTS_DIR / "latest.json"
    latest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    history = RESULTS_DIR / f"{payload['metadata']['run_id']}.json"
    history.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    REPORT_PATH.write_text(render_report(payload), encoding="utf-8")
    print(f"结果：{latest}")
    print(f"报告：{REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
