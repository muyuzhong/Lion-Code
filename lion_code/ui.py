"""终端界面渲染：彩色输出、等待动画及工具调用摘要。

本模块同时承载 Agent 运行时输出与 REPL 自身界面。agent.py 不直接写 stdout，
其输出在注册事件汇（set_sink）后改为发射结构化事件，供 TUI 等替代前端消费；
welcome、用户输入提示和 CLI Plan 选项仍由 REPL 直接渲染。
"""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable

from rich.console import Console

console = Console(highlight=False)

# ─── 事件汇（替代前端接入点）─────────────────────────────────

UIEventSink = Callable[[str, dict], None]
_sink: UIEventSink | None = None


def set_sink(sink: UIEventSink | None) -> UIEventSink | None:
    """注册/清除 Agent 运行时事件汇；REPL 自身界面不进入事件汇。"""
    global _sink
    prev = _sink
    _sink = sink
    return prev


# ─── 基础输出 ───────────────────────────────────────────────


def print_welcome() -> None:
    console.print("\n  [bold cyan]Lion Code[/bold cyan][dim] — 一个轻量级编码 Agent[/dim]\n")
    console.print("[dim]  Type your request, or 'exit' to quit.[/dim]")
    console.print("[dim]  Commands: /clear /plan /cost /compact /dream /memory /skills[/dim]\n")


def print_user_prompt() -> None:
    console.print("\n[bold green]> [/bold green]", end="")


def print_assistant_text(text: str) -> None:
    if _sink:
        _sink("text", {"text": text})
        return
    sys.stdout.write(text)
    sys.stdout.flush()


def print_tool_call(name: str, inp: dict) -> None:
    icon = _get_tool_icon(name)
    summary = _get_tool_summary(name, inp)
    if _sink:
        _sink("tool_call", {"name": name, "icon": icon, "summary": summary})
        return
    console.print(f"\n  [yellow]{icon} {name}[/yellow][dim] {summary}[/dim]")


def print_tool_result(name: str, result: str) -> None:
    if _sink:
        max_len = 500
        truncated = result
        if len(result) > max_len:
            truncated = result[:max_len] + f"\n... ({len(result)} chars total)"
        _sink("tool_result", {"name": name, "text": truncated})
        return
    if (name in ("edit_file", "write_file")) and not result.startswith("Error"):
        _print_file_change_result(name, result)
        return
    max_len = 500
    truncated = result
    if len(result) > max_len:
        truncated = result[:max_len] + f"\n  ... ({len(result)} chars total)"
    lines = "\n".join("  " + l for l in truncated.split("\n"))
    console.print(f"[dim]{lines}[/dim]")


def _print_file_change_result(_name: str, result: str) -> None:
    lines = result.split("\n")
    console.print(f"[dim]  {lines[0]}[/dim]")

    max_display = 40
    content_lines = lines[1:]
    display_lines = content_lines[:max_display]

    for line in display_lines:
        if not line.strip():
            continue
        if line.startswith("@@"):
            console.print(f"[cyan]  {line}[/cyan]")
        elif line.startswith("- "):
            console.print(f"[red]  {line}[/red]")
        elif line.startswith("+ "):
            console.print(f"[green]  {line}[/green]")
        else:
            console.print(f"[dim]  {line}[/dim]")
    if len(content_lines) > max_display:
        console.print(f"[dim]  ... ({len(content_lines) - max_display} more lines)[/dim]")


def print_error(msg: str) -> None:
    if _sink:
        _sink("error", {"message": msg})
        return
    console.print(f"\n  [red]Error: {msg}[/red]")


def print_confirmation(command: str) -> None:
    if _sink:
        _sink("confirmation", {"command": command})
        return
    console.print(f"\n  [yellow]⚠ Dangerous command:[/yellow] [white]{command}[/white]")


def print_divider() -> None:
    if _sink:
        _sink("divider", {})
        return
    console.print(f"\n[dim]  {'─' * 50}[/dim]")


def print_cost(input_tokens: int, output_tokens: int, cache_read: int = 0, cache_creation: int = 0) -> None:
    # 与 Agent 的费用估算保持同一倍率，避免状态栏和预算检查显示不同金额。
    total = (
        (input_tokens / 1_000_000) * 3
        + (cache_read / 1_000_000) * 0.3
        + (cache_creation / 1_000_000) * 3.75
        + (output_tokens / 1_000_000) * 15
    )
    if _sink:
        _sink("cost", {
            "input": input_tokens,
            "output": output_tokens,
            "cache_read": cache_read,
            "cache_creation": cache_creation,
            "total": total,
        })
        return
    cache_str = f", {cache_read} cached" if cache_read else ""
    console.print(f"\n[dim]  Tokens: {input_tokens} in / {output_tokens} out{cache_str} (~${total:.4f})[/dim]")


