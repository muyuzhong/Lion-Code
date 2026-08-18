"""Agent 外部的长期执行控制平面。

本模块只保存执行控制状态，并通过公开的 Agent 运行结果、事件和 session
reference 驱动下一次运行。它不参与 Agent 的内部构造、工具执行或会话内容存储。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import tempfile
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal, Protocol

from lion_code.core.events import AgentEvent

type Phase = Literal[
    "pending",
    "running",
    "recovery",
    "retry_wait",
    "completed",
    "failed",
    "cancelled",
]
type Status = Literal["pending", "running", "completed", "failed", "cancelled"]
type PublicAgentEventListener = Callable[[AgentEvent], Awaitable[None] | None]


class PublicAgentResult(Protocol):
    """Agent 对外暴露给 Supervisor 的最小结果契约。"""

    @property
    def session_id(self) -> str: ...

    @property
    def stop_reason(self) -> str: ...

    @property
    def error(self) -> str | None: ...


class AgentPort(Protocol):
    """Supervisor 可以使用的公开 Agent 运行端口。"""

    @property
    def session_id(self) -> str: ...

    def subscribe(self, listener: PublicAgentEventListener) -> Callable[[], None]: ...

    async def run(
        self, prompt: str, *, timeout: float | None = None
    ) -> PublicAgentResult: ...

    async def restore(self, session_id: str) -> bool: ...

    def cancel(self) -> None: ...

    async def close(self) -> None: ...


type AgentFactory = Callable[[], AgentPort]


class Scheduler(Protocol):
    """等待下一次执行时机的窄端口。"""

    async def wait(self, delay_seconds: float) -> None: ...


class AsyncioScheduler:
    """基于当前进程事件循环的默认调度实现。"""

    async def wait(self, delay_seconds: float) -> None:
        await asyncio.sleep(delay_seconds)


class CheckpointError(ValueError):
    """Checkpoint 文档缺失、损坏或越过了执行控制契约。"""


_PHASES = frozenset(
    {"pending", "running", "recovery", "retry_wait", "completed", "failed", "cancelled"}
)
_STATUSES = frozenset({"pending", "running", "completed", "failed", "cancelled"})
_STATE_FIELDS = frozenset(
    {
        "goal_id",
        "goal",
        "phase",
        "status",
        "attempt",
        "session_id",
        "retry_count",
        "last_stop_reason",
        "last_error",
        "created_at",
        "updated_at",
        "next_run_at",
    }
)


def _finite_number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CheckpointError(f"{field_name} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise CheckpointError(f"{field_name} must be finite")
    return number


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise CheckpointError(f"{field_name} must be a non-empty string")
    return value


def _optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise CheckpointError(f"{field_name} must be a string or null")
    return value


def _non_negative_integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CheckpointError(f"{field_name} must be a non-negative integer")
    return value


def _goal_id(prompt: str) -> str:
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:20]
    return f"goal-{digest}"


def _validate_state_identity(goal_id: str, goal: str) -> None:
    _required_text(goal_id, "goal_id")
    _required_text(goal, "goal")


def _validate_state_phase_status(phase: Phase, status: Status) -> None:
    if phase not in _PHASES:
        raise ValueError(f"unknown phase: {phase}")
    if status not in _STATUSES:
        raise ValueError(f"unknown status: {status}")
    expected_statuses: dict[Phase, Status] = {
        "pending": "pending",
        "running": "running",
        "recovery": "running",
        "retry_wait": "pending",
        "completed": "completed",
        "failed": "failed",
        "cancelled": "cancelled",
    }
    expected_status = expected_statuses[phase]
    if status != expected_status:
        raise ValueError(f"phase/status mismatch: {phase}/{status}")


def _validate_state_counters(attempt: int, retry_count: int) -> None:
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 0:
        raise ValueError("attempt must be a non-negative integer")
    if (
        isinstance(retry_count, bool)
        or not isinstance(retry_count, int)
        or retry_count < 0
    ):
        raise ValueError("retry_count must be a non-negative integer")


def _validate_state_optional_text(
    session_id: str | None,
    last_stop_reason: str | None,
    last_error: str | None,
) -> None:
    if session_id is not None and not isinstance(session_id, str):
        raise ValueError("session_id must be a string or null")
    if last_stop_reason is not None and not isinstance(last_stop_reason, str):
        raise ValueError("last_stop_reason must be a string or null")
    if last_error is not None and not isinstance(last_error, str):
        raise ValueError("last_error must be a string or null")


def _validate_state_timestamps(
    created_at: float,
    updated_at: float,
    next_run_at: float | None,
) -> None:
    if (
        isinstance(created_at, bool)
        or not isinstance(created_at, (int, float))
        or isinstance(updated_at, bool)
        or not isinstance(updated_at, (int, float))
        or not math.isfinite(created_at)
        or not math.isfinite(updated_at)
    ):
        raise ValueError("timestamps must be finite")
    if next_run_at is not None and (
        isinstance(next_run_at, bool)
        or not isinstance(next_run_at, (int, float))
        or not math.isfinite(next_run_at)
    ):
        raise ValueError("next_run_at must be finite or null")


@dataclass(frozen=True, slots=True)
class Goal:
    """Supervisor 要执行的不可变目标。"""

    prompt: str
    id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.prompt, str) or not self.prompt.strip():
            raise ValueError("goal prompt must be a non-empty string")
        if self.id and (not isinstance(self.id, str) or not self.id.strip()):
            raise ValueError("goal id must be a non-empty string")
        if not self.id:
            object.__setattr__(self, "id", _goal_id(self.prompt))


@dataclass(frozen=True, slots=True)
class SupervisorState:
    """Checkpoint 的完整且唯一的执行控制形状。"""

    goal_id: str
    goal: str
    phase: Phase = "pending"
    status: Status = "pending"
    attempt: int = 0
    session_id: str | None = None
    retry_count: int = 0
    last_stop_reason: str | None = None
    last_error: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    next_run_at: float | None = None

    def __post_init__(self) -> None:
        _validate_state_identity(self.goal_id, self.goal)
        _validate_state_phase_status(self.phase, self.status)
        _validate_state_counters(self.attempt, self.retry_count)
        _validate_state_optional_text(
            self.session_id, self.last_stop_reason, self.last_error
        )
        _validate_state_timestamps(
            self.created_at,
            self.updated_at,
            self.next_run_at,
        )

    def to_dict(self) -> dict[str, object]:
        """返回严格的持久化字段，不暴露 Agent 运行对象。"""

        return {
            "goal_id": self.goal_id,
            "goal": self.goal,
            "phase": self.phase,
            "status": self.status,
            "attempt": self.attempt,
            "session_id": self.session_id,
            "retry_count": self.retry_count,
            "last_stop_reason": self.last_stop_reason,
            "last_error": self.last_error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "next_run_at": self.next_run_at,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> SupervisorState:
        """严格读取一个 checkpoint，拒绝未知字段和错误类型。"""

        fields = set(value)
        if fields != _STATE_FIELDS:
            missing = sorted(_STATE_FIELDS - fields)
            extra = sorted(fields - _STATE_FIELDS)
            details = []
            if missing:
                details.append(f"missing={missing}")
            if extra:
                details.append(f"extra={extra}")
            raise CheckpointError("invalid checkpoint fields: " + ", ".join(details))

        phase = _required_text(value["phase"], "phase")
        status = _required_text(value["status"], "status")
        if phase not in _PHASES:
            raise CheckpointError(f"unknown phase: {phase}")
        if status not in _STATUSES:
            raise CheckpointError(f"unknown status: {status}")

        attempt = _non_negative_integer(value["attempt"], "attempt")
        retry_count = _non_negative_integer(value["retry_count"], "retry_count")
        created_at = _finite_number(value["created_at"], "created_at")
        updated_at = _finite_number(value["updated_at"], "updated_at")
        next_run_at_value = value["next_run_at"]
        next_run_at = (
            None
            if next_run_at_value is None
            else _finite_number(next_run_at_value, "next_run_at")
        )
        try:
            return cls(
                goal_id=_required_text(value["goal_id"], "goal_id"),
                goal=_required_text(value["goal"], "goal"),
                phase=phase,  # type: ignore[arg-type]
                status=status,  # type: ignore[arg-type]
                attempt=attempt,
                session_id=_optional_text(value["session_id"], "session_id"),
                retry_count=retry_count,
                last_stop_reason=_optional_text(
                    value["last_stop_reason"], "last_stop_reason"
                ),
                last_error=_optional_text(value["last_error"], "last_error"),
                created_at=created_at,
                updated_at=updated_at,
                next_run_at=next_run_at,
            )
        except ValueError as exc:
            raise CheckpointError(str(exc)) from exc


class CheckpointStore(Protocol):
    """Supervisor execution-control checkpoint 的读写端口。"""

    async def load(self, goal_id: str) -> SupervisorState | None: ...

    async def save(self, state: SupervisorState) -> None: ...


class VolatileCheckpointStore:
    """仅用于测试和单进程组合的非持久 checkpoint store。"""

    def __init__(self) -> None:
        self._states: dict[str, SupervisorState] = {}

    async def load(self, goal_id: str) -> SupervisorState | None:
        return self._states.get(goal_id)

    async def save(self, state: SupervisorState) -> None:
        self._states[state.goal_id] = state


def _safe_goal_id(goal_id: str) -> str:
    if not goal_id or goal_id in {".", ".."}:
        raise CheckpointError("goal_id cannot be empty or a path marker")
    if any(separator in goal_id for separator in ("/", "\\")):
        raise CheckpointError("goal_id cannot contain path separators")
    return goal_id


class JsonCheckpointStore:
    """将严格执行控制状态原子写入调用方指定目录。"""

    def __init__(self, directory: str | os.PathLike[str]) -> None:
        self._directory = Path(directory)

    def _path_for(self, goal_id: str) -> Path:
        return self._directory / f"{_safe_goal_id(goal_id)}.json"

    async def load(self, goal_id: str) -> SupervisorState | None:
        path = self._path_for(goal_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CheckpointError(f"cannot load checkpoint {goal_id}: {exc}") from exc
        if not isinstance(payload, dict):
            raise CheckpointError("checkpoint root must be an object")
        return SupervisorState.from_dict(payload)

    async def save(self, state: SupervisorState) -> None:
        path = self._path_for(state.goal_id)
        self._directory.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.stem}.", suffix=".tmp", dir=self._directory
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(
                    state.to_dict(),
                    handle,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, path)
        except Exception:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
            raise


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """根据公开 stop reason 决定是否重新运行及等待多久。"""

    max_attempts: int = 3
    initial_delay_seconds: float = 0.0
    multiplier: float = 2.0
    max_delay_seconds: float = 3600.0
    retryable_stop_reasons: frozenset[str] = frozenset({"timeout", "model_error"})

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_attempts, bool)
            or not isinstance(self.max_attempts, int)
            or self.max_attempts <= 0
        ):
            raise ValueError("max_attempts must be a positive integer")
        for field_name in (
            "initial_delay_seconds",
            "multiplier",
            "max_delay_seconds",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{field_name} must be a number")
            if not math.isfinite(float(value)):
                raise ValueError(f"{field_name} must be finite")
        if self.initial_delay_seconds < 0:
            raise ValueError("initial_delay_seconds must be non-negative")
        if self.multiplier < 1:
            raise ValueError("multiplier must be at least one")
        if self.max_delay_seconds < 0:
            raise ValueError("max_delay_seconds must be non-negative")
        if self.max_delay_seconds < self.initial_delay_seconds:
            raise ValueError("max_delay_seconds cannot be less than initial delay")
        reasons = frozenset(self.retryable_stop_reasons)
        if any(not isinstance(reason, str) or not reason for reason in reasons):
            raise ValueError("retryable stop reasons must be non-empty strings")
        object.__setattr__(self, "retryable_stop_reasons", reasons)

    def should_retry(
        self, *, attempt: int, stop_reason: str
    ) -> bool:
        return (
            attempt < self.max_attempts
            and stop_reason in self.retryable_stop_reasons
        )

    def delay_seconds(self, retry_number: int) -> float:
        if retry_number <= 0:
            raise ValueError("retry_number must be positive")
        try:
            delay = self.initial_delay_seconds * (self.multiplier ** (retry_number - 1))
        except OverflowError:
            delay = self.max_delay_seconds
        return min(float(delay), self.max_delay_seconds)


@dataclass(frozen=True, slots=True)
class SupervisorResult:
    """一次 Supervisor 调用的执行控制结果，不携带 Agent 内容。"""

    state: SupervisorState

    @property
    def status(self) -> Status:
        return self.state.status

    @property
    def attempt(self) -> int:
        return self.state.attempt

    @property
    def session_id(self) -> str | None:
        return self.state.session_id

    @property
    def stop_reason(self) -> str | None:
        return self.state.last_stop_reason

    @property
    def succeeded(self) -> bool:
        return self.state.status == "completed"


@dataclass(frozen=True, slots=True)
class _AttemptOutcome:
    stop_reason: str
    error: str | None = None
    session_id: str | None = None
    cancelled: bool = False


@dataclass(frozen=True, slots=True)
class _PreparedAttempt:
    agent: AgentPort | None
    session_id: str | None
    outcome: _AttemptOutcome | None = None


_RUNNING_EVENT_TYPES = frozenset(
    {
        "agent_start",
        "turn_start",
        "turn_end",
        "message_start",
        "message_update",
        "message_end",
        "tool_execution_start",
        "tool_execution_update",
        "tool_execution_end",
        "compaction_completed",
    }
)
_CANCELLED_STOP_REASONS = frozenset({"aborted"})


class Supervisor:
    """在 Agent 外部编排目标、重试、恢复和 checkpoint。

    ``agent_factory`` 决定使用哪个 Profile-backed Agent。Supervisor 只通过
    ``AgentPort`` 观察一次运行，不持有 Agent 的内部 runtime、工具或会话内容。
    """

    def __init__(
        self,
        *,
        agent_factory: AgentFactory,
        goal: Goal | str,
        retry_policy: RetryPolicy | None = None,
        checkpoint_store: CheckpointStore,
        scheduler: Scheduler | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._agent_factory = agent_factory
        self._goal = goal if isinstance(goal, Goal) else Goal(goal)
        self._retry_policy = retry_policy or RetryPolicy()
        self._checkpoint_store = checkpoint_store
        self._scheduler = scheduler or AsyncioScheduler()
        self._clock = clock
        self._state: SupervisorState | None = None
        self._current_agent: AgentPort | None = None
        self._run_task: asyncio.Task[SupervisorResult] | None = None
        self._cancel_requested = False

    @property
    def goal(self) -> Goal:
        return self._goal

    @property
    def state(self) -> SupervisorState | None:
        return self._state

    def cancel(self) -> None:
        """请求当前运行在最近的公开执行边界停止，且绝不触发重试。"""

        self._cancel_requested = True
        agent = self._current_agent
        if agent is not None:
            agent.cancel()
        task = self._run_task
        current = asyncio.current_task()
        if (
            agent is None
            and task is not None
            and task is not current
            and not task.done()
        ):
            task.cancel()

    async def run(self) -> SupervisorResult:
        """加载 checkpoint 并运行至终态。

        Agent factory、session restore、公开 Agent run 和 checkpoint store 都是
        边界操作；它们的失败会转为带 stop reason 的 Supervisor 状态，以便由
        注入的 RetryPolicy 作出恢复决定。调用方取消本协程时仍保留 CancelledError。
        """

        if self._run_task is not None and not self._run_task.done():
            raise RuntimeError("Supervisor is already running")
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("Supervisor.run() requires an active event loop")
        self._run_task = task
        self._cancel_requested = False
        try:
            state = await self._load_or_create()
            if state.status in {"completed", "failed", "cancelled"}:
                return SupervisorResult(state)

            while True:
                if self._cancel_requested:
                    state = await self._mark_cancelled(state)
                    return SupervisorResult(state)
                if state.phase == "retry_wait":
                    await self._wait_for_retry(state)
                prepared = await self._prepare_attempt(state)
                if prepared.status in {"failed", "cancelled"}:
                    return SupervisorResult(prepared)
                state = prepared
                outcome = await self._execute_attempt(state)
                state = await self._apply_outcome(state, outcome)
                if state.status in {"completed", "failed", "cancelled"}:
                    return SupervisorResult(state)
        except asyncio.CancelledError:
            if self._cancel_requested:
                if self._state is None:
                    raise
                if self._state.status in {"completed", "failed", "cancelled"}:
                    return SupervisorResult(self._state)
                return SupervisorResult(await self._mark_cancelled(self._state))
            if self._state is not None and self._state.status not in {
                "completed",
                "failed",
                "cancelled",
            }:
                try:
                    await self._mark_cancelled(self._state)
                except Exception:
                    pass
            raise
        finally:
            self._run_task = None

    async def _load_or_create(self) -> SupervisorState:
        state = await self._checkpoint_store.load(self._goal.id)
        if state is None:
            now = self._clock()
            state = SupervisorState(
                goal_id=self._goal.id,
                goal=self._goal.prompt,
                created_at=now,
                updated_at=now,
            )
            return await self._save(state)
        if state.goal_id != self._goal.id or state.goal != self._goal.prompt:
            raise CheckpointError("checkpoint goal does not match Supervisor goal")
        self._state = state
        return state

    async def _save(self, state: SupervisorState) -> SupervisorState:
        self._state = state
        await self._checkpoint_store.save(state)
        return state

    async def _prepare_attempt(self, state: SupervisorState) -> SupervisorState:
        next_attempt = state.attempt + 1
        if next_attempt > self._retry_policy.max_attempts:
            return await self._save(
                replace(
                    state,
                    phase="failed",
                    status="failed",
                    last_stop_reason="max_attempts",
                    last_error="maximum attempts reached before the next run",
                    next_run_at=None,
                    updated_at=self._clock(),
                )
            )
        return await self._save(
            replace(
                state,
                phase="running",
                status="running",
                attempt=next_attempt,
                next_run_at=None,
                updated_at=self._clock(),
            )
        )

    async def _wait_for_retry(self, state: SupervisorState) -> None:
        if state.next_run_at is None:
            return
        delay = max(0.0, state.next_run_at - self._clock())
        if delay:
            await self._scheduler.wait(delay)

    async def _execute_attempt(self, state: SupervisorState) -> _AttemptOutcome:
        prepared = await self._prepare_agent(state)
        agent = prepared.agent
        outcome = prepared.outcome
        unsubscribe: Callable[[], None] | None = None
        cleanup_error: str | None = None
        try:
            if outcome is None:
                if agent is None or prepared.session_id is None:
                    outcome = _AttemptOutcome(
                        "agent_lifecycle_error",
                        "Agent preparation did not produce a public session",
                    )
                else:
                    await self._save(
                        replace(
                            self._state or state,
                            session_id=prepared.session_id,
                            updated_at=self._clock(),
                        )
                    )
                    outcome, unsubscribe = await self._run_agent_attempt(
                        agent, prepared.session_id
                    )
        except asyncio.CancelledError:
            if agent is not None:
                agent.cancel()
            raise
        except Exception as exc:
            outcome = _AttemptOutcome(
                "agent_lifecycle_error",
                str(exc) or type(exc).__name__,
                prepared.session_id,
            )
        finally:
            cleanup_error = await self._cleanup_attempt(agent, unsubscribe)
            self._current_agent = None

        return self._finalize_attempt(outcome, cleanup_error)

    async def _prepare_agent(self, state: SupervisorState) -> _PreparedAttempt:
        agent: AgentPort | None = None
        try:
            agent = self._agent_factory()
            self._current_agent = agent
            current_session_id = self._read_session_id(agent)
        except Exception as exc:
            return _PreparedAttempt(
                agent,
                None,
                _AttemptOutcome("agent_factory_error", str(exc) or type(exc).__name__),
            )

        if state.session_id is None:
            return _PreparedAttempt(agent, current_session_id)
        try:
            restored = await self._restore_session(agent, state.session_id)
        except Exception as exc:
            return _PreparedAttempt(
                agent,
                current_session_id,
                _AttemptOutcome(
                    "session_restore_error",
                    str(exc) or type(exc).__name__,
                    current_session_id,
                ),
            )
        if not restored:
            return _PreparedAttempt(
                agent,
                current_session_id,
                _AttemptOutcome(
                    "session_restore_error",
                    "Agent could not restore the checkpoint session",
                    current_session_id,
                ),
            )
        try:
            current_session_id = self._read_session_id(agent)
        except Exception as exc:
            return _PreparedAttempt(
                agent,
                current_session_id,
                _AttemptOutcome(
                    "session_restore_error",
                    str(exc) or type(exc).__name__,
                    current_session_id,
                ),
            )
        return _PreparedAttempt(agent, current_session_id)

    async def _run_agent_attempt(
        self, agent: AgentPort, session_id: str
    ) -> tuple[_AttemptOutcome, Callable[[], None]]:
        async def on_event(event: AgentEvent) -> None:
            await self._observe_event(event)

        unsubscribe = agent.subscribe(on_event)
        if self._cancel_requested:
            agent.cancel()
            return (
                _AttemptOutcome(
                    "cancelled",
                    "Supervisor cancellation requested",
                    session_id,
                    True,
                ),
                unsubscribe,
            )
        return await self._run_public_agent(agent, session_id), unsubscribe

    async def _run_public_agent(
        self, agent: AgentPort, session_id: str
    ) -> _AttemptOutcome:
        try:
            public_result = await agent.run(
                self._goal.prompt,
                timeout=None,
            )
        except asyncio.CancelledError:
            agent.cancel()
            raise
        except Exception as exc:
            return _AttemptOutcome(
                "agent_run_error", str(exc) or type(exc).__name__, session_id
            )
        return self._result_to_outcome(public_result, session_id)

    def _result_to_outcome(
        self, public_result: PublicAgentResult, session_id: str
    ) -> _AttemptOutcome:
        try:
            stop_reason = public_result.stop_reason
            if not isinstance(stop_reason, str) or not stop_reason:
                raise TypeError("public result stop_reason must be a non-empty string")
            result_session_id = public_result.session_id
            if not isinstance(result_session_id, str) or not result_session_id:
                result_session_id = session_id
            error = public_result.error
            if error is not None and not isinstance(error, str):
                error = str(error)
            return _AttemptOutcome(
                stop_reason,
                error,
                result_session_id,
                self._cancel_requested or stop_reason in _CANCELLED_STOP_REASONS,
            )
        except Exception as exc:
            return _AttemptOutcome(
                "agent_result_contract_error",
                str(exc) or type(exc).__name__,
                session_id,
            )

    @staticmethod
    async def _cleanup_attempt(
        agent: AgentPort | None, unsubscribe: Callable[[], None] | None
    ) -> str | None:
        cleanup_error: str | None = None
        if unsubscribe is not None:
            try:
                unsubscribe()
            except Exception as exc:
                cleanup_error = str(exc) or type(exc).__name__
        if agent is not None:
            try:
                await agent.close()
            except Exception as exc:
                cleanup_error = cleanup_error or (str(exc) or type(exc).__name__)
        return cleanup_error

    @staticmethod
    def _finalize_attempt(
        outcome: _AttemptOutcome | None, cleanup_error: str | None
    ) -> _AttemptOutcome:
        if outcome is None:
            return _AttemptOutcome(
                "agent_lifecycle_error", cleanup_error or "Agent ended without a result"
            )
        if cleanup_error and outcome.stop_reason == "completed":
            return _AttemptOutcome(
                "agent_close_error", cleanup_error, outcome.session_id
            )
        return outcome

    async def _observe_event(self, event: AgentEvent) -> None:
        state = self._state
        if state is None or state.status != "running":
            return
        event_type = getattr(event, "type", None)
        phase: Phase | None = None
        if event_type == "compaction_started" or event_type == "turn_failed":
            phase = "recovery"
        elif event_type == "cancelled":
            phase = "cancelled"
        elif event_type in _RUNNING_EVENT_TYPES:
            phase = "running"
        if phase is not None and phase != state.phase:
            status: Status = "cancelled" if phase == "cancelled" else state.status
            await self._save(
                replace(
                    state,
                    phase=phase,
                    status=status,
                    updated_at=self._clock(),
                )
            )

    async def _apply_outcome(
        self, state: SupervisorState, outcome: _AttemptOutcome
    ) -> SupervisorState:
        session_id = outcome.session_id or state.session_id
        if outcome.cancelled or self._cancel_requested:
            return await self._mark_cancelled(
                replace(
                    state,
                    session_id=session_id,
                    last_stop_reason=outcome.stop_reason,
                    last_error=outcome.error,
                )
            )
        if outcome.stop_reason == "completed":
            return await self._save(
                replace(
                    state,
                    phase="completed",
                    status="completed",
                    session_id=session_id,
                    last_stop_reason=outcome.stop_reason,
                    last_error=None,
                    next_run_at=None,
                    updated_at=self._clock(),
                )
            )
        if self._retry_policy.should_retry(
            attempt=state.attempt,
            stop_reason=outcome.stop_reason,
        ):
            retry_count = state.retry_count + 1
            delay = self._retry_policy.delay_seconds(retry_count)
            now = self._clock()
            return await self._save(
                replace(
                    state,
                    phase="retry_wait",
                    status="pending",
                    session_id=session_id,
                    retry_count=retry_count,
                    last_stop_reason=outcome.stop_reason,
                    last_error=outcome.error,
                    next_run_at=now + delay,
                    updated_at=now,
                )
            )
        return await self._save(
            replace(
                state,
                phase="failed",
                status="failed",
                session_id=session_id,
                last_stop_reason=outcome.stop_reason,
                last_error=outcome.error,
                next_run_at=None,
                updated_at=self._clock(),
            )
        )

    async def _mark_cancelled(self, state: SupervisorState) -> SupervisorState:
        return await self._save(
            replace(
                state,
                phase="cancelled",
                status="cancelled",
                last_stop_reason=state.last_stop_reason or "cancelled",
                last_error=state.last_error or "Supervisor cancellation requested",
                next_run_at=None,
                updated_at=self._clock(),
            )
        )

    @staticmethod
    def _read_session_id(agent: AgentPort) -> str:
        session_id = agent.session_id
        if not isinstance(session_id, str) or not session_id:
            raise TypeError("Agent session_id must be a non-empty string")
        return session_id

    @staticmethod
    async def _restore_session(agent: AgentPort, session_id: str) -> bool:
        restored = await agent.restore(session_id)
        if not isinstance(restored, bool):
            raise TypeError("Agent session restore must return bool")
        return restored


__all__ = [
    "AgentFactory",
    "AgentPort",
    "AsyncioScheduler",
    "CheckpointError",
    "CheckpointStore",
    "Goal",
    "JsonCheckpointStore",
    "Phase",
    "PublicAgentEventListener",
    "PublicAgentResult",
    "RetryPolicy",
    "Scheduler",
    "Status",
    "Supervisor",
    "SupervisorResult",
    "SupervisorState",
    "VolatileCheckpointStore",
]
