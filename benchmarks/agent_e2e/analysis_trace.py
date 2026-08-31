"""DeepEval 专用的安全语义工具轨迹。

该模块只从 typed Core 工具事件提取有限的动作事实。它不读取 session、stdout
或 stderr，也不参与官方 Harness、ProcessVerifier 或 Opik 的结果判定。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import shlex
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, Literal, cast

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from lion_code.core.types import JSONValue

from .models import SCHEMA_VERSION, VersionedModel

ANALYSIS_TRACE_SCHEMA_VERSION = SCHEMA_VERSION
MAX_ANALYSIS_TRACE_EVENTS = 256
MAX_ANALYSIS_TRACE_EVENT_BYTES = 4096
MAX_ANALYSIS_TRACE_VALUE_LENGTH = 512
MAX_ANALYSIS_TRACE_COMMAND_TARGETS = 16

_SAFE_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_SAFE_KEY = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}\Z")
_HEX_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
_CONTROL_TEXT = re.compile(r"[\x00-\x1f\x7f]")
_SHELL_SYNTAX = re.compile(r"(?:&&|\|\||[;&|<>$`])")
_SECRET_TEXT = re.compile(
    r"(?ix)(?:\b(?:api[_-]?key|authorization|password|secret|token)\b"
    r"\s*[:=]\s*[^\s,;]+|\bbearer\s+[^\s,;]+|\bsk-[a-z0-9_-]{8,})"
)
_PRIVATE_PATH_PARTS = frozenset({"gold", "hidden", "verifier"})
_SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "cookie",
    "password",
    "secret",
    "session",
    "token",
)
_FORBIDDEN_DATA_KEYS = frozenset(
    {
        "command",
        "command_text",
        "raw_command",
        "stdout",
        "stderr",
        "output",
        "raw_output",
        "content",
        "body",
        "prompt",
        "reasoning",
        "old_string",
        "new_string",
    }
)
_KNOWN_ACTIONS = {
    "read_file": "read",
    "write_file": "write",
    "edit_file": "edit",
    "list_files": "list",
    "grep_search": "search",
    "run_shell": "execute",
}
_SHELL_OPTIONS = frozenset(
    {
        "-q",
        "-v",
        "-vv",
        "-x",
        "-ra",
        "--quiet",
        "--verbose",
        "--tb=short",
        "--tb=long",
        "--strict-markers",
        "--no-header",
        "--no-summary",
        "--binary",
        "--check",
        "--cached",
        "--name-only",
        "--stat",
    }
)
_SHELL_FAMILIES = frozenset({"pytest", "python", "git", "rg", "grep", "find"})
_GIT_SUBCOMMANDS = frozenset(
    {"apply", "diff", "log", "show", "status", "add", "commit", "ls-files"}
)


class AnalysisTraceError(ValueError):
    """Analysis Trace 无法生成、读取或通过安全边界。"""


class AnalysisTraceUnavailable(AnalysisTraceError):
    """缺少受控 Analysis Trace 产物，不能把 digest 逆向成语义。"""


class AnalysisTraceSchemaError(AnalysisTraceError):
    """Analysis Trace 版本、字段、顺序或 digest 不满足固定契约。"""


class AnalysisTraceEvent(VersionedModel):
    """一条按原始 Core sequence 标识的安全工具调用或结果。"""

    sequence: int = Field(ge=1)
    kind: Literal["tool_call", "tool_result"]
    tool_call_id: str = Field(min_length=1, max_length=128)
    tool_name: str = Field(min_length=1, max_length=160)
    action: str = Field(min_length=1, max_length=64)
    safe_data: dict[str, JSONValue] = Field(default_factory=dict)

    @field_validator("tool_call_id", "tool_name", "action")
    @classmethod
    def _validate_controlled_token(cls, value: str) -> str:
        if "\n" in value or "\r" in value or "\x00" in value:
            raise ValueError("Analysis Trace identifiers cannot contain control text")
        return value

    @model_validator(mode="after")
    def _validate_safe_payload(self) -> AnalysisTraceEvent:
        _validate_safe_mapping(self.safe_data)
        return self


class AnalysisTrace(VersionedModel):
    """DeepEval 唯一可见的有界语义工具轨迹。"""

    task_id: str = Field(min_length=1, max_length=160)
    trace_id: str = Field(min_length=1, max_length=128)
    events: tuple[AnalysisTraceEvent, ...] = Field(
        default=(), max_length=MAX_ANALYSIS_TRACE_EVENTS
    )
    event_count: int = Field(ge=0, le=MAX_ANALYSIS_TRACE_EVENTS)
    truncated: bool = False
    trace_digest: str = Field(min_length=64, max_length=64)

    @field_validator("task_id", "trace_id")
    @classmethod
    def _validate_identifiers(cls, value: str) -> str:
        if _CONTROL_TEXT.search(value):
            raise ValueError("Analysis Trace identifiers cannot contain control text")
        return value

    @field_validator("trace_digest")
    @classmethod
    def _validate_trace_digest(cls, value: str) -> str:
        if not _HEX_DIGEST.fullmatch(value.casefold()):
            raise ValueError("Analysis Trace trace_digest must be a SHA-256 hex digest")
        return value.casefold()

    @model_validator(mode="after")
    def _validate_event_contract(self) -> AnalysisTrace:
        if self.event_count != len(self.events):
            raise ValueError("Analysis Trace event_count does not match events")
        sequences = tuple(event.sequence for event in self.events)
        if sequences != tuple(sorted(sequences)) or len(set(sequences)) != len(
            sequences
        ):
            raise ValueError("Analysis Trace events must be ordered by unique sequence")
        return self

    @classmethod
    def from_events(
        cls,
        *,
        task_id: str,
        trace_id: str,
        events: Sequence[AnalysisTraceEvent],
        truncated: bool = False,
    ) -> AnalysisTrace:
        """根据已经投影的事件计算稳定 digest。"""

        ordered = tuple(sorted(events, key=lambda event: event.sequence))
        if len(ordered) > MAX_ANALYSIS_TRACE_EVENTS:
            raise AnalysisTraceSchemaError("Analysis Trace exceeds the event limit")
        digest = analysis_trace_digest(
            task_id=task_id,
            trace_id=trace_id,
            events=ordered,
            event_count=len(ordered),
            truncated=truncated,
        )
        return cls(
            task_id=task_id,
            trace_id=trace_id,
            events=ordered,
            event_count=len(ordered),
            truncated=truncated,
            trace_digest=digest,
        )

    def validate_digest(self) -> None:
        """校验产物 digest；模型构造本身允许测试先填充占位 digest。"""

        expected = analysis_trace_digest(
            task_id=self.task_id,
            trace_id=self.trace_id,
            events=self.events,
            event_count=self.event_count,
            truncated=self.truncated,
        )
        if self.trace_digest != expected:
            raise AnalysisTraceSchemaError(
                "Analysis Trace trace_digest does not match its canonical payload"
            )

    def write_json(self, path: str | Path) -> Path:
        """把校验过的 Analysis Trace 写入调用方指定的受控位置。"""

        self.validate_digest()
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(self.canonical_json() + "\n", encoding="utf-8")
        return destination


class AnalysisTraceProjector:
    """从 typed Core tool events 提取安全且有限的调用/结果事件。"""

    def __init__(
        self,
        *,
        workspace: str | Path | None = None,
        max_events: int = MAX_ANALYSIS_TRACE_EVENTS,
    ) -> None:
        if max_events < 1 or max_events > MAX_ANALYSIS_TRACE_EVENTS:
            raise ValueError(
                f"max_events must be between 1 and {MAX_ANALYSIS_TRACE_EVENTS}"
            )
        self.workspace = Path(workspace or Path.cwd()).resolve()
        self.max_events = max_events
        self._events: list[AnalysisTraceEvent] = []
        self._truncated = False
        self._failed = False

    @property
    def events(self) -> tuple[AnalysisTraceEvent, ...]:
        """返回不可变的安全事件快照。"""

        return tuple(self._events)

    @property
    def truncated(self) -> bool:
        return self._truncated

    def project(self, event: object, *, sequence: int) -> AnalysisTraceEvent | None:
        """投影一个 typed Core event；流式 update 与非工具事件被忽略。"""

        if self._failed:
            return None
        try:
            return self._project(event, sequence=sequence)
        except Exception:
            # Analysis Trace 只供 DeepEval 旁路使用；失败后冻结旁路，不影响正式事件。
            self._failed = True
            return None

    def _project(self, event: object, *, sequence: int) -> AnalysisTraceEvent | None:
        payload = _event_payload(event)
        event_type = _event_type(payload, event)
        if event_type == "tool_execution_update":
            return None
        if event_type not in {"tool_execution_start", "tool_execution_end"}:
            return None
        if len(self._events) >= self.max_events:
            self._truncated = True
            return None
        if sequence < 1:
            raise ValueError("Analysis Trace sequence must be positive")

        raw_tool_name = _first_text(payload, "tool_name", "toolName", "name")
        tool_name = _safe_tool_name(raw_tool_name)
        raw_call_id = _first_text(payload, "tool_call_id", "toolCallId", "tool_use_id")
        tool_call_id = _safe_call_id(raw_call_id, sequence)
        arguments = _mapping_value(payload, "args", "arguments", "input")
        if event_type == "tool_execution_start":
            action, safe_data = self._project_call(tool_name, arguments)
            kind: Literal["tool_call", "tool_result"] = "tool_call"
        else:
            action, safe_data = self._project_result(tool_name, payload)
            kind = "tool_result"
        projected = AnalysisTraceEvent(
            sequence=sequence,
            kind=kind,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            action=action,
            safe_data=safe_data,
        )
        self._events.append(projected)
        return projected

    def project_events(self, events: Sequence[object]) -> None:
        """按输入顺序投影一批 Core event，sequence 从 1 开始。"""

        for sequence, event in enumerate(events, start=1):
            self.project(event, sequence=sequence)

    def build(self, *, task_id: str, trace_id: str) -> AnalysisTrace:
        """完成当前投影并计算 canonical digest。"""

        if self._failed:
            raise AnalysisTraceUnavailable(
                "Analysis Trace projector failed during collection"
            )
        return AnalysisTrace.from_events(
            task_id=task_id,
            trace_id=trace_id,
            events=self._events,
            truncated=self._truncated,
        )

    def _project_call(
        self,
        tool_name: str,
        arguments: Mapping[str, Any] | None,
    ) -> tuple[str, dict[str, JSONValue]]:
        args = arguments or {}
        action = _KNOWN_ACTIONS.get(tool_name, "other")
        if tool_name == "read_file":
            return action, _path_data(args, self.workspace, "file_path", "path")
        if tool_name == "list_files":
            data = _path_data(args, self.workspace, "path", "directory")
            pattern = _safe_glob(args.get("pattern"))
            if pattern is not None:
                data["glob"] = pattern
            return action, data
        if tool_name == "grep_search":
            data = _path_data(args, self.workspace, "path", "directory")
            pattern = _safe_query(args.get("pattern"))
            include = _safe_glob(args.get("include"))
            if pattern is not None:
                data["query"] = pattern
            if include is not None:
                data["include"] = include
            return action, data
        if tool_name in {"write_file", "edit_file"}:
            return action, _write_data(tool_name, args, self.workspace)
        if tool_name == "run_shell":
            return action, _shell_data(args.get("command"), self.workspace)
        return "other", _unknown_data(args)

    def _project_result(
        self,
        tool_name: str,
        payload: Mapping[str, Any],
    ) -> tuple[str, dict[str, JSONValue]]:
        action = _KNOWN_ACTIONS.get(tool_name, "other")
        result = _mapping_value(payload, "result", "tool_result") or {}
        details = _mapping_value(result, "details") or {}
        is_error = _bool_value(payload, "is_error", "isError") or bool(
            result.get("is_error", result.get("isError", False))
        )
        data: dict[str, JSONValue] = {"status": "error" if is_error else "ok"}
        if tool_name == "run_shell":
            data.update(_shell_result_data(details, is_error=is_error))
        else:
            data.update(_structured_result_data(details, is_error=is_error))
        if tool_name not in _KNOWN_ACTIONS:
            data["result_digest"] = _digest_json(
                {"is_error": is_error, "details": _safe_digest_value(details)}
            )
        return action, data


def project_analysis_trace(
    task_id: str,
    trace_id: str,
    events: Sequence[object],
    *,
    workspace: str | Path | None = None,
    max_events: int = MAX_ANALYSIS_TRACE_EVENTS,
) -> AnalysisTrace:
    """一次性从 typed Core event 序列生成 Analysis Trace。"""

    projector = AnalysisTraceProjector(workspace=workspace, max_events=max_events)
    projector.project_events(events)
    return projector.build(task_id=task_id, trace_id=trace_id)


def write_analysis_trace(trace: AnalysisTrace, path: str | Path) -> Path:
    """写出已校验的 Analysis Trace JSON。"""

    return trace.write_json(path)


def load_analysis_trace(
    payload: AnalysisTrace | Mapping[str, Any] | str | Path,
    *,
    expected_task_id: str | None = None,
    expected_trace_id: str | None = None,
) -> AnalysisTrace:
    """读取并校验 Analysis Trace；缺失和非法产物使用 typed 错误区分。"""

    if isinstance(payload, AnalysisTrace):
        trace = payload
    else:
        raw = _load_payload(payload)
        _validate_raw_event_versions(raw)
        try:
            trace = AnalysisTrace.from_dict(raw)
        except ValidationError as error:
            raise AnalysisTraceSchemaError(str(error)) from error
        except AnalysisTraceError:
            raise
        except ValueError as error:
            raise AnalysisTraceSchemaError(str(error)) from error
    try:
        trace.validate_digest()
    except AnalysisTraceError:
        raise
    except ValueError as error:
        raise AnalysisTraceSchemaError(str(error)) from error
    if expected_task_id is not None and trace.task_id != expected_task_id:
        raise AnalysisTraceSchemaError(
            f"Analysis Trace task_id mismatch: expected {expected_task_id}, got {trace.task_id}"
        )
    if expected_trace_id is not None and trace.trace_id != expected_trace_id:
        raise AnalysisTraceSchemaError(
            f"Analysis Trace trace_id mismatch: expected {expected_trace_id}, got {trace.trace_id}"
        )
    return trace


def analysis_trace_digest(
    *,
    task_id: str,
    trace_id: str,
    events: Sequence[AnalysisTraceEvent],
    event_count: int,
    truncated: bool,
) -> str:
    """计算不含 ``trace_digest`` 自身的 canonical SHA-256。"""

    payload = {
        "schema_version": ANALYSIS_TRACE_SCHEMA_VERSION,
        "task_id": task_id,
        "trace_id": trace_id,
        "events": [event.model_dump(mode="json") for event in events],
        "event_count": event_count,
        "truncated": truncated,
    }
    return _digest_json(payload)


def _event_payload(event: object) -> Mapping[str, Any]:
    if isinstance(event, Mapping):
        return dict(event)
    if isinstance(event, BaseModel):
        payload = event.model_dump(mode="json")
        return payload if isinstance(payload, Mapping) else {}
    if is_dataclass(event):
        payload = asdict(cast(Any, event))
        return payload if isinstance(payload, Mapping) else {}
    values = getattr(event, "__dict__", None)
    return dict(values) if isinstance(values, Mapping) else {}


def _event_type(payload: Mapping[str, Any], event: object) -> str:
    raw = payload.get("event_type") or payload.get("type") or event.__class__.__name__
    raw_text = str(raw).casefold().replace("-", "_")
    normalized = raw_text.removesuffix("_event").removesuffix("event")
    aliases = {
        "toolexecutionstartevent": "tool_execution_start",
        "toolexecutionendevent": "tool_execution_end",
        "toolexecutionupdateevent": "tool_execution_update",
    }
    compact = re.sub(r"[^a-z0-9]", "", str(raw).casefold())
    return aliases.get(compact, normalized)


def _first_text(payload: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _mapping_value(payload: Mapping[str, Any], *keys: str) -> Mapping[str, Any] | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, Mapping):
            return value
    return None


def _bool_value(payload: Mapping[str, Any], *keys: str) -> bool:
    return any(payload.get(key) is True for key in keys)


def _safe_tool_name(value: str | None) -> str:
    if value and _SAFE_TOKEN.fullmatch(value):
        return value[:160]
    if value:
        return f"tool-{_digest_json(value)[:24]}"
    return "unknown"


def _safe_call_id(value: str | None, sequence: int) -> str:
    if value and _SAFE_TOKEN.fullmatch(value):
        return value
    if value:
        return f"call-{_digest_json(value)[:24]}"
    return f"call-{sequence}"


def _safe_relative_path(value: object, workspace: Path) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if len(raw) > MAX_ANALYSIS_TRACE_VALUE_LENGTH or _CONTROL_TEXT.search(raw):
        return None
    windows_path = PureWindowsPath(raw)
    if (
        windows_path.drive
        or _WINDOWS_ABSOLUTE.match(raw)
        or windows_path.is_absolute()
        or bool(windows_path.root)
    ):
        return None
    try:
        candidate = (workspace / Path(raw)).resolve()
        relative = candidate.relative_to(workspace)
    except (OSError, RuntimeError, ValueError):
        return None
    parts = tuple(part.casefold() for part in relative.parts)
    if any(part in _PRIVATE_PATH_PARTS for part in parts):
        return None
    normalized = relative.as_posix()
    return normalized if normalized and normalized != "." else "."


def _path_data(
    arguments: Mapping[str, Any], workspace: Path, *keys: str
) -> dict[str, JSONValue]:
    # 这里只返回相对路径；绝对、越界和私有 verifier/gold/hidden 路径被丢弃。
    data: dict[str, JSONValue] = {}
    for key in keys:
        value = arguments.get(key)
        path = _safe_relative_path(value, workspace)
        if path is not None:
            data["path"] = path
            break
    return data


def _safe_glob(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip().replace("\\", "/")
    if (
        _CONTROL_TEXT.search(value)
        or len(value) > MAX_ANALYSIS_TRACE_VALUE_LENGTH
        or _WINDOWS_ABSOLUTE.match(value)
        or value.startswith("/")
    ):
        return None
    parts = tuple(part.casefold() for part in Path(value).parts)
    if ".." in parts or any(part in _PRIVATE_PATH_PARTS for part in parts):
        return None
    safe, _ = _redact(value, max_length=160)
    return safe.strip() or None


def _safe_query(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    if _CONTROL_TEXT.search(value):
        return None
    if _contains_path_or_private_text(value):
        return "[FILTERED]"
    safe, _ = _redact(value, max_length=160)
    return safe.strip() or None


def _contains_path_or_private_text(value: str) -> bool:
    return bool(
        _WINDOWS_ABSOLUTE.search(value)
        or value.startswith("/")
        or re.search(r"(?i)(?:^|[/\\.])(?:gold|hidden|verifier)(?:[/\\.]|$)", value)
    )


def _write_data(
    tool_name: str, arguments: Mapping[str, Any], workspace: Path
) -> dict[str, JSONValue]:
    data = _path_data(arguments, workspace, "file_path", "path")
    data["operation"] = tool_name.removesuffix("_file")
    if tool_name == "write_file":
        _add_text_facts(data, "content", arguments.get("content"))
    else:
        _add_text_facts(data, "old", arguments.get("old_string"))
        _add_text_facts(data, "new", arguments.get("new_string"))
    return data


def _add_text_facts(data: dict[str, JSONValue], label: str, value: object) -> None:
    if not isinstance(value, str):
        return
    data[f"{label}_length"] = len(value)
    data[f"{label}_lines"] = value.count("\n") + (1 if value else 0)
    data[f"{label}_digest"] = _digest_json(value)


def _shell_data(command: object, workspace: Path) -> dict[str, JSONValue]:
    tokens = _command_tokens(command)
    if (
        not isinstance(command, str)
        or len(command) > MAX_ANALYSIS_TRACE_EVENT_BYTES
        or not tokens
        or _SHELL_SYNTAX.search(command)
    ):
        family, module_index = "other", None
    else:
        family, module_index = _shell_family(tokens)
    data: dict[str, JSONValue] = {"command_family": family}
    if family == "other":
        # 无法识别的命令只保留参数形状和不可逆摘要，绝不把 command 正文带入
        # Analysis Trace；这也让未知命令在 judge 中明确降级为 other。
        data["argument_keys"] = ["command"]
        data["argument_digest"] = _digest_json({"command": _safe_digest_value(command)})
        return data
    subcommand = _safe_subcommand(tokens, family, module_index)
    if subcommand is not None:
        data["subcommand"] = subcommand
    options = _safe_shell_options(tokens)
    if options:
        safe_options: list[JSONValue] = list(options)
        data["options"] = safe_options
    targets = _shell_targets(tokens, family, module_index, workspace)
    if targets:
        safe_targets: list[JSONValue] = list(targets)
        data["targets"] = safe_targets
        if len(targets) == 1:
            data["target"] = targets[0]
    return data


def _command_tokens(command: object) -> tuple[str, ...]:
    if not isinstance(command, str):
        return ()
    try:
        return tuple(shlex.split(command, posix=True))
    except ValueError:
        return ()


def _shell_family(tokens: Sequence[str]) -> tuple[str, int | None]:
    index = 0
    while index < len(tokens) and (
        "=" in tokens[index] and not tokens[index].startswith("-")
    ):
        index += 1
    if index >= len(tokens):
        return "other", None
    executable = Path(tokens[index]).name.casefold()
    if executable in {"pytest", "py.test"}:
        return "pytest", index
    if executable in {"python", "python3", "python3.12", "py"}:
        if index + 2 < len(tokens) and tokens[index + 1] == "-m":
            module = tokens[index + 2].casefold()
            if module in {"pytest", "py.test"}:
                return "pytest", index + 2
            return "other", index
        if index + 1 < len(tokens) and tokens[index + 1] in {"-c", "-"}:
            return "other", index
        return "python", index
    if executable in _SHELL_FAMILIES:
        return executable, index
    return "other", index


def _safe_subcommand(
    tokens: Sequence[str], family: str, executable_index: int | None
) -> str | None:
    if executable_index is None:
        return None
    if family == "git":
        for token in tokens[executable_index + 1 :]:
            if token in _GIT_SUBCOMMANDS:
                return token
            if not token.startswith("-"):
                return "other"
    if family == "pytest" and executable_index > 0:
        return "pytest"
    return None


def _safe_shell_options(tokens: Sequence[str]) -> list[str]:
    options: list[str] = []
    for token in tokens:
        if token in _SHELL_OPTIONS:
            if token not in options:
                options.append(token)
        elif re.fullmatch(r"--maxfail=[0-9]{1,3}", token):
            if token not in options:
                options.append(token)
        if len(options) >= MAX_ANALYSIS_TRACE_COMMAND_TARGETS:
            break
    return options


def _shell_targets(
    tokens: Sequence[str],
    family: str,
    executable_index: int | None,
    workspace: Path,
) -> list[str]:
    if executable_index is None:
        return []
    ignored = {
        "-m",
        "-q",
        "-v",
        "-vv",
        "-x",
        "-ra",
        "--quiet",
        "--verbose",
        "--strict-markers",
        "--no-header",
        "--no-summary",
        "--",
    }
    targets: list[str] = []
    # ``executable_index`` 已经指向实际的 pytest token；对 ``python -m
    # pytest`` 而言它是 module token，因此不能再次跳过第一个测试目标。
    after_module = True
    for token in tokens[executable_index + 1 :]:
        if token == "-m":
            after_module = False
            continue
        if not after_module:
            after_module = True
            continue
        if token in ignored or token.startswith("-"):
            continue
        candidate = token.split("::", 1)[0]
        if not _looks_like_path(candidate):
            continue
        safe = _safe_relative_path(candidate, workspace)
        if safe is not None and safe not in targets:
            targets.append(safe)
        if len(targets) >= MAX_ANALYSIS_TRACE_COMMAND_TARGETS:
            break
    return targets


def _looks_like_path(value: str) -> bool:
    return (
        value in {".", ".."}
        or "/" in value
        or "\\" in value
        or bool(re.search(r"\.[A-Za-z0-9]{1,12}\Z", value))
    )


def _shell_result_data(
    details: Mapping[str, Any], *, is_error: bool
) -> dict[str, JSONValue]:
    data: dict[str, JSONValue] = {}
    for key in ("exit_code", "returncode", "exitCode"):
        value = details.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            data["exit_code"] = value
            break
    for key in ("test_count", "tests_run", "testCount", "testsRun"):
        value = details.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            data["test_count"] = value
            break
    error_type = _safe_error_type(details)
    if error_type is not None:
        data["error_type"] = error_type
    elif is_error:
        data["error_type"] = "tool_error"
    return data


def _structured_result_data(
    details: Mapping[str, Any], *, is_error: bool
) -> dict[str, JSONValue]:
    data: dict[str, JSONValue] = {}
    error_type = _safe_error_type(details)
    if error_type is not None:
        data["error_type"] = error_type
    elif is_error:
        data["error_type"] = "tool_error"
    for source, target in (
        ("bytes_written", "bytes_written"),
        ("lines_changed", "lines_changed"),
        ("files_changed", "files_changed"),
    ):
        value = details.get(source)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            data[target] = value
    return data


def _safe_error_type(details: Mapping[str, Any]) -> str | None:
    for key in ("error_type", "exception_type", "errorType", "exceptionType"):
        value = details.get(key)
        if isinstance(value, str) and re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_.]{0,79}", value
        ):
            return value
    nested = details.get("error")
    if isinstance(nested, Mapping):
        value = nested.get("type")
        if isinstance(value, str) and re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_.]{0,79}", value
        ):
            return value
    return None


def _unknown_data(arguments: Mapping[str, Any]) -> dict[str, JSONValue]:
    keys = sorted(
        key for key in {_safe_argument_key(key) for key in arguments} if key is not None
    )[:16]
    safe_keys: list[JSONValue] = list(keys)
    return {
        "argument_keys": safe_keys,
        "argument_digest": _digest_json(_safe_digest_value(arguments)),
    }


def _safe_argument_key(value: object) -> str | None:
    key = str(value)
    if any(part in key.casefold() for part in _SENSITIVE_KEY_PARTS):
        return "sensitive"
    if not _SAFE_KEY.fullmatch(key):
        return "key-" + _digest_json(key)[:16]
    return key


def _safe_digest_value(value: object) -> JSONValue:
    if isinstance(value, Mapping):
        return {
            str(_safe_argument_key(key)): _safe_digest_value(nested)
            for key, nested in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_safe_digest_value(item) for item in value[:32]]
    if isinstance(value, str):
        safe, _ = _redact(value, max_length=MAX_ANALYSIS_TRACE_VALUE_LENGTH)
        return safe
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return f"<{value.__class__.__name__}>"


def _validate_safe_mapping(value: Mapping[str, JSONValue]) -> None:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    if len(encoded.encode("utf-8")) > MAX_ANALYSIS_TRACE_EVENT_BYTES:
        raise ValueError("Analysis Trace safe_data exceeds the event size limit")
    if len(value) > 32:
        raise ValueError("Analysis Trace safe_data has too many fields")
    for key, nested in value.items():
        normalized = str(key).casefold()
        if not _SAFE_KEY.fullmatch(str(key)):
            raise ValueError("Analysis Trace safe_data contains an unsafe key")
        if normalized in _FORBIDDEN_DATA_KEYS or any(
            part in normalized for part in _SENSITIVE_KEY_PARTS
        ):
            raise ValueError("Analysis Trace safe_data contains a forbidden field")
        _validate_safe_value(nested, key=normalized)


def _validate_safe_value(value: object, *, key: str) -> None:
    if isinstance(value, str):
        if len(value) > MAX_ANALYSIS_TRACE_VALUE_LENGTH:
            raise ValueError("Analysis Trace safe text exceeds the value limit")
        if _CONTROL_TEXT.search(value):
            raise ValueError("Analysis Trace safe text contains control text")
        if _SECRET_TEXT.search(value):
            raise ValueError("Analysis Trace safe_data contains credential text")
        if _contains_path_or_private_text(value) and key in {
            "path",
            "target",
            "targets",
            "glob",
            "include",
        }:
            raise ValueError("Analysis Trace safe_data contains an unsafe path")
        return
    if isinstance(value, Mapping):
        _validate_safe_mapping(value)
        return
    if isinstance(value, (list, tuple)):
        if len(value) > MAX_ANALYSIS_TRACE_COMMAND_TARGETS:
            raise ValueError("Analysis Trace safe_data list exceeds the value limit")
        for nested in value:
            _validate_safe_value(nested, key=key)
        return
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Analysis Trace safe_data cannot contain non-finite numbers")
    if value is None or isinstance(value, (bool, int, float)):
        return
    raise ValueError("Analysis Trace safe_data must contain JSON values")


def _validate_raw_event_versions(raw: Mapping[str, Any]) -> None:
    if raw.get("schema_version") != ANALYSIS_TRACE_SCHEMA_VERSION:
        return
    events = raw.get("events")
    if not isinstance(events, list):
        return
    for event in events:
        if isinstance(event, Mapping) and event.get("schema_version") != SCHEMA_VERSION:
            raise AnalysisTraceSchemaError(
                "Analysis Trace event schema_version is unsupported"
            )


def _load_payload(
    payload: Mapping[str, Any] | str | Path,
) -> Mapping[str, Any]:
    if isinstance(payload, Mapping):
        return dict(payload)
    path = Path(payload)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise AnalysisTraceUnavailable("Analysis Trace artifact is missing") from error
    except (OSError, UnicodeError) as error:
        raise AnalysisTraceUnavailable(
            "Analysis Trace artifact is unavailable"
        ) from error
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError as error:
        raise AnalysisTraceSchemaError(
            f"Invalid Analysis Trace JSON: {error}"
        ) from error
    if not isinstance(decoded, Mapping):
        raise AnalysisTraceSchemaError("Analysis Trace payload must be a JSON object")
    return dict(decoded)


def _redact(value: str, *, max_length: int) -> tuple[str, int]:
    # 延迟导入避免 TraceRecorder 与该模块形成模块级循环依赖。
    from .trace import redact_text

    return redact_text(value, max_length=max_length)


def _digest_json(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = (
    "ANALYSIS_TRACE_SCHEMA_VERSION",
    "MAX_ANALYSIS_TRACE_EVENTS",
    "MAX_ANALYSIS_TRACE_EVENT_BYTES",
    "AnalysisTrace",
    "AnalysisTraceError",
    "AnalysisTraceEvent",
    "AnalysisTraceProjector",
    "AnalysisTraceSchemaError",
    "AnalysisTraceUnavailable",
    "analysis_trace_digest",
    "load_analysis_trace",
    "project_analysis_trace",
    "write_analysis_trace",
)
