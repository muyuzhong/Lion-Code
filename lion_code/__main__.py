"""Lion Code 的 CLI 与交互式 REPL 入口。"""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys

from .agent import Agent
from .application.session import LionCodingSession
from .config import load_api_config
from .permission_state import PermissionMode
from .skills import (
    discover_skills,
    execute_skill,
    get_skill_by_name,
    resolve_skill_prompt,
)
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


async def run_repl(agent: Agent) -> None:
    """运行交互式 REPL，并负责中断、审批和命令分发。"""

    async def confirm_fn(message: str) -> bool:
        try:
            answer = input("  Allow? (y/n): ")
            return answer.lower().startswith("y")
        except EOFError:
            return False

    agent.set_confirm_fn(confirm_fn)

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

    agent.set_plan_approval_fn(plan_approval_fn)
    command_session = LionCodingSession(backend=agent, terminal_output=True)

    sigint_count = 0

    def handle_sigint(sig, frame):
        nonlocal sigint_count
        # `is_processing` 才表示主 Agent 是否有活动任务；`_output_buffer` 只服务于
        # 子 Agent，不能用它判断主 Agent 是否可中断。
        if not agent.is_aborted and agent.is_processing:
            agent.abort()
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
            command_session.handle_command(inp)

        # 内置 REPL 命令在普通对话前分发，避免被误送给模型。
        if inp == "/clear":
            await agent.clear_history()
            continue
        if inp == "/plan":
            agent.toggle_plan_mode()
            continue
        if inp == "/cost":
            agent.show_cost()
            continue
        if inp == "/compact":
            try:
                await agent.compact()
            except Exception as e:
                print_error(str(e))
            continue
        if inp == "/skills":
            skills = discover_skills()
            if not skills:
                print_info("No skills found. Add skills to .claude/skills/<name>/SKILL.md")
            else:
                print_info(f"{len(skills)} skills:")
                for s in skills:
                    tag = f"/{s.name}" if s.user_invocable else s.name
                    print(f"    {tag} ({s.source}) — {s.description}")
            continue

        # 非内置的斜杠命令按 `/<skill-name> [args]` 尝试解析。
        if inp.startswith("/"):
            space_idx = inp.find(" ")
            cmd_name = inp[1:space_idx] if space_idx > 0 else inp[1:]
            cmd_args = inp[space_idx + 1:] if space_idx > 0 else ""
            skill = get_skill_by_name(cmd_name)
            if skill and skill.user_invocable:
                print_info(f"Invoking skill: {skill.name}")
                try:
                    if skill.context == "fork":
                        result = execute_skill(skill.name, cmd_args)
                        if result:
                            await agent.chat(f'Use the skill tool to invoke "{skill.name}" with args: {cmd_args or "(none)"}')
                    else:
                        resolved = resolve_skill_prompt(skill, cmd_args)
                        await agent.chat(resolved)
                except Exception as e:
                    if "abort" not in str(e).lower():
                        print_error(str(e))
                continue

        # 其余输入进入普通对话路径。
        try:
            await agent.chat(inp)
        except Exception as e:
            if "abort" not in str(e).lower():
                print_error(str(e))

    # REPL 退出时必须回收 Capability 外部资源，否则终端进程可能无法正常结束（issue #8）。
    await agent.close()


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
    api_base = args.api_base

    # 显式参数优先于环境变量；API Key 的类型同时决定使用哪种协议后端。
    resolved_api_base = api_base
    resolved_api_key: str | None = None
    resolved_use_openai = bool(api_base)

    if os.environ.get("OPENAI_API_KEY") and os.environ.get("OPENAI_BASE_URL"):
        resolved_api_key = os.environ["OPENAI_API_KEY"]
        resolved_api_base = resolved_api_base or os.environ.get("OPENAI_BASE_URL")
        resolved_use_openai = True
    elif os.environ.get("ANTHROPIC_API_KEY"):
        resolved_api_key = os.environ["ANTHROPIC_API_KEY"]
        resolved_api_base = resolved_api_base or os.environ.get("ANTHROPIC_BASE_URL")
        resolved_use_openai = False
    elif os.environ.get("OPENAI_API_KEY"):
        resolved_api_key = os.environ["OPENAI_API_KEY"]
        resolved_api_base = resolved_api_base or os.environ.get("OPENAI_BASE_URL")
        resolved_use_openai = True

    if not resolved_api_key and api_base:
        resolved_api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
        resolved_use_openai = True

    # 三级回退：CLI 参数 > 环境变量 > /model 保存的配置。
    if not resolved_api_key:
        saved = load_api_config()
        if saved.get("api_key"):
            resolved_api_key = saved["api_key"]
            resolved_use_openai = saved.get("provider") == "openai"
            resolved_api_base = saved.get("base_url") or None
            if not args.model and saved.get("model"):
                model = saved["model"]

    prompt = " ".join(args.prompt) if args.prompt else None
    use_tui = not prompt and not args.repl

    if use_tui:
        # 完全未配置凭证时使用 OpenAI-compatible 占位端点，
        # 由新 TUI 承载 /model 首跑配置。
        if not resolved_api_key and not resolved_use_openai:
            resolved_use_openai = True
            resolved_api_base = resolved_api_base or "https://api.openai.com/v1"

    # TUI 允许无凭证启动（进入后用 /model 配置）；one-shot 与 REPL 仍需预先配置。
    if not resolved_api_key and not use_tui:
        print_error(
            "API key is required.\n"
            "  Set ANTHROPIC_API_KEY (+ optional ANTHROPIC_BASE_URL) for Anthropic format,\n"
            "  or OPENAI_API_KEY + OPENAI_BASE_URL for OpenAI-compatible format."
        )
        sys.exit(1)

    agent = Agent(
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
        agent.toggle_plan_mode()

    if use_tui:
        # TUI 内自带输入循环，one-shot prompt 不适用。
        from .application.session import LionCodingSession
        from .tui.app import run_tui_app

        run_tui_app(LionCodingSession(backend=agent), resume=args.resume)
        return

    async def run_cli() -> None:
        if args.resume:
            await agent.restore_latest_session()
        if prompt:
            try:
                await agent.chat(prompt)
            finally:
                await agent.close()
            return
        await run_repl(agent)

    try:
        asyncio.run(run_cli())
    except Exception as e:
        print_error(str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
