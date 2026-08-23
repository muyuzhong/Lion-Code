"""Lion Code 的 CLI 与交互式 REPL 入口。"""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys

from .adapters.coding_session_backend import CodingSessionBackendAdapter
from .application.commands import CommandResult
from .application.session import LionCodingSession
from .capabilities.skill.discovery import discover_skills
from .composition.full_product import build_full_coding_backend
from .config import resolve_api_credentials
from .permission_state import PermissionMode
from .ui import (
    print_error,
    print_info,
    print_plan_approval_options,
    print_plan_for_approval,
    print_user_prompt,
    print_welcome,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="lion-code",
        description="Lion Code：一个轻量级编码 Agent",
        add_help=False,
    )
    parser.add_argument("prompt", nargs="*", help="One-shot prompt")
    parser.add_argument("--yolo", "-y", action="store_true", help="Skip all confirmation prompts")
    parser.add_argument("--plan", action="store_true", help="Start in Plan mode: read-only planning phase")
    parser.add_argument("--accept-edits", action="store_true", help="Auto-approve file edits")
    parser.add_argument("--dont-ask", action="store_true", help="Auto-deny confirmations (for CI)")
    parser.add_argument("--thinking", action="store_true", help="Enable extended thinking")
    parser.add_argument("--model", "-m", default=None, help="Model to use")
    parser.add_argument("--api-base", default=None, help="OpenAI-compatible API base URL")
    parser.add_argument("--resume", action="store_true", help="Resume last session")
    parser.add_argument("--repl", action="store_true", help="Use the plain REPL instead of the default TUI")
    parser.add_argument("--max-cost", type=float, default=None, help="Max USD spend")
    parser.add_argument("--max-turns", type=int, default=None, help="Max agentic turns")
    parser.add_argument("--web", action="store_true", help="Launch Web server mode")
    parser.add_argument("--port", type=int, default=8000, help="Web server port (default: 8000)")
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Headless Web health check only; do not deliver a control capability",
    )
    parser.add_argument("--help", "-h", action="store_true", help="Show help")
    return parser.parse_args()


def _resolve_permission_mode(args: argparse.Namespace) -> PermissionMode:
    if args.yolo:
        return "bypassPermissions"
    if args.accept_edits:
        return "acceptEdits"
    if args.dont_ask:
        return "dontAsk"
    return "default"


def _print_repl_skills() -> None:
    """REPL 的 /skills 展示：与 TUI 共享 skills 发现，只做终端呈现。"""

    skills = discover_skills()
    if not skills:
        print_info("No skills found. Add skills to .claude/skills/<name>/SKILL.md")
        return
    print_info(f"{len(skills)} skills:")
    for s in skills:
        tag = f"/{s.name}" if s.user_invocable else s.name
        print(f"    {tag} ({s.source}) — {s.description}")


async def _dispatch_repl_command(
    backend: CodingSessionBackendAdapter, result: CommandResult
) -> bool:
    """按 ``CommandResult`` 意图分发 REPL 命令；返回 True 表示退出。

    单一命令入口在 ``application/commands.py``，REPL 只做呈现
    （runtime-boundaries.md 禁止 REPL 自建第二套分发器）。
    """

    if not result.handled:
        print_info(
            "未知命令 — 可用: /model /clear /plan /cost /compact "
            "/skills /thinking /resume /quit"
        )
        return False
    if result.exit_requested:
        print("\nBye!\n")
        return True
    if result.new_session_requested:
        await backend.clear_history()
    elif result.plan_toggle_requested:
        print_info(f"Plan mode: {backend.toggle_plan_mode()}")
    elif result.cost_requested:
        backend.show_cost()
    elif result.compact_summary is not None:
        try:
            await backend.compact()
        except Exception as e:
            print_error(str(e))
    elif result.skill_prompt is not None:
        try:
            await backend.chat(result.skill_prompt)
        except Exception as e:
            if "abort" not in str(e).lower():
                print_error(str(e))
    elif result.skills_list_requested:
        _print_repl_skills()
    elif result.model_picker_requested:
        print_info("Usage: /model <name>")
    elif result.resume_session_id is not None or result.resume_picker_requested:
        print_info("REPL 不支持 /resume；请用 --resume 启动")
    elif result.theme is not None or result.theme_picker_requested:
        print_info("主题仅 TUI 可用")
    elif result.message:
        print_info(result.message)
    return False


