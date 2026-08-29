"""语义化过程证据投影：在脱敏前把 typed Core event 提炼为明确事实。

真实事件携带确定性事实(tool_call_id / is_error / compaction /
termination),但既有 TraceEvent 只保留工具名与摘要,丢弃这些字段
并哈希路径与命令。本模块在脱敏之前的 record 同步点做一次投影,
落盘独立的 ``ProcessEvidence`` 数组,让 ProcessVerifier 读取明确
事实而非猜测脱敏文本。

隐私不变式:绝不在 evidence 中保存命令正文、文件路径原文或工具
输出;路径只落盘分类结果(target_scope)+ digest,命令只落盘
``validation_command`` 标记 + digest。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .models import VersionedModel

# 与 lion_code/core/events.py 的 Literal 一致的 typed event 类型名。
EVENT_TOOL_START = "tool_execution_start"
EVENT_TOOL_UPDATE = "tool_execution_update"
EVENT_TOOL_END = "tool_execution_end"
EVENT_COMPACTION_STARTED = "compaction_started"
EVENT_COMPACTION_COMPLETED = "compaction_completed"
EVENT_TURN_FAILED = "turn_failed"
EVENT_CANCELLED = "cancelled"

# 工具参数中承载路径的键,与 trace.py 的 `_PATH_KEYS` 对齐。
_PATH_ARG_KEYS = (
    "file_path",
    "path",
    "file",
    "cwd",
    "directory",
    "workspace",
)
_COMMAND_ARG_KEYS = ("command", "cmd", "script")


class ToolPhase(str, Enum):
    """工具调用的生命周期阶段。"""

    START = "start"
    UPDATE = "update"
    END = "end"


class TargetScope(str, Enum):
    """路径在哈希前分类的语义范围。"""

    SOURCE = "source"
    TEST = "test"
    VERIFIER = "verifier"
    OTHER = "other"


class CompactionState(str, Enum):
    """上下文压缩阶段。"""

    STARTED = "started"
    COMPLETED = "completed"


class TerminationKind(str, Enum):
    """非正常终止类型。"""

    TURN_FAILED = "turn_failed"
    CANCELLED = "cancelled"


class ProcessEvidence(VersionedModel):
    """一条可审计的过程证据;与被投影 TraceEvent 通过 sequence 关联。"""

    sequence: int = Field(ge=1)
    tool_call_id: str | None = None
    tool_phase: ToolPhase | None = None
    tool_name: str | None = Field(default=None, max_length=160)
    tool_fingerprint: str | None = Field(default=None, min_length=64, max_length=64)
    is_error: bool | None = None
    target_scope: TargetScope = TargetScope.OTHER
    path_digest: str | None = Field(default=None, min_length=64, max_length=64)
    validation_command: bool = False
    validation_command_id: str | None = Field(default=None, max_length=64)
    command_digest: str | None = Field(default=None, min_length=64, max_length=64)
    compaction: CompactionState | None = None
    termination: TerminationKind | None = None
    extensions: dict[str, Any] = Field(default_factory=dict)


class PathScopeRules:
    """路径分类规则;判定优先序为 verifier → test → source → other。"""

    def __init__(
        self,
        *,
        verifier_prefixes: Sequence[str] = (
            ".harbor/",
            "hidden/",
            "verifier/",
            "gold/",
        ),
        test_prefixes: Sequence[str] = ("tests/", "test/"),
    ) -> None:
        self.verifier_prefixes = tuple(verifier_prefixes)
        self.test_prefixes = tuple(test_prefixes)

    def classify(self, raw_path: str | None) -> tuple[TargetScope, str]:
        """把路径分类为语义范围,并返回其 digest;绝不返回原文。"""

        if raw_path is None:
            return TargetScope.OTHER, _digest("")
        normalized = raw_path.replace("\\", "/").lstrip("./")
        if not normalized:
            return TargetScope.OTHER, _digest(raw_path)
        if any(normalized.startswith(prefix) for prefix in self.verifier_prefixes):
            return TargetScope.VERIFIER, _digest(raw_path)
        if any(normalized.startswith(prefix) for prefix in self.test_prefixes):
            return TargetScope.TEST, _digest(raw_path)
        # 绝对系统路径不属于项目 source 范围;其余视为项目文件。
        if Path(raw_path).is_absolute():
            return TargetScope.OTHER, _digest(raw_path)
        return TargetScope.SOURCE, _digest(raw_path)


class ProcessEvidenceProjector:
    """把 typed Core event 投影为 ProcessEvidence 的纯函数式投影器。

    ``validation_commands`` 在构造时注入(来自任务卡
    ``public_validation_commands``),投影时只做命令比对与哈希,
    命令正文不离开本对象之外。
    """

    DEFAULT_WRITE_TOOLS = frozenset({"write_file", "edit_file"})

    def __init__(
        self,
        *,
        validation_commands: Sequence[str] = (),
        path_scope_rules: PathScopeRules | None = None,
        write_tool_names: Sequence[str] | None = None,
    ) -> None:
        self._validation_commands = tuple(validation_commands)
        self._scope_rules = path_scope_rules or PathScopeRules()
        self._write_tool_names = frozenset(write_tool_names or self.DEFAULT_WRITE_TOOLS)

    @property
    def validation_command_heads(self) -> tuple[str, ...]:
        """供审计的已规范化命令首词(不含命令正文)。"""

        return tuple(_command_heads(self._validation_commands))

    def project(self, event: object, *, sequence: int) -> ProcessEvidence | None:
        """对可识别 typed event 返回证据;未知事件返回 None 不抛错。"""

        payload = _event_payload(event)
        event_type = _event_type(payload)
        if event_type == EVENT_TOOL_START:
            return self._project_tool(payload, sequence, ToolPhase.START)
        if event_type == EVENT_TOOL_UPDATE:
            return self._project_tool(payload, sequence, ToolPhase.UPDATE)
        if event_type == EVENT_TOOL_END:
            is_error = payload.get("is_error", payload.get("isError"))
            return self._project_tool(
                payload,
                sequence,
                ToolPhase.END,
                is_error=bool(is_error) if is_error is not None else None,
            )
        if event_type == EVENT_COMPACTION_STARTED:
            return ProcessEvidence(
                sequence=sequence,
                compaction=CompactionState.STARTED,
            )
        if event_type == EVENT_COMPACTION_COMPLETED:
            return ProcessEvidence(
                sequence=sequence,
                compaction=CompactionState.COMPLETED,
            )
        if event_type == EVENT_TURN_FAILED:
            return ProcessEvidence(
                sequence=sequence, termination=TerminationKind.TURN_FAILED
            )
        if event_type == EVENT_CANCELLED:
            return ProcessEvidence(
                sequence=sequence, termination=TerminationKind.CANCELLED
            )
        return None

    def _project_tool(
        self,
        payload: Mapping[str, Any],
        sequence: int,
        phase: ToolPhase,
        *,
        is_error: bool | None = None,
    ) -> ProcessEvidence:
        tool_call_id = _find_text(payload, "tool_call_id", "toolCallId", "tool_use_id")
        tool_name = _find_text(payload, "tool_name", "toolName")
        if tool_name is None:
            return ProcessEvidence(sequence=sequence, tool_phase=phase)
        arguments = _find_mapping(payload, "args", "arguments", "input")
        fingerprint = _tool_fingerprint(tool_name, arguments)
        scope, path_digest = self._scope_for(arguments)
        validation = self._validation_for(arguments)
        return ProcessEvidence(
            sequence=sequence,
            tool_call_id=tool_call_id,
            tool_phase=phase,
            tool_name=tool_name,
            tool_fingerprint=fingerprint,
            is_error=is_error,
            target_scope=scope,
            path_digest=path_digest,
            validation_command=validation is not None,
            validation_command_id=(
                f"validation-{validation}" if validation is not None else None
            ),
            command_digest=self._command_digest_for(arguments),
        )

    def _scope_for(
        self, arguments: Mapping[str, Any] | None
    ) -> tuple[TargetScope, str]:
        if not arguments:
            return TargetScope.OTHER, _digest("")
        raw_path = next(
            (
                str(arguments[key])
                for key in _PATH_ARG_KEYS
                if isinstance(arguments.get(key), str) and arguments[key]
            ),
            None,
        )
        return self._scope_rules.classify(raw_path)

    def _validation_for(self, arguments: Mapping[str, Any] | None) -> int | None:
        if not arguments or not self._validation_commands:
            return None
        command = next(
            (
                str(arguments[key])
                for key in _COMMAND_ARG_KEYS
                if isinstance(arguments.get(key), str) and arguments[key]
            ),
            None,
        )
        if command is None:
            return None
        executed_heads = _command_heads((command,))
        for index, declared in enumerate(self._validation_commands):
            declared_heads = _command_heads((declared,))
            if _heads_match(executed_heads, declared_heads):
                return index
        return None

    def _command_digest_for(self, arguments: Mapping[str, Any] | None) -> str | None:
        if not arguments:
            return None
        command = next(
            (
                str(arguments[key])
                for key in _COMMAND_ARG_KEYS
                if isinstance(arguments.get(key), str) and arguments[key]
            ),
            None,
        )
        return _digest(command) if command is not None else None


def _command_heads(commands: Sequence[str]) -> tuple[str, ...]:
    heads: list[str] = []
    for command in commands:
        stripped = command.strip()
        if not stripped:
            continue
        tokens = stripped.split()
        candidates = [tokens[0]]
        if (
            len(tokens) >= 3
            and tokens[0] in {"python", "python3"}
            and tokens[1] == "-m"
        ):
            candidates.append(tokens[2])
        for head in candidates:
            if head not in heads:
                heads.append(head)
    return tuple(heads)


# 解释器本身不算语义化命令头:python -m pytest 与 pytest -q 应同义。
_INTERPRETER_HEADS = frozenset({"python", "python3", "python2", "py"})


def _heads_match(executed_heads: Sequence[str], declared_heads: Sequence[str]) -> bool:
    meaningful_executed = {
        head for head in executed_heads if head not in _INTERPRETER_HEADS
    }
    meaningful_declared = {
        head for head in declared_heads if head not in _INTERPRETER_HEADS
    }
    # 一侧无语义化命令头(如 python script.py)时保守不匹配,防误报。
    if meaningful_declared:
        return bool(meaningful_executed & meaningful_declared)
    return bool(set(executed_heads) & set(declared_heads))


def _normalize_command(value: str) -> str:
    return " ".join(value.strip().split())


def _tool_fingerprint(tool_name: str, arguments: Mapping[str, Any] | None) -> str:
    if isinstance(arguments, Mapping):
        return _digest({"tool_name": tool_name, "arguments": dict(arguments)})
    return _digest({"tool_name": tool_name})


def _event_payload(event: object) -> Mapping[str, Any]:
    if isinstance(event, Mapping):
        return dict(event)
    if isinstance(event, BaseModel):
        payload = event.model_dump(mode="json")
        return payload if isinstance(payload, Mapping) else {}
    if is_dataclass(event):
        payload = asdict(event)
        return payload if isinstance(payload, Mapping) else {}
    values = getattr(event, "__dict__", None)
    return dict(values) if isinstance(values, Mapping) else {}


def _event_type(payload: Mapping[str, Any]) -> str:
    value = payload.get("type") or payload.get("event_type")
    return str(value) if value is not None else ""


def _find_text(payload: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _find_mapping(payload: Mapping[str, Any], *keys: str) -> Mapping[str, Any] | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, Mapping):
            return value
    return None


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "CompactionState",
    "PathScopeRules",
    "ProcessEvidence",
    "ProcessEvidenceProjector",
    "TargetScope",
    "TerminationKind",
    "ToolPhase",
]