def print_retry(attempt: int, max_retries: int, reason: str) -> None:
    if _sink:
        _sink("retry", {"attempt": attempt, "max_retries": max_retries, "reason": reason})
        return
    console.print(f"\n  [yellow]↻ Retry {attempt}/{max_retries}: {reason}[/yellow]")


def print_info(msg: str) -> None:
    if _sink:
        _sink("info", {"message": msg})
        return
    console.print(f"\n  [cyan]ℹ {msg}[/cyan]")


# ─── 等待动画 ───────────────────────────────────────────────

SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

_spinner_thread: threading.Thread | None = None
_spinner_stop = threading.Event()


def start_spinner(label: str = "Thinking") -> None:
    global _spinner_thread
    if _sink:
        _sink("spinner", {"on": True, "label": label})
        return
    if _spinner_thread is not None:
        return
    _spinner_stop.clear()

    def _run() -> None:
        frame = 0
        sys.stdout.write(f"\n  {SPINNER_FRAMES[0]} {label}...")
        sys.stdout.flush()
        while not _spinner_stop.is_set():
            time.sleep(0.08)
            frame = (frame + 1) % len(SPINNER_FRAMES)
            sys.stdout.write(f"\r  {SPINNER_FRAMES[frame]} {label}...")
            sys.stdout.flush()

    _spinner_thread = threading.Thread(target=_run, daemon=True)
    _spinner_thread.start()


def stop_spinner() -> None:
    global _spinner_thread
    if _sink:
        _sink("spinner", {"on": False})
        return
    if _spinner_thread is None:
        return
    _spinner_stop.set()
    _spinner_thread.join(timeout=1)
    _spinner_thread = None
    sys.stdout.write("\r\033[K")
    sys.stdout.flush()


# ─── Plan 审批界面 ──────────────────────────────────────────


def print_plan_for_approval(plan_content: str) -> None:
    console.print("\n  [cyan]━━━ Plan for Approval ━━━[/cyan]")
    lines = plan_content.split("\n")
    max_lines = 60
    for line in lines[:max_lines]:
        console.print(f"  [white]{line}[/white]")
    if len(lines) > max_lines:
        console.print(f"[dim]  ... ({len(lines) - max_lines} more lines)[/dim]")
    console.print("  [cyan]━━━━━━━━━━━━━━━━━━━━━━━━[/cyan]\n")


def print_plan_approval_options() -> None:
    console.print("  [yellow]Choose an option:[/yellow]")
    console.print("    [white]1) Yes, clear context and execute[/white][dim] — fresh start with auto-accept edits[/dim]")
    console.print("    [white]2) Yes, and execute[/white][dim] — keep context, auto-accept edits[/dim]")
    console.print("    [white]3) Yes, manually approve edits[/white][dim] — keep context, confirm each edit[/dim]")
    console.print("    [white]4) No, keep planning[/white][dim] — provide feedback to revise[/dim]")


# ─── 子 Agent 状态 ──────────────────────────────────────────


def print_sub_agent_start(agent_type: str, description: str) -> None:
    if _sink:
        _sink("sub_agent_start", {"agent_type": agent_type, "description": description})
        return
    console.print(f"\n  [magenta]┌─ Sub-agent [{agent_type}]: {description}[/magenta]")


def print_sub_agent_end(agent_type: str, _description: str) -> None:
    if _sink:
        _sink("sub_agent_end", {"agent_type": agent_type})
        return
    console.print(f"  [magenta]└─ Sub-agent [{agent_type}] completed[/magenta]")


# ─── 工具图标与摘要 ─────────────────────────────────────────

_TOOL_ICONS = {
    "read_file": "📖",
    "write_file": "✏️",
    "edit_file": "🔧",
    "list_files": "📁",
    "grep_search": "🔍",
    "run_shell": "💻",
    "skill": "⚡",
    "agent": "🤖",
}


def _get_tool_icon(name: str) -> str:
    return _TOOL_ICONS.get(name, "🔨")


def _get_tool_summary(name: str, inp: dict) -> str:
    if name == "read_file":
        return inp.get("file_path", "")
    if name == "write_file":
        return inp.get("file_path", "")
    if name == "edit_file":
        return inp.get("file_path", "")
    if name == "list_files":
        return inp.get("pattern", "")
    if name == "grep_search":
        return f'"{inp.get("pattern", "")}" in {inp.get("path", ".")}'
    if name == "run_shell":
        cmd = inp.get("command", "")
        return cmd[:60] + "..." if len(cmd) > 60 else cmd
    if name == "skill":
        return inp.get("skill_name", "")
    if name == "agent":
        return f'[{inp.get("type", "general")}] {inp.get("description", "")}'
    return ""
