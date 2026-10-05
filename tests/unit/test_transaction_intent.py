from __future__ import annotations

import unittest
from datetime import datetime

from investment_stack.personal.intent import (
    ConfirmationState,
    CostBasisStatus,
    IntentState,
    IntentValidationContext,
    OpeningBalanceKind,
    TransactionIntent,
    TransactionType,
    evaluate_intent,
    resolve_timezone,
    transaction_fingerprint,
)
from investment_stack.personal.interpretation import parse_transaction_request


NOW = datetime(2026, 8, 14, 9, 0)


class TransactionIntentTests(unittest.TestCase):
    def test_transaction_type_closed_set_has_no_correction(self) -> None:
        self.assertEqual(len(TransactionType), 19)
        self.assertNotIn("CORRECTION", {item.value for item in TransactionType})

    def complete_buy(self, **changes: object) -> TransactionIntent:
        values = dict(
            account_id="broker",
            instrument_id="fanuc",
            quantity="2",
            unit_price="6400",
            currency="JPY",
            occurred_at=NOW,
            timezone="Asia/Tokyo",
        )
        values.update(changes)
        return TransactionIntent(TransactionType.BUY, **values)

    def test_complete_buy_is_ready(self) -> None:
        self.assertEqual(evaluate_intent(self.complete_buy()).state, IntentState.READY_TO_POST)

    def test_missing_time_quantity_only_and_ambiguity_require_confirmation(self) -> None:
        cases = (
            self.complete_buy(occurred_at=None),
            self.complete_buy(timezone=None),
            self.complete_buy(unit_price=None, quantity_only=True),
            self.complete_buy(account_ambiguous=True),
            self.complete_buy(instrument_ambiguous=True),
            self.complete_buy(custody_ambiguous=True),
            self.complete_buy(high_impact=True),
            self.complete_buy(net_worth_ambiguous=True),
        )
        for intent in cases:
            with self.subTest(intent=intent):
                self.assertEqual(
                    evaluate_intent(intent).state, IntentState.NEEDS_CONFIRMATION
                )

    def test_always_confirm_types(self) -> None:
        intents = (
            TransactionIntent(
                TransactionType.ASSET_ADJUSTMENT,
                account_id="a",
                instrument_id="i",
                quantity="1",
                unit="SHARE",
                occurred_at=NOW,
                timezone="UTC",
            ),
            TransactionIntent(
                TransactionType.INITIAL_POSITION,
                account_id="a",
                instrument_id="i",
                quantity="1",
                unit="SHARE",
                cost_basis_status=CostBasisStatus.UNAVAILABLE,
                occurred_at=NOW,
                timezone="UTC",
            ),
            TransactionIntent(
                TransactionType.OPENING_BALANCE,
                account_id="a",
                cash_amount="1",
                currency="KRW",
                opening_balance_kind=OpeningBalanceKind.CASH,
                occurred_at=NOW,
                timezone="UTC",
            ),
        )
        for intent in intents:
            self.assertEqual(evaluate_intent(intent).state, IntentState.NEEDS_CONFIRMATION)
            confirmed = TransactionIntent(
                intent.transaction_type,
                **{
                    field: getattr(intent, field)
                    for field in intent.__dataclass_fields__
                    if field not in {"transaction_type", "intent_id", "confirmation_state"}
                },
                confirmation_state=ConfirmationState.CONFIRMED,
            )
            self.assertEqual(evaluate_intent(confirmed).state, IntentState.READY_TO_POST)

    def test_in_kind_transfer_is_unsupported(self) -> None:
        intent = TransactionIntent(TransactionType.TRANSFER, in_kind_transfer=True)
        self.assertEqual(evaluate_intent(intent).state, IntentState.UNSUPPORTED)

    def test_invalid_timezone_and_binary_float_are_rejected(self) -> None:
        self.assertEqual(
            evaluate_intent(self.complete_buy(timezone="Mars/Olympus")).state,
            IntentState.NEEDS_CONFIRMATION,
        )
        with self.assertRaisesRegex(Exception, "binary float"):
            self.complete_buy(quantity=0.1)

    def test_timezone_fallback_is_explicit_context_not_current_time(self) -> None:
        decision = evaluate_intent(
            self.complete_buy(timezone=None),
            context=IntentValidationContext(account_timezone="Asia/Tokyo"),
        )
        self.assertEqual(decision.state, IntentState.READY_TO_POST)
        self.assertEqual(decision.intent.timezone, "Asia/Tokyo")

    def test_parser_never_fabricates_missing_time_or_price(self) -> None:
        intent = parse_transaction_request(
            "FANUC 2주 샀어", account_id="a", instrument_id="fanuc", currency="JPY"
        )
        self.assertTrue(intent.quantity_only)
        self.assertIsNone(intent.occurred_at)
        self.assertIsNone(intent.unit_price)
        self.assertEqual(evaluate_intent(intent).state, IntentState.NEEDS_CONFIRMATION)

    def test_fingerprint_uses_canonical_timezone_and_decimals(self) -> None:
        explicit = self.complete_buy(timezone="Asia/Tokyo", quantity="10")
        fallback = resolve_timezone(
            self.complete_buy(timezone=None, quantity="10.00"),
            IntentValidationContext(account_timezone="Asia/Tokyo"),
        )
        self.assertEqual(transaction_fingerprint(explicit), transaction_fingerprint(fallback))
        self.assertEqual(
            transaction_fingerprint(self.complete_buy(quantity="10")),
            transaction_fingerprint(self.complete_buy(quantity="10.0")),
        )
        self.assertEqual(
            transaction_fingerprint(self.complete_buy(quantity="10.0")),
            transaction_fingerprint(self.complete_buy(quantity="10.00")),
        )
        self.assertNotEqual(
            transaction_fingerprint(self.complete_buy(occurred_at=NOW)),
            transaction_fingerprint(self.complete_buy(occurred_at=datetime(2026, 1, 1, 9, 0))),
        )


if __name__ == "__main__":
    unittest.main()