async def run_repl(backend: CodingSessionBackendAdapter) -> None:
    """运行交互式 REPL，并负责中断、审批和命令分发。"""

    async def confirm_fn(message: str) -> bool:
        try:
            answer = input("  Allow? (y/n): ")
            return answer.lower().startswith("y")
        except EOFError:
            return False

    backend.set_confirm_fn(confirm_fn)

    async def plan_approval_fn(plan_content: str) -> dict:
        print_plan_for_approval(plan_content)
        print_plan_approval_options()
        while True:
            try:
                choice = input("  Enter choice (1-4): ").strip()
            except EOFError:
                return {"choice": "manual-execute"}
            if choice == "1":
                return {"choice": "clear-and-execute"}
            elif choice == "2":
                return {"choice": "execute"}
            elif choice == "3":
                return {"choice": "manual-execute"}
            elif choice == "4":
                try:
                    feedback = input("  Feedback (what to change): ").strip()
                except EOFError:
                    feedback = ""
                return {"choice": "keep-planning", "feedback": feedback or None}
            else:
                print("  Invalid choice. Enter 1, 2, 3, or 4.")

    backend.set_plan_approval_fn(plan_approval_fn)
    command_session = LionCodingSession(backend=backend, terminal_output=True)

    sigint_count = 0

    def handle_sigint(sig, frame):
        nonlocal sigint_count
        # `is_processing` 才表示主 Agent 是否有活动任务；`_output_buffer` 只服务于
        # 子 Agent，不能用它判断主 Agent 是否可中断。
        if not backend.is_aborted and backend.is_processing:
            backend.abort()
            print("\n  (interrupted)")
            sigint_count = 0
            print_user_prompt()
        else:
            sigint_count += 1
            if sigint_count >= 2:
                print("\nBye!\n")
                sys.exit(0)
            print("\n  Press Ctrl+C again to exit.")
            print_user_prompt()

    signal.signal(signal.SIGINT, handle_sigint)
    print_welcome()

    while True:
        print_user_prompt()
        try:
            line = input()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!\n")
            break

        inp = line.strip()
        sigint_count = 0

        if not inp:
            continue
        if inp in ("exit", "quit"):
            print("\nBye!\n")
            break

        if inp.startswith("/"):
            result = command_session.handle_command(inp)
            if await _dispatch_repl_command(backend, result):
                break
            continue

        # 其余输入进入普通对话路径。
        try:
            await backend.chat(inp)
        except Exception as e:
            if "abort" not in str(e).lower():
                print_error(str(e))

    # REPL 退出时必须回收 Capability 外部资源，否则终端进程可能无法正常结束（issue #8）。
    await backend.close()


