"""Slash 命令注册表(vendored 自 tau_coding/commands.py 的结构部分)。

阶段 2 只迁入数据结构与注册/解析/执行骨架;Lion 内置命令集
(/clear /plan /cost /compact /model …)按迁移计划在阶段 3 注册。
``CommandResult`` 保留 Tau 的完整意图标志集,便于 app.py 的命令分发
原样迁入;Lion 不使用的标志(如 login/logout)恒为默认值。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from lion_code.core.tools import AgentTool

from .prompt_templates import PromptTemplate
from .resources import ResourceDiagnostic
from .skills import Skill


class CommandSession(Protocol):
    """Session attributes available to slash-command handlers.

    与 Tau 的差异:去掉 session_manager/available_providers 等尚未在
    Lion 落地的成员,阶段 3/4 随 LionCodingSession 扩展补齐。
    """

    @property
    def cwd(self) -> Path: ...

    @property
    def model(self) -> str: ...

    @property
    def provider_name(self) -> str: ...

    @property
    def available_models(self) -> Sequence[str]: ...

    @property
    def tools(self) -> Sequence[AgentTool]: ...

    @property
    def skills(self) -> Sequence[Skill]: ...

    @property
    def prompt_templates(self) -> Sequence[PromptTemplate]: ...

    @property
    def context_token_estimate(self) -> int: ...

    @property
    def context_window_tokens(self) -> int: ...

    @property
    def thinking_level(self) -> str: ...

    @property
    def available_thinking_levels(self) -> Sequence[str]: ...

    @property
    def resource_diagnostics(self) -> Sequence[ResourceDiagnostic]: ...

    @property
    def system_prompt(self) -> str: ...

    @property
    def session_id(self) -> str | None: ...

    def set_model(self, model: str) -> None: ...

    def set_thinking_level(self, level: str) -> str: ...

    def cycle_thinking_level(self) -> str: ...


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Result of handling a coding-session slash command."""

    handled: bool
    exit_requested: bool = False
    clear_requested: bool = False
    reload_requested: bool = False
    new_session_requested: bool = False
    compact_summary: str | None = None
    export_requested: bool = False
    export_destination: Path | None = None
    export_format: str | None = None
    resume_session_id: str | None = None
    resume_picker_requested: bool = False
    prompts_picker_requested: bool = False
    tree_picker_requested: bool = False
    login_picker_requested: bool = False
    custom_provider_login_requested: bool = False
    login_provider: str | None = None
    login_method: str | None = None
    logout_picker_requested: bool = False
    logout_provider: str | None = None
    model_picker_requested: bool = False
    tools_picker_requested: bool = False
    scoped_models_picker_requested: bool = False
    skills_picker_requested: bool = False
    theme_picker_requested: bool = False
    thinking_level: str | None = None
    theme: str | None = None
    message: str | None = None
    # Lion 增补:Plan 模式切换与费用显示是 Lion 特有交互,Tau 无对应。
    plan_toggle_requested: bool = False
    cost_requested: bool = False
    task_action: str | None = None
    task_text: str | None = None
    session_memory_requested: bool = False
    handoff_requested: bool = False
    dream_requested: bool = False
    skills_list_requested: bool = False
    skill_prompt: str | None = None


@dataclass(frozen=True, slots=True)
class CommandContext:
    """Runtime context passed to slash-command handlers."""

    session: CommandSession
    registry: CommandRegistry
    text: str
    name: str
    args: str


CommandHandler = Callable[[CommandContext], CommandResult]


@dataclass(frozen=True, slots=True)
class SlashCommand:
    """A registered slash command and its user-facing metadata."""

    name: str
    description: str
    usage: str
    handler: CommandHandler
    aliases: tuple[str, ...] = ()
    search_terms: tuple[str, ...] = ()


class CommandRegistry:
    """Parse, register, list, and execute slash commands."""

    def __init__(self) -> None:
        self._commands: dict[str, SlashCommand] = {}
        self._aliases: dict[str, str] = {}

    def register(self, command: SlashCommand) -> None:
        """Register a slash command and its aliases."""
        name = _normalize_name(command.name)
        if name in self._commands:
            raise ValueError(f"Duplicate slash command: /{name}")
        self._commands[name] = command
        for alias in command.aliases:
            normalized_alias = _normalize_name(alias)
            if normalized_alias in self._commands or normalized_alias in self._aliases:
                raise ValueError(f"Duplicate slash command alias: /{normalized_alias}")
            self._aliases[normalized_alias] = name

    def get(self, name: str) -> SlashCommand | None:
        """Return a command by name or alias."""
        normalized = _normalize_name(name)
        command_name = self._aliases.get(normalized, normalized)
        return self._commands.get(command_name)

    def list_commands(self) -> tuple[SlashCommand, ...]:
        """Return registered commands sorted by name."""
        return tuple(self._commands[name] for name in sorted(self._commands))

    def execute(self, session: CommandSession, text: str) -> CommandResult:
        """Execute a slash command, or return unhandled for ordinary prompts."""
        stripped = text.strip()
        if not stripped.startswith("/"):
            return CommandResult(handled=False)

        name, args = _parse_command(stripped)
        if not name:
            return CommandResult(handled=False)

        command = self.get(name)
        if command is None:
            return _try_skill_fallback(name, args)

        return command.handler(
            CommandContext(session=session, registry=self, text=stripped, name=name, args=args)
        )


def _model_command(ctx: CommandContext) -> CommandResult:
    """带参数直接切模型;无参数交给前端开 picker。"""
    if ctx.args:
        ctx.session.set_model(ctx.args)
        return CommandResult(handled=True, message=f"Model set: {ctx.args}")
    return CommandResult(handled=True, model_picker_requested=True)


