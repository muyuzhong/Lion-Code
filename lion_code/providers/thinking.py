"""Thinking 档位:档位词汇、归一化、循环,以及档位 -> Provider 参数映射。

档位采纳 Tau 0.3.3 的 6 档词汇(``off``/``minimal``/``low``/``medium``/
``high``/``xhigh``),与 vendored TUI、``SessionRecorder`` 的 ``thinking_level``
字段保持一致。档位到具体 Provider 参数的映射是 Provider 知识,故置于本包:

- Anthropic:档位 -> ``thinking_budget_tokens``(off=None,其余 1024-16384);
- OpenAI-compatible:档位 -> ``reasoning_effort``(off="none",其余原样透传,
  由 provider 层按 Responses/Chat 规范归一化)。

``provider_thinking_levels`` / ``provider_default_thinking_level`` 给出某后端
支持的档位集合与默认值;v1 两后端都返回全 6 档(provider 尽力应用),后续可按
模型细化。
"""

from __future__ import annotations

from typing import Literal

type ThinkingLevel = Literal["low", "medium", "high", "max"]

THINKING_LEVELS: tuple[ThinkingLevel, ...] = (
    "low",
    "medium",
    "high",
    "max",
)
DEFAULT_THINKING_LEVEL: ThinkingLevel = "medium"

# Anthropic thinking budget_tokens per level
_ANTHROPIC_BUDGET_TOKENS: dict[str, int] = {
    "low": 2048,
    "medium": 8192,
    "high": 16384,
    "max": 32768,
}


def normalize_thinking_level(level: str | None) -> ThinkingLevel:
    """归一化档位:``None`` -> 默认;剥空白并小写;未知值抛 ``ValueError``。"""
    if level is None:
        return DEFAULT_THINKING_LEVEL
    normalized = level.strip().lower()
    if normalized not in THINKING_LEVELS:
        raise ValueError(f"Unknown thinking mode: {level!r}")
    return normalized  # type: ignore[return-value]


# 旧 SDK / 历史会话遗留词汇 -> 新 4 档。
_LEGACY_THINKING_MODE_MAP: dict[str, ThinkingLevel] = {
    "off": "low",
    "disabled": "low",
    "minimal": "low",
    "adaptive": "medium",
    "enabled": "medium",
    "xhigh": "max",
}


def coerce_thinking_level(level: str | None) -> ThinkingLevel:
    """容忍式归一化:接受新档位与旧词汇,未知值回落到默认档位。"""
    if level is None:
        return DEFAULT_THINKING_LEVEL
    normalized = level.strip().lower()
    if normalized in THINKING_LEVELS:
        return normalized  # type: ignore[return-value]
    if normalized in _LEGACY_THINKING_MODE_MAP:
        return _LEGACY_THINKING_MODE_MAP[normalized]
    return DEFAULT_THINKING_LEVEL


def next_thinking_level(
    current: ThinkingLevel,
    available: tuple[str, ...] = THINKING_LEVELS,
) -> ThinkingLevel:
    """循环到下一档(在 ``available`` 集合内环绕)。"""
    if not available:
        return current
    index = available.index(current) if current in available else -1
    return available[(index + 1) % len(available)]  # type: ignore[return-value]


def anthropic_budget_tokens_for_level(level: ThinkingLevel) -> int:
    """Anthropic thinking ``budget_tokens``。"""
    return _ANTHROPIC_BUDGET_TOKENS.get(level, _ANTHROPIC_BUDGET_TOKENS[DEFAULT_THINKING_LEVEL])


def openai_reasoning_effort_for_level(level: ThinkingLevel) -> str:
    """OpenAI-compatible ``reasoning_effort``。"""
    if level == "max":
        return "high"
    return level


def provider_thinking_levels(
    provider_kind: str,
    *,
    model: str | None = None,
) -> tuple[ThinkingLevel, ...]:
    """某后端支持的档位集合。v1 两后端都返回 4 档。"""
    return THINKING_LEVELS


def provider_default_thinking_level(
    provider_kind: str,
    *,
    model: str | None = None,
) -> ThinkingLevel:
    """某后端的默认档位。"""
    return DEFAULT_THINKING_LEVEL

