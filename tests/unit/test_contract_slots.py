"""Unit tests for SlotSpec coherence, EligibilityDecision, and SelectedInputSet hashing."""

from __future__ import annotations

import unittest
from decimal import Decimal

from investment_stack.contracts.errors import (
    SlotCoherenceError,
)
from investment_stack.contracts.slots import (
    BoundSlotInput,
    CalculationPurpose,
    DimensionKind,
    EligibilityDecision,
    EligibilityStatus,
    ExcludedCandidate,
    SelectionRequest,
    SelectedInputSet,
    SlotSpec,
)


class ContractSlotsTests(unittest.TestCase):
    def test_slot_spec_currency_coherence_rules(self) -> None:
        # MONEY without currency must raise SlotCoherenceError
        with self.assertRaises(SlotCoherenceError) as ctx:
            SlotSpec(
                slot_id="s1",
                purpose=CalculationPurpose.CURRENT_PRICE,
                instrument_id="AAPL",
                metric="price",
                dimension=DimensionKind.MONEY,
                currency=None,
            )
        self.assertIn("requires currency", str(ctx.exception))

        # MONEY_PER_SHARE without currency must raise SlotCoherenceError
        with self.assertRaises(SlotCoherenceError):
            SlotSpec(
                slot_id="s2",
                purpose=CalculationPurpose.FINANCIAL_CALC,
                instrument_id="AAPL",
                metric="eps",
                dimension=DimensionKind.MONEY_PER_SHARE,
                currency=None,
            )

        # SHARES with currency must raise SlotCoherenceError
        with self.assertRaises(SlotCoherenceError) as ctx:
            SlotSpec(
                slot_id="s3",
                purpose=CalculationPurpose.FINANCIAL_CALC,
                instrument_id="AAPL",
                metric="shares",
                dimension=DimensionKind.SHARES,
                currency="USD",
            )
        self.assertIn("must not specify currency", str(ctx.exception))

        # Valid MONEY with currency
        valid = SlotSpec(
            slot_id="s4",
            purpose=CalculationPurpose.CURRENT_PRICE,
            instrument_id="AAPL",
            metric="price",
            dimension=DimensionKind.MONEY,
            currency="USD",
        )
        self.assertEqual(valid.currency, "USD")

    def test_slot_spec_period_and_duration_coherence(self) -> None:
        # start > end raises
        with self.assertRaises(SlotCoherenceError):
            SlotSpec(
                slot_id="s1",
                purpose=CalculationPurpose.FINANCIAL_CALC,
                instrument_id="AAPL",
                metric="revenue",
                dimension=DimensionKind.MONEY,
                currency="USD",
                target_period_start="2025-12-31",
                target_period_end="2025-01-01",
            )

        # duration_days <= 0 raises
        with self.assertRaises(SlotCoherenceError):
            SlotSpec(
                slot_id="s2",
                purpose=CalculationPurpose.FINANCIAL_CALC,
                instrument_id="AAPL",
                metric="revenue",
                dimension=DimensionKind.MONEY,
                currency="USD",
                duration_days=0,
            )

    def test_slot_spec_matching_candidate(self) -> None:
        slot = SlotSpec(
            slot_id="slot_rev",
            purpose=CalculationPurpose.FINANCIAL_CALC,
            instrument_id="AAPL",
            metric="revenue",
            dimension=DimensionKind.MONEY,
            currency="USD",
            target_period_end="2025-12-31",
        )
        # Currency & instrument match
        ok, reason = slot.matches_candidate(
            "USD", DimensionKind.MONEY, "2025-12-31", candidate_instrument_id="AAPL"
        )
        self.assertTrue(ok)
        self.assertIsNone(reason)

        # Instrument missing when slot requires instrument_id
        ok, reason = slot.matches_candidate("USD", DimensionKind.MONEY, "2025-12-31")
        self.assertFalse(ok)
        self.assertIn("Instrument missing", str(reason))

        # Instrument mismatch
        ok, reason = slot.matches_candidate(
            "USD", DimensionKind.MONEY, "2025-12-31", candidate_instrument_id="MSFT"
        )
        self.assertFalse(ok)
        self.assertIn("Instrument mismatch", str(reason))

        # Currency mismatch
        ok, reason = slot.matches_candidate(
            "KRW", DimensionKind.MONEY, "2025-12-31", candidate_instrument_id="AAPL"
        )
        self.assertFalse(ok)
        self.assertIn("Currency mismatch", str(reason))

        # Period mismatch
        ok, reason = slot.matches_candidate(
            "USD", DimensionKind.MONEY, "2024-12-31", candidate_instrument_id="AAPL"
        )
        self.assertFalse(ok)
        self.assertIn("Period end mismatch", str(reason))

        # Counterexample 2: Slot requires currency USD, dimension MONEY, period_end 2025-12-31.
        # Candidate with matches_candidate('USD', None, None) must NOT treat None as wildcards!
        ok, reason = slot.matches_candidate("USD", None, None, candidate_instrument_id="AAPL")
        self.assertFalse(ok)
        self.assertIn("Dimension missing", str(reason))

        ok, reason = slot.matches_candidate("USD", DimensionKind.MONEY, None, candidate_instrument_id="AAPL")
        self.assertFalse(ok)
        self.assertIn("Period end missing", str(reason))

    def test_eligibility_decision_factories(self) -> None:
        el = EligibilityDecision.eligible("el-1", "CURRENT_PRICE", "p1", "fp-123")
        self.assertEqual(el.status, EligibilityStatus.ELIGIBLE)
        self.assertEqual(el.reason_codes, ())

        inel = EligibilityDecision.ineligible(
            "el-2",
            "CURRENT_PRICE",
            reason_codes=("STALE_PRICE", "UNVERIFIED_SESSION"),
            reasons=("Price is older than 24h", "Market session not confirmed"),
            policy_version="p1",
            input_fingerprint="fp-456",
        )
        self.assertEqual(inel.status, EligibilityStatus.INELIGIBLE)
        self.assertEqual(len(inel.reason_codes), 2)

    def test_selected_input_set_hash_and_tamper_detection(self) -> None:
        slot_a = BoundSlotInput(
            slot_id="slot_b",  # test sorting
            canonical_value=Decimal("200"),
            canonical_unit="USD",
            canonical_currency="USD",
            evidence_id="ev-2",
        )
        slot_b = BoundSlotInput(
            slot_id="slot_a",
            canonical_value=Decimal("100"),
            canonical_unit="USD",
            canonical_currency="USD",
            evidence_id="ev-1",
        )
        excluded = ExcludedCandidate("c-1", "ev-3", ("STALE",), "Old price")

        snapshot = SelectedInputSet.create(
            run_id="run-1",
            purpose="VALUATION",
            selection_version=1,
            slots=[slot_a, slot_b],
            excluded_candidates=[excluded],
        )
        # Verify slots were sorted by slot_id
        self.assertEqual(snapshot.slots[0].slot_id, "slot_a")
        self.assertEqual(snapshot.slots[1].slot_id, "slot_b")
        self.assertTrue(snapshot.verify_hash())

        # Tampering with snapshot_hash
        tampered = SelectedInputSet(
            run_id=snapshot.run_id,
            purpose=snapshot.purpose,
            selection_version=snapshot.selection_version,
            slots=snapshot.slots,
            excluded_candidates=snapshot.excluded_candidates,
            created_at=snapshot.created_at,
            snapshot_hash="tampered_hash_000000000000000000000000000000000000000000000000000000",
        )
        self.assertFalse(tampered.verify_hash())

        # Tampering with slot value
        tampered_slot = BoundSlotInput(
            slot_id="slot_a",
            canonical_value=Decimal("999"),  # altered value
            canonical_unit="USD",
            canonical_currency="USD",
            evidence_id="ev-1",
        )
        tampered_slots_snapshot = SelectedInputSet(
            run_id=snapshot.run_id,
            purpose=snapshot.purpose,
            selection_version=snapshot.selection_version,
            slots=(tampered_slot, snapshot.slots[1]),
            excluded_candidates=snapshot.excluded_candidates,
            created_at=snapshot.created_at,
            snapshot_hash=snapshot.snapshot_hash,
        )
        self.assertFalse(tampered_slots_snapshot.verify_hash())

    def test_selected_input_set_duplicate_slot_id_rejection(self) -> None:
        slot1 = BoundSlotInput("slot_same", Decimal("10"), "USD", "USD", "ev-1")
        slot2 = BoundSlotInput("slot_same", Decimal("20"), "USD", "USD", "ev-2")
        with self.assertRaises(ValueError) as ctx:
            SelectedInputSet.create("run-1", "PURPOSE", 1, [slot1, slot2])
        self.assertIn("Duplicate slot_id", str(ctx.exception))

    def test_selected_input_set_semantic_hash_permutation_invariance(self) -> None:
        slot1 = BoundSlotInput("slot_1", Decimal("100"), "USD", "USD", "ev-1")
        slot2 = BoundSlotInput("slot_2", Decimal("200"), "USD", "USD", "ev-2")

        snap_a = SelectedInputSet.create("run-1", "PURPOSE", 1, [slot1, slot2])
        snap_b = SelectedInputSet.create("run-1", "PURPOSE", 1, [slot2, slot1])

        # Semantic hash should be invariant to candidate/slot input order
        self.assertEqual(snap_a.semantic_hash(), snap_b.semantic_hash())
        self.assertEqual(snap_a.snapshot_hash, snap_b.snapshot_hash)

    def test_selection_request_compute_hash(self) -> None:
        slot = SlotSpec(
            slot_id="s1",
            purpose=CalculationPurpose.CURRENT_PRICE,
            instrument_id="AAPL",
            metric="price",
            dimension=DimensionKind.MONEY,
            currency="USD",
        )
        req1 = SelectionRequest(
            request_id="req-1",
            purpose=CalculationPurpose.CURRENT_PRICE,
            instrument_id="AAPL",
            slots=(slot,),
        )
        req2 = SelectionRequest(
            request_id="req-1",
            purpose=CalculationPurpose.CURRENT_PRICE,
            instrument_id="AAPL",
            slots=(slot,),
        )
        req3 = SelectionRequest(
            request_id="req-2",
            purpose=CalculationPurpose.CURRENT_PRICE,
            instrument_id="AAPL",
            slots=(slot,),
        )
        self.assertEqual(req1.compute_request_hash(), req2.compute_request_hash())
        self.assertNotEqual(req1.compute_request_hash(), req3.compute_request_hash())

    def test_selected_input_set_active_key_scoping(self) -> None:
        slot = BoundSlotInput("s1", Decimal("100"), "USD", "USD", "ev-1")
        # Purpose only
        snap_p = SelectedInputSet.create("r1", "PRICE", 1, [slot])
        self.assertEqual(snap_p.active_key, "PRICE")

        # Purpose and instrument
        snap_pi = SelectedInputSet.create("r1", "PRICE", 1, [slot], instrument_id="AAPL")
        self.assertEqual(snap_pi.active_key, "PRICE:AAPL")

        # Purpose, instrument, and request_hash
        snap_pir = SelectedInputSet.create(
            "r1", "PRICE", 1, [slot], instrument_id="AAPL", request_hash="h123"
        )
        self.assertEqual(snap_pir.active_key, "PRICE:AAPL:h123")

        # Purpose and request_hash
        snap_pr = SelectedInputSet.create("r1", "PRICE", 1, [slot], request_hash="h123")
        self.assertEqual(snap_pr.active_key, "PRICE:*:h123")


if __name__ == "__main__":
    unittest.main()
