"""/goal、/loop 与 Auto Mode 的协调层(状态与循环)。

纯提示词与解析函数在 :mod:`lion_code.autonomy`;本模块承载它们的运行时状态与
驱动循环。``AutonomyRuntime`` 经一个窄 ``AutonomyHost`` 协议回调 ``Agent`` 的
``chat``/``_emit_notice`` 与 side-query 工具,自身不持有 Provider
或 TUI,从而把「自主运行」与「Provider 切换/TUI 输出」分离。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from typing import Any, Literal, Protocol, runtime_checkable

from .autonomy import (
    DENIAL_LIMITS,
    GOAL_EVALUATOR_SYSTEM,
    GOAL_MAX_ITERATIONS,
    GOAL_TRANSCRIPT_FRAMING,
    LOOP_MAX_ITERATIONS,
    OFFER_CLOUD_THRESHOLD_SECONDS,
    build_classifier_system,
    build_classifier_transcript,
    clamp_wakeup_delay,
    classifier_user_message,
    dynamic_loop_directive,
    goal_directive,
    goal_judge_user_message,
    is_daily_wording,
    load_auto_mode_rules,
    parse_block_verdict,
    parse_goal_verdict,
    parse_loop_input,
)
from .core.messages import AssistantMessage
from .prompt import load_claude_md
from .tooling.internal import create_wakeup_tool
from .tooling.middleware import is_auto_fast_path
from .tooling.types import JSONValue, ToolResult
from .usage import BudgetPolicy, UsageLedger


@runtime_checkable
class AutonomyHost(Protocol):
    """``AutonomyRuntime`` 依赖的 ``Agent`` 表面(窄协议,非 Service Locator)。

    复杂属性(``tool_registry``/``_core_runtime``/``confirm_fn``)用 ``Any`` 标注,
    只约束本模块实际回调的方法签名。
    """

    confirm_fn: Any
    tool_registry: Any
    _core_runtime: Any

    @property
    def api_configured(self) -> bool: ...

    @property
    def is_aborted(self) -> bool: ...

    def _emit_notice(
        self, message: str, *, role: Literal["info", "error"] = "info"
    ) -> None: ...

    async def chat(self, user_message: str) -> None: ...

    async def _run_evaluator_query(
        self, system: str, messages: list, max_tokens: int = 512
    ) -> str: ...

    async def _run_classifier_query(
        self, system: str, user: str, max_tokens: int
    ) -> str: ...


class AutonomyRuntime:
    """拥有 /goal、/loop 与 Auto Mode 的状态与驱动循环。"""

    def __init__(
        self,
        host: AutonomyHost,
        *,
        usage: UsageLedger,
        budget: BudgetPolicy,
    ) -> None:
        self._host = host
        self._usage = usage
        self._budget = budget
        # /goal 是跨轮次、会话级的 Stop-hook 条件。
        self.active_goal: dict | None = None
        self.goal_stop = False  # 中断时置位,使目标追踪循环尽快退出。
        # 动态 /loop 中,模型调用 schedule_wakeup 后写入;本轮收敛后由驱动器读取并清空。
        self.pending_wakeup: dict | None = None
        self.loop_stop = False  # 中断时置位,使正在运行的 loop 尽快退出。
        # Auto Mode 按 DENIAL_LIMITS 追踪连续和累计拒绝次数。
        self.auto_consecutive_denials = 0
        self.auto_total_denials = 0

    # ─── /goal 追踪 ──────────────────────────────────────────

    def set_goal(self, condition: str) -> str:
        """设置活动目标并返回首轮执行指令。"""
        self.active_goal = {
            "condition": condition,
            "iterations": 0,
            "started_at": time.time(),
            "last_reason": None,
        }
        self._host._emit_notice(f'◎ /goal active - Stop hook condition: "{condition}"')
        return goal_directive(condition)

    def show_goal(self) -> None:
        """处理无参数 `/goal`,显示当前目标状态。"""
        if not self.active_goal:
            self._host._emit_notice("No active goal. Set one with /goal <condition>.")
            return
        secs = time.time() - self.active_goal["started_at"]
        last = (
            f"\n  last reason: {self.active_goal['last_reason']}"
            if self.active_goal["last_reason"]
            else ""
        )
        self._host._emit_notice(
            f"◎ /goal active\n  condition: {self.active_goal['condition']}\n"
            f"  iterations: {self.active_goal['iterations']}\n  elapsed: {secs:.1f}s{last}"
        )

    async def pursue_goal(self, directive: str) -> None:
        """持续执行“运行 -> 评估 -> 反馈未满足原因”,直到目标终止条件出现。"""
        if not self.active_goal:
            return
        self.goal_stop = False
        try:
            await self._host.chat(directive)
            # 先评估刚结束的一轮,再检查上限或决定下一轮,确保最终输出不会漏判。
            while self.active_goal and not self.goal_stop and not self._host.is_aborted:
                verdict = await self._evaluate_goal(self.active_goal["condition"])
                if verdict["ok"]:
                    turns = self.active_goal["iterations"] + 1
                    secs = time.time() - self.active_goal["started_at"]
                    plural = "" if turns == 1 else "s"
                    self._host._emit_notice(
                        f"✓ Goal achieved ({turns} turn{plural}, {secs:.1f}s): {verdict['reason']}"
                    )
                    break
                if verdict.get("impossible"):
                    self._host._emit_notice(
                        f"Hooks: Prompt hook condition judged impossible: {verdict['reason']}"
                    )
                    break

                # 未满足时记录原因,再检查预算和硬上限是否允许继续。
                self.active_goal["iterations"] += 1
                self.active_goal["last_reason"] = verdict["reason"]
                self._host._emit_notice(
                    f"Hooks: Prompt hook condition was not met: {verdict['reason']}"
                )

                decision = self._budget.check(self._usage.snapshot())
                if decision.exceeded:
                    self._host._emit_notice(f"Goal stopped: {decision.reason}")
                    break
                # --max-turns 只统计执行工具的轮次;纯文本目标循环可能永远不触发它,
                # 因此仍需独立的无条件硬上限。
                if self.active_goal["iterations"] >= GOAL_MAX_ITERATIONS:
                    self._host._emit_notice(
                        f"Goal stopped: reached {GOAL_MAX_ITERATIONS} iterations without meeting the condition."
                    )
                    break
                if self.goal_stop or self._host.is_aborted:
                    break

                await self._host.chat(
                    f"Hooks: Prompt hook condition was not met: {verdict['reason']}\n\nKeep working toward the goal."
                )
            if self.goal_stop or self._host.is_aborted:
                self._host._emit_notice("Goal pursuit interrupted.")
        finally:
            # 无论满足、不可能、超限还是中断都清除状态,避免旧目标污染后续对话;
            # 当前实现不支持恢复进行中的 /goal。
            self.active_goal = None

    async def _evaluate_goal(self, condition: str) -> dict:
        """评估刚结束的一轮,并把 transcript 作为独立 assistant 消息发送。

        前置 user 消息明确它只是待判定数据,防止被评估内容夹带伪造的用户或裁判文本。
        """
        transcript = self._extract_last_assistant_text()
        messages = [
            {"role": "user", "content": GOAL_TRANSCRIPT_FRAMING},
            {"role": "assistant", "content": transcript or "(no assistant output)"},
            {"role": "user", "content": goal_judge_user_message(condition)},
        ]
        try:
            raw = await self._host._run_evaluator_query(GOAL_EVALUATOR_SYSTEM, messages)
            return parse_goal_verdict(raw)
        except Exception as e:
            # 评估异常按“未满足”处理,绝不能因故障误清除目标。
            return {"ok": False, "reason": f"evaluator error: {e}", "impossible": False}

    def _extract_last_assistant_text(self) -> str:
        """提取最近一轮 assistant 文本,确保评估目标只覆盖刚完成的动作。"""
        for message in reversed(self._host._core_runtime.messages):
            if isinstance(message, AssistantMessage):
                return message.text
        return ""

    # ─── /loop:定时或自主节奏 ───────────────────────────────

    async def run_loop(self, raw_input: str) -> None:
        """解析 /loop 输入并驱动对应模式;格式错误时直接返回。"""
        spec = parse_loop_input(raw_input)
        if "error" in spec:
            self._host._emit_notice(spec["error"])
            return
        # 长间隔或 daily 措辞在真实客户端会触发持久化云计划建议;教学版没有云端,
        # 这里只显式告知差异,仍在当前进程内运行。
        wants_cloud = (
            spec["mode"] == "interval"
            and spec["interval_seconds"] >= OFFER_CLOUD_THRESHOLD_SECONDS
        ) or is_daily_wording(raw_input)
        if wants_cloud:
            self._host._emit_notice(
                "(Real Claude Code would offer to convert this to a persistent cloud schedule "
                "that keeps running after the session ends. This teaching build has no cloud "
                "backend - continuing in-session.)"
            )

        self.loop_stop = False
        try:
            if spec["mode"] == "interval":
                await self._run_loop_interval(spec)
            else:
                await self._run_loop_dynamic(spec)
        except asyncio.CancelledError:
            self._host._emit_notice("Loop interrupted.")

    async def _run_loop_interval(self, spec: dict) -> None:
        """按固定秒数重复提示词,直到中断、预算或迭代上限。

        这是仅会话内生效的简化计时器,不提供 Cron/KAIROS 的持久化能力。
        """
        self._host._emit_notice(
            f"⟳ /loop scheduled every {spec['interval_label']} (session-only, not persisted - "
            "dies when this process exits). Ctrl+C to stop."
        )
        iterations = 0
        while not self.loop_stop and not self._host.is_aborted:
            iterations += 1
            self._host._emit_notice(f"⟳ loop tick {iterations}")
            await self._host.chat(spec["prompt"])

            decision = self._budget.check(self._usage.snapshot())
            if decision.exceeded:
                self._host._emit_notice(f"Loop stopped: {decision.reason}")
                break
            # 工具轮次计数无法约束纯文本 loop,因此这里同时把 --max-turns 解释为 tick 上限。
            if (
                self._budget.max_turns is not None
                and iterations >= self._budget.max_turns
            ):
                self._host._emit_notice(
                    f"Loop stopped: tick limit reached ({iterations} >= {self._budget.max_turns})."
                )
                break
            if iterations >= LOOP_MAX_ITERATIONS:
                self._host._emit_notice(
                    f"Loop stopped: reached {LOOP_MAX_ITERATIONS} ticks."
                )
                break
            interrupted = await self._interruptible_sleep(spec["interval_seconds"])
            if interrupted:
                self._host._emit_notice("Loop stopped.")
                break

    async def _run_loop_dynamic(self, spec: dict) -> None:
        """让主模型通过 schedule_wakeup 自主安排下一轮。

        有唤醒计划则等待裁剪后的延迟并复用回传提示词;没有计划即视为收敛。动态节奏
        不使用独立评估器,schedule_wakeup 也只在 loop 生命周期内暴露。
        """
        self._host._emit_notice(
            "⟳ /loop dynamic (self-paced) - the model schedules its own next run, or ends the "
            "loop. Ctrl+C to stop."
        )
        prompt = spec["prompt"]
        iterations = 0
        with self._host.tool_registry.temporary_tool(
            create_wakeup_tool(self.schedule_wakeup)
        ):
            try:
                while not self.loop_stop and not self._host.is_aborted:
                    iterations += 1
                    self.pending_wakeup = None
                    await self._host.chat(dynamic_loop_directive(prompt))

                    if not self.pending_wakeup:
                        plural = "" if iterations == 1 else "s"
                        self._host._emit_notice(
                            f"⟳ Loop converged after {iterations} tick{plural} (model scheduled no wakeup)."
                        )
                        break
                    decision = self._budget.check(self._usage.snapshot())
                    if decision.exceeded:
                        self._host._emit_notice(f"Loop stopped: {decision.reason}")
                        break
                    if (
                        self._budget.max_turns is not None
                        and iterations >= self._budget.max_turns
                    ):
                        self._host._emit_notice(
                            f"Loop stopped: tick limit reached ({iterations} >= {self._budget.max_turns})."
                        )
                        break
                    if iterations >= LOOP_MAX_ITERATIONS:
                        self._host._emit_notice(
                            f"Loop stopped: reached {LOOP_MAX_ITERATIONS} ticks."
                        )
                        break
                    delay = self.pending_wakeup["delay_seconds"]
                    self._host._emit_notice(
                        f"⟳ next run in {delay}s - {self.pending_wakeup['reason']}"
                    )
                    prompt = self.pending_wakeup["prompt"] or prompt
                    interrupted = await self._interruptible_sleep(delay)
                    if interrupted:
                        self._host._emit_notice("Loop stopped.")
                        break
            finally:
                self.pending_wakeup = None

    async def schedule_wakeup(
        self,
        arguments: Mapping[str, JSONValue],
    ) -> ToolResult:
        """记录唤醒请求并返回工具结果；状态仍由本运行时持有。"""

        delay = clamp_wakeup_delay(arguments.get("delaySeconds"))
        reason = (
            arguments.get("reason") if isinstance(arguments.get("reason"), str) else ""
        )
        prompt = (
            arguments.get("prompt") if isinstance(arguments.get("prompt"), str) else ""
        )
        self.pending_wakeup = {
            "delay_seconds": delay,
            "reason": reason,
            "prompt": prompt,
        }
        return ToolResult(
            content=(
                f"Wakeup scheduled in {delay}s. The loop will resume then; "
                "end your turn now."
            )
        )

    async def _interruptible_sleep(self, seconds: float) -> bool:
        """分段等待,并在 loop 停止或本轮 abort 时提前返回 True。"""
        import time as _time

        start = _time.time()
        while _time.time() - start < seconds:
            if self.loop_stop or self._host.is_aborted:
                return True
            await asyncio.sleep(min(0.2, seconds))
        return False

    def stop_loop(self) -> None:
        """通知正在运行的 /loop 在最近的检查点停止。"""
        self.loop_stop = True

    def stop_goal(self) -> None:
        """通知 /goal 在下一轮边界停止;正在进行的调用由 abort() 单独取消。"""
        self.goal_stop = True

    # ─── Auto Mode:transcript 分类器权限门 ───────────────────

    async def _classify_tool_call(
        self,
        tool_name: str,
        inp: Mapping[str, JSONValue],
    ) -> dict:
        """以两阶段分类器决定工具调用,返回 allow、deny 或人工 confirm。

        第一阶段是低成本激进门,只要规则可能适用就拦截;若放行则一次调用结束。
        被拦截后第二阶段结合用户意图谨慎复核,其结论为最终结果。
        """
        # 直接调用此兼容方法时也按 Capability 跳过无副作用只读工具;显式 deny 和
        # Plan 硬边界统一由 PermissionMiddleware 在进入分类器前执行。
        try:
            if is_auto_fast_path(self._host.tool_registry.resolve(tool_name)):
                return {"action": "allow"}
        except LookupError:
            pass

        if not self._host.api_configured:
            # 没有可用模型时 fail-closed:交互环境转人工,headless 直接拒绝。
            return self._auto_fallback(
                f"{tool_name} (auto-mode classifier unavailable)"
            )
        try:
            rules = load_auto_mode_rules()
            history = list(self._host._core_runtime.messages)
            if history and isinstance(history[-1], AssistantMessage):
                history.pop()
            transcript = build_classifier_transcript(
                history, {"tool_name": tool_name, "input": inp}
            )
            system = build_classifier_system(rules)
            # CLAUDE.md 是不可信仓库内容,只能放在 user 消息,不能获得 system 权威。
            claude_md = load_claude_md()
            # 第一阶段只需简短 block 结论,因此使用较小 Token 预算。
            s1_raw = await self._host._run_classifier_query(
                system,
                classifier_user_message(
                    rules, transcript, rules["suffix_stage1"], claude_md
                ),
                256,
            )
            s1 = parse_block_verdict(s1_raw)
            if not s1["block"]:
                verdict = s1  # 第一阶段已放行,无需支付第二次模型调用成本。
            else:
                # 第二阶段会权衡用户意图并可能撤销拦截,允许先输出 thinking。
                s2_raw = await self._host._run_classifier_query(
                    system,
                    classifier_user_message(
                        rules, transcript, rules["suffix_stage2"], claude_md
                    ),
                    1024,
                )
                verdict = parse_block_verdict(s2_raw)
        except Exception as e:
            # 配置或分类器异常一律 fail-closed;在这里兜住资源加载错误,避免本轮崩溃
            # 后留下没有配对结果的 tool_use。
            verdict = {"block": True, "reason": f"classifier error: {e}"}

        if not verdict["block"]:
            self.auto_consecutive_denials = 0
            return {"action": "allow"}

        self.auto_consecutive_denials += 1
        self.auto_total_denials += 1
        if (
            self.auto_consecutive_denials >= DENIAL_LIMITS["max_consecutive"]
            or self.auto_total_denials >= DENIAL_LIMITS["max_total"]
        ):
            # 拒绝过多说明分类器可能卡住:交互环境转人工,headless 环境继续拒绝。
            self._host._emit_notice(
                "Auto Mode: denial limit reached - handing back to manual confirmation."
            )
            return self._auto_fallback(f"[Auto Mode blocked] {verdict['reason']}")
        return {"action": "deny", "message": f"[Auto Mode] {verdict['reason']}"}

    def _auto_fallback(self, message: str) -> dict:
        """Auto Mode 的安全降级:能人工确认则询问,否则拒绝,绝不自动放行未判定动作。"""
        if self._host.confirm_fn:
            return {"action": "confirm", "message": message}
        return {"action": "deny", "message": f"{message} (headless - denied)"}