def main() -> None:
    args = parse_args()

    if args.help:
        print("""
Usage: lion-code [options] [prompt]

Options:
  --yolo, -y          Skip all confirmation prompts (bypassPermissions mode)
  --plan              Start in Plan mode: read-only planning phase
  --accept-edits      Auto-approve file edits, still confirm dangerous shell
  --dont-ask          Auto-deny anything needing confirmation (for CI)
  --thinking          Enable extended thinking for supported models
  --model, -m         Model to use (default: claude-opus-4-6, or LION_CODE_MODEL env)
  --api-base URL      Use OpenAI-compatible API endpoint (key via env var)
  --resume            Resume the last session
  --repl              Plain REPL instead of the default TUI
  --max-cost USD      Stop when estimated cost exceeds this amount
  --max-turns N       Stop after N agentic turns
  --web               Launch the loopback-only Web server
  --port N            Web server port (default: 8000)
  --no-browser        Headless health check only; no control capability is delivered
  --help, -h          Show this help

REPL commands:
  /clear              Clear conversation history
  /plan               Toggle plan mode (read-only <-> normal)
  /cost               Show token usage and cost
  /compact            Manually compact conversation
  /skills             List available skills
  /<skill-name>       Invoke a skill (e.g. /commit "fix types")

Examples:
  lion-code "修复 src/app.py 中的 bug"
  lion-code --yolo "运行测试并修复失败项"
  lion-code --plan "如何重构这个模块？"
  lion-code --max-cost 0.50 --max-turns 20 "实现功能 X"
  OPENAI_API_KEY=sk-xxx lion-code --api-base https://aihubmix.com/v1 --model gpt-4o "hello"
  lion-code --resume
  lion-code  # 启动 TUI（可先在界面内用 /model 配置 API）
""")
        sys.exit(0)

    permission_mode = _resolve_permission_mode(args)
    model = args.model or os.environ.get("LION_CODE_MODEL", "claude-opus-4-6")

    creds = resolve_api_credentials()
    resolved_api_key = creds["api_key"]
    resolved_api_base = args.api_base or creds["api_base"]
    resolved_use_openai = bool(args.api_base) or creds["use_openai"]
    if not args.model and creds["model"]:
        model = creds["model"]

    prompt = " ".join(args.prompt) if args.prompt else None
    use_web = args.web
    use_tui = not prompt and not args.repl and not use_web

    if use_tui or use_web:
        # 完全未配置凭证时使用 OpenAI-compatible 占位端点，
        # 由 TUI 或 Web 端承载 /model 首跑配置。
        if not resolved_api_key and not resolved_use_openai:
            resolved_use_openai = True
            resolved_api_base = resolved_api_base or "https://api.openai.com/v1"

    # TUI 与 Web 模式允许无凭证启动（进入后在界面配置）；one-shot 与 REPL 仍需预先配置。
    if not resolved_api_key and not use_tui and not use_web:
        print_error(
            "API key is required.\n"
            "  Set ANTHROPIC_API_KEY (+ optional ANTHROPIC_BASE_URL) for Anthropic format,\n"
            "  or OPENAI_API_KEY + OPENAI_BASE_URL for OpenAI-compatible format."
        )
        sys.exit(1)

    backend = build_full_coding_backend(
        permission_mode=permission_mode,
        model=model,
        thinking=args.thinking,
        max_cost_usd=args.max_cost,
        max_turns=args.max_turns,
        api_base=resolved_api_base if resolved_use_openai else None,
        anthropic_base_url=resolved_api_base if not resolved_use_openai else None,
        api_key=resolved_api_key,
    )
    if args.plan:
        # Plan 激活是 Plan Capability 命令（PR4 起 Permission 不再有 plan 模式）。
        backend.toggle_plan_mode()

    if use_web:
        from .application.session import LionCodingSession
        from .server.app import run_server

        session = LionCodingSession(backend=backend, terminal_output=False)
        if args.resume:
            asyncio.run(session.restore_latest())
        run_server(
            session=session,
            port=args.port,
            open_browser=not args.no_browser,
        )
        return

    if use_tui:
        # TUI 内自带输入循环，one-shot prompt 不适用。
        from .application.session import LionCodingSession
        from .tui.app import run_tui_app

        run_tui_app(LionCodingSession(backend=backend), resume=args.resume)
        return

    async def run_cli() -> None:
        if args.resume:
            await backend.restore_latest()
        if prompt:
            try:
                await backend.chat(prompt)
            finally:
                await backend.close()
            return
        await run_repl(backend)

    try:
        asyncio.run(run_cli())
    except Exception as e:
        print_error(str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
