"""旧整体 JSON Session 的读取与 Canonical Message 转换。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lion_code.core.messages import (
    AgentMessage,
    AssistantMessage,
    TextContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)


class LegacySessionError(ValueError):
    """旧 Session 存在但无法安全转换时抛出。"""


def load_legacy_session(session_dir: Path, session_id: str) -> dict[str, Any] | None:
    path = session_dir / f"{_safe_session_id(session_id)}.json"
    if not path.exists():
        return None
    try:
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # 旧版本未指定编码，Windows 上可能按本地代码页写入。
            content = path.read_text()
        data = json.loads(content)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise LegacySessionError(f"Legacy session is invalid: {session_id}") from error
    if not isinstance(data, dict):
        raise LegacySessionError(f"Legacy session root must be an object: {session_id}")
    return data


def list_legacy_sessions(session_dir: Path) -> list[dict[str, Any]]:
    if not session_dir.exists():
        return []
    sessions: list[dict[str, Any]] = []
    for path in session_dir.glob("*.json"):
        try:
            data = load_legacy_session(session_dir, path.stem)
        except LegacySessionError:
            continue
        metadata = data.get("metadata") if data else None
        if isinstance(metadata, dict):
            sessions.append({**metadata, "id": path.stem, "format": "json"})
    return sessions


def legacy_session_messages(data: dict[str, Any]) -> list[AgentMessage]:
    """把旧 OpenAI/Anthropic 字典历史转换为唯一 Canonical 表示。"""
    openai_messages = data.get("openaiMessages")
    if isinstance(openai_messages, list):
        return _openai_messages(openai_messages, _legacy_model(data))

    anthropic_messages = data.get("anthropicMessages")
    if isinstance(anthropic_messages, list):
        return _anthropic_messages(anthropic_messages, _legacy_model(data))

    raise LegacySessionError("Legacy session contains no recognized message history")


def _openai_messages(rows: list[Any], model: str) -> list[AgentMessage]:
    messages: list[AgentMessage] = []
    tool_names: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise LegacySessionError("Legacy OpenAI message must be an object")
        role = row.get("role")
        if role == "system":
            continue
        if role == "user":
            messages.append(UserMessage(content=_content_text(row.get("content"))))
            continue
        if role == "assistant":
            blocks: list[TextContent | ToolCall] = []
            text = _content_text(row.get("content"))
            if text:
                blocks.append(TextContent(text=text))
            for raw_call in row.get("tool_calls") or []:
                if not isinstance(raw_call, dict):
                    continue
                function = raw_call.get("function")
                if not isinstance(function, dict):
                    continue
                call_id = str(raw_call.get("id") or "")
                name = str(function.get("name") or "unknown")
                arguments = _tool_arguments(function.get("arguments"))
                blocks.append(ToolCall(id=call_id, name=name, arguments=arguments))
                tool_names[call_id] = name
            messages.append(
                AssistantMessage(
                    api="legacy-openai",
                    provider="legacy",
                    model=model,
                    content=blocks,
                    stop_reason="toolUse" if any(
                        isinstance(block, ToolCall) for block in blocks
                    ) else "stop",
                )
            )
            continue
        if role == "tool":
            call_id = str(row.get("tool_call_id") or "")
            messages.append(
                ToolResultMessage(
                    tool_call_id=call_id,
                    tool_name=str(row.get("name") or tool_names.get(call_id) or "unknown"),
                    content=_content_text(row.get("content")),
                )
            )
            continue
        raise LegacySessionError(f"Unsupported legacy OpenAI role: {role}")
    return messages


def _anthropic_messages(rows: list[Any], model: str) -> list[AgentMessage]:
    messages: list[AgentMessage] = []
    tool_names: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise LegacySessionError("Legacy Anthropic message must be an object")
        role = row.get("role")
        content = row.get("content")
        blocks = content if isinstance(content, list) else None
        if role == "assistant":
            assistant_blocks: list[TextContent | ToolCall] = []
            for block in blocks or [{"type": "text", "text": _content_text(content)}]:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    call_id = str(block.get("id") or "")
                    name = str(block.get("name") or "unknown")
                    arguments = block.get("input")
                    assistant_blocks.append(
                        ToolCall(
                            id=call_id,
                            name=name,
                            arguments=arguments if isinstance(arguments, dict) else {},
                        )
                    )
                    tool_names[call_id] = name
                elif block.get("type") == "text":
                    assistant_blocks.append(TextContent(text=str(block.get("text") or "")))
            messages.append(
                AssistantMessage(
                    api="legacy-anthropic",
                    provider="legacy",
                    model=model,
                    content=assistant_blocks,
                    stop_reason=(
                        "toolUse"
                        if any(isinstance(block, ToolCall) for block in assistant_blocks)
                        else "stop"
                    ),
                )
            )
            continue
        if role == "user":
            if blocks is None:
                messages.append(UserMessage(content=_content_text(content)))
                continue
            text_parts: list[str] = []
            for block in blocks:
                if not isinstance(block, dict):
                    text_parts.append(str(block))
                    continue
                if block.get("type") != "tool_result":
                    text_parts.append(_content_text(block))
                    continue
                if any(text_parts):
                    messages.append(UserMessage(content="\n".join(filter(None, text_parts))))
                    text_parts = []
                call_id = str(block.get("tool_use_id") or "")
                messages.append(
                    ToolResultMessage(
                        tool_call_id=call_id,
                        tool_name=tool_names.get(call_id, "unknown"),
                        content=_content_text(block.get("content")),
                        is_error=bool(block.get("is_error", False)),
                    )
                )
            if any(text_parts):
                messages.append(UserMessage(content="\n".join(filter(None, text_parts))))
            continue
        raise LegacySessionError(f"Unsupported legacy Anthropic role: {role}")
    return messages


def _legacy_model(data: dict[str, Any]) -> str:
    metadata = data.get("metadata")
    if isinstance(metadata, dict) and metadata.get("model"):
        return str(metadata["model"])
    return "unknown"


def _tool_arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _content_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(filter(None, (_content_text(item) for item in value)))
    if isinstance(value, dict):
        if value.get("type") == "text":
            return str(value.get("text") or "")
        if "content" in value:
            return _content_text(value["content"])
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _safe_session_id(session_id: str) -> str:
    if not session_id or Path(session_id).name != session_id or session_id in {".", ".."}:
        raise ValueError("Invalid session id")
    return session_id