def _thinking_command(ctx: CommandContext) -> CommandResult:
    """带参数设定 thinking 档位;无参数循环到下一档。"""
    if ctx.args:
        level = ctx.session.set_thinking_level(ctx.args)
    else:
        level = ctx.session.cycle_thinking_level()
    return CommandResult(handled=True, thinking_level=level, message=f"Thinking: {level}")


def _task_command(ctx: CommandContext) -> CommandResult:
    """仅解析活动任务操作，实际读写由应用会话层执行。"""

    if not ctx.args:
        return CommandResult(handled=True, task_action="show")
    action, _, task = ctx.args.partition(" ")
    action = action.lower()
    if action == "switch" and task.strip():
        return CommandResult(
            handled=True,
            task_action="switch",
            task_text=task.strip(),
        )
    if action == "done" and not task.strip():
        return CommandResult(handled=True, task_action="done")
    return CommandResult(
        handled=True,
        message="Usage: /task | /task switch <text> | /task done",
    )


def _try_skill_fallback(name: str, args: str) -> CommandResult:
    """未命中内置命令时，按 ``/<skill-name> [args]`` 尝试解析用户可调用 Skill。

    与 REPL ``__main__.py`` 的 fallback 逻辑一致：
    - ``inline`` Skill 直接把解析后的提示词交给 ``agent.chat``；
    - ``fork`` Skill 改用 skill 工具调用入口。
    """

    from lion_code.skills import execute_skill, get_skill_by_name, resolve_skill_prompt

    skill = get_skill_by_name(name)
    if skill is None or not skill.user_invocable:
        return CommandResult(handled=False)
    if skill.context == "fork":
        result = execute_skill(skill.name, args)
        if result is None:
            return CommandResult(handled=False)
        prompt = (
            f'Use the skill tool to invoke "{skill.name}" with args: '
            f'{args or "(none)"}'
        )
    else:
        prompt = resolve_skill_prompt(skill, args)
    return CommandResult(handled=True, skill_prompt=prompt)


def _skills_command(_ctx: CommandContext) -> CommandResult:
    """/skills 列出可用 Skill。"""

    return CommandResult(handled=True, skills_list_requested=True)


def create_default_command_registry() -> CommandRegistry:
    """注册 Lion 内置 TUI 命令;全部以 CommandResult 意图返回,由前端执行。"""
    registry = CommandRegistry()
    for command in (
        SlashCommand(
            name="quit",
            description="退出 Lion Code",
            usage="/quit",
            handler=lambda _ctx: CommandResult(handled=True, exit_requested=True),
            aliases=("exit",),
        ),
        SlashCommand(
            name="clear",
            description="清空对话并开始新会话",
            usage="/clear",
            handler=lambda _ctx: CommandResult(handled=True, new_session_requested=True),
            aliases=("new",),
        ),
        SlashCommand(
            name="plan",
            description="切换 Plan 模式",
            usage="/plan",
            handler=lambda _ctx: CommandResult(handled=True, plan_toggle_requested=True),
        ),
        SlashCommand(
            name="cost",
            description="显示本会话用量与费用",
            usage="/cost",
            handler=lambda _ctx: CommandResult(handled=True, cost_requested=True),
        ),
        SlashCommand(
            name="compact",
            description="压缩当前上下文",
            usage="/compact",
            handler=lambda ctx: CommandResult(handled=True, compact_summary=ctx.args),
        ),
        SlashCommand(
            name="task",
            description="查看、切换或结束当前项目任务",
            usage="/task [switch <text>|done]",
            handler=_task_command,
        ),
        SlashCommand(
            name="session-memory",
            description="查看当前项目的 Session Memory",
            usage="/session-memory",
            handler=lambda _ctx: CommandResult(
                handled=True,
                session_memory_requested=True,
            ),
        ),
        SlashCommand(
            name="handoff",
            description="保存当前项目的交接摘要",
            usage="/handoff",
            handler=lambda _ctx: CommandResult(handled=True, handoff_requested=True),
        ),
        SlashCommand(
            name="dream",
            description="整理受限的 Auto Memory 候选",
            usage="/dream",
            handler=lambda _ctx: CommandResult(handled=True, dream_requested=True),
        ),
        SlashCommand(
            name="skills",
            description="列出可用 Skill",
            usage="/skills",
            handler=_skills_command,
        ),
        SlashCommand(
            name="model",
            description="切换模型 / 配置 API",
            usage="/model [name]",
            handler=_model_command,
        ),
        SlashCommand(
            name="thinking",
            description="切换 thinking 档位",
            usage="/thinking [off|minimal|low|medium|high|xhigh]",
            handler=_thinking_command,
        ),
        SlashCommand(
            name="resume",
            description="恢复历史会话",
            usage="/resume [session-id]",
            handler=lambda ctx: (
                CommandResult(handled=True, resume_session_id=ctx.args)
                if ctx.args
                else CommandResult(handled=True, resume_picker_requested=True)
            ),
        ),
        SlashCommand(
            name="theme",
            description="切换 TUI 主题",
            usage="/theme <name>",
            handler=lambda ctx: (
                CommandResult(handled=True, theme=ctx.args)
                if ctx.args
                else CommandResult(handled=True, theme_picker_requested=True)
            ),
        ),
    ):
        registry.register(command)
    return registry


def _parse_command(text: str) -> tuple[str, str]:
    command, separator, args = text[1:].partition(" ")
    return _normalize_name(command), args.strip() if separator else ""


def _normalize_name(name: str) -> str:
    return name.strip().removeprefix("/").lower()
