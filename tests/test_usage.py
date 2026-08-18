"""UsageLedger、UsageSnapshot 与 BudgetPolicy 的领域契约。"""

from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError

from lion_code.core import Usage, UsageCost
from lion_code.usage import BudgetPolicy, UsageLedger


class TestUsageLedger(unittest.TestCase):
    def test_model_usage_accumulates_tokens_cost_and_latest_context(self) -> None:
        ledger = UsageLedger()
        ledger.record_model_usage(
            Usage(
                input=100,
                output=20,
                cache_read=10,
                cache_write=5,
                reasoning=7,
                total_tokens=135,
                cost=UsageCost(total=0.01),
            ),
            response_at=10.0,
        )
        ledger.record_model_usage(
            Usage(
                input=7,
                output=3,
                cache_read=5,
                cache_write=2,
                reasoning=2,
                cost=UsageCost(total=0.02),
            ),
            response_at=20.0,
        )

        usage = ledger.snapshot()
        self.assertEqual(usage.input_tokens, 107)
        self.assertEqual(usage.output_tokens, 23)
        self.assertEqual(usage.cache_read_tokens, 15)
        self.assertEqual(usage.cache_write_tokens, 7)
        self.assertEqual(usage.responses, 2)
        self.assertEqual(usage.last_prompt_tokens, 17)
        self.assertEqual(usage.last_response_at, 20.0)

    def test_child_usage_is_not_overwritten_by_later_model_usage(self) -> None:
        ledger = UsageLedger()
        ledger.record_model_usage(
            Usage(input=10, output=2, total_tokens=12),
            response_at=1.0,
        )
        ledger.record_turn()
        before_child = ledger.snapshot()

        ledger.record_child_usage(3, 4)
        child = ledger.snapshot()
        ledger.record_model_usage(
            Usage(input=5, output=1, total_tokens=6),
            response_at=2.0,
        )
        final = ledger.snapshot()

        self.assertEqual(child.input_tokens, 13)
        self.assertEqual(child.output_tokens, 6)
        self.assertEqual(child.responses, before_child.responses)
        self.assertEqual(child.turns, before_child.turns)
        self.assertEqual(child.last_prompt_tokens, before_child.last_prompt_tokens)
        self.assertEqual(child.last_response_at, before_child.last_response_at)
        self.assertEqual(final.input_tokens, 18)
        self.assertEqual(final.output_tokens, 7)

    def test_context_reset_only_clears_last_prompt_tokens(self) -> None:
        ledger = UsageLedger()
        ledger.record_model_usage(
            Usage(input=10, output=2, total_tokens=12),
            response_at=3.0,
        )
        ledger.record_turn()

        ledger.reset_context_tracking()

        usage = ledger.snapshot()
        self.assertEqual(usage.last_prompt_tokens, 0)
        self.assertEqual(usage.input_tokens, 10)
        self.assertEqual(usage.output_tokens, 2)
        self.assertEqual(usage.turns, 1)
        self.assertEqual(usage.responses, 1)
        self.assertEqual(usage.last_response_at, 3.0)

    def test_session_reset_clears_all_usage(self) -> None:
        ledger = UsageLedger()
        ledger.record_model_usage(
            Usage(input=10, output=2, reasoning=3, cost=UsageCost(total=0.5)),
            response_at=3.0,
        )
        ledger.record_child_usage(4, 5)
        ledger.record_turn()

        ledger.reset()

        self.assertEqual(ledger.snapshot(), type(ledger.snapshot())())

    def test_snapshot_is_frozen_and_cost_uses_existing_estimate(self) -> None:
        ledger = UsageLedger()
        ledger.record_model_usage(
            Usage(
                input=1_000_000,
                output=1_000_000,
                cache_read=1_000_000,
                cache_write=1_000_000,
            )
        )

        usage = ledger.snapshot()

        self.assertAlmostEqual(usage.cost_usd, 22.05)
        with self.assertRaises(FrozenInstanceError):
            usage.input_tokens = 0  # type: ignore[misc]


class TestBudgetPolicy(unittest.TestCase):
    def test_cost_precedes_turn_limit(self) -> None:
        ledger = UsageLedger()
        ledger.record_child_usage(1_000_000, 0)
        ledger.record_turn()
        policy = BudgetPolicy(max_cost_usd=3.0, max_turns=1)

        decision = policy.check(ledger.snapshot())

        self.assertTrue(decision.exceeded)
        self.assertEqual(decision.kind, "max_cost")
        self.assertEqual(decision.reason, "Cost limit reached ($3.0000 >= $3.0)")

    def test_turn_limit_and_unlimited_decisions(self) -> None:
        ledger = UsageLedger()
        ledger.record_turn()

        turn = BudgetPolicy(max_turns=1).check(ledger.snapshot())
        unlimited = BudgetPolicy().check(ledger.snapshot())

        self.assertEqual(turn.kind, "max_turns")
        self.assertEqual(turn.reason, "Turn limit reached (1 >= 1)")
        self.assertFalse(unlimited.exceeded)
        self.assertIsNone(unlimited.kind)
        self.assertEqual(unlimited.reason, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
