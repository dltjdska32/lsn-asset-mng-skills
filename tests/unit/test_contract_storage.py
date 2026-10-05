"""Unit tests for atomic run.db contract storage, CAS revision control, and history preservation."""

from __future__ import annotations

import copy
import json
import sqlite3
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from datetime import datetime, timezone

from investment_stack.contracts.calculation import (
    CalculationRecord,
    CalculationStatus,
)
from investment_stack.contracts.codec import encode_envelope
from investment_stack.contracts.context import PublicAvailability
from investment_stack.contracts.errors import (
    AmbiguousSnapshotError,
    CorruptedStorageError,
    EvidenceNotFoundError,
    HistoryPreservationError,
    InputIntegrityError,
    PayloadSizeExceededError,
    RevisionConflictError,
    TamperDetectionError,
)
from investment_stack.contracts.market import MarketQuote, QuoteKind
from investment_stack.contracts.slots import (
    BoundSlotInput,
    SelectedInputSet,
)
from investment_stack.contracts.storage import (
    CONTRACT_STORAGE_KEY,
    MAX_PAYLOAD_SIZE_BYTES,
    extract_contract_storage,
)
from investment_stack.evidence.manager import RunDatabaseManager


class ContractStorageTests(unittest.TestCase):
    def _register_quote(
        self,
        evidence_id: str,
        price: str | Decimal,
        instrument_id: str = "TEST",
        currency: str = "USD",
    ) -> None:
        now = datetime.now(timezone.utc)
        pub = PublicAvailability.instant(now)
        quote = MarketQuote(
            quote_id=f"q-{evidence_id}",
            evidence_id=evidence_id,
            instrument_id=instrument_id,
            currency=currency,
            price=Decimal(str(price)),
            quote_kind=QuoteKind.REGULAR,
            retrieved_at=now,
            public_availability=pub,
        )
        self.manager.add_contract_evidence(
            evidence_id=evidence_id,
            contract_envelope=encode_envelope("MarketQuote", quote),
        )

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)
        self.run_id = "run-storage-test-01"
        self.manager = RunDatabaseManager(self.workspace, self.run_id)
        report = self.manager.create()
        self.assertTrue(report.valid, f"RunDatabase creation failed: {report.errors}")

        # Pre-seed standard typed contract evidences for tests
        self._register_quote("ev-1", Decimal("100"), instrument_id="TEST")
        self._register_quote("ev-2", Decimal("105"), instrument_id="TEST")
        self._register_quote("ev-3", Decimal("110"), instrument_id="TEST")
        self._register_quote("ev-50", Decimal("50"), instrument_id="TEST")
        self._register_quote("ev-60", Decimal("60"), instrument_id="TEST")
        self._register_quote("ev-aapl-1", Decimal("150"), instrument_id="AAPL")
        self._register_quote("ev-msft-1", Decimal("300"), instrument_id="MSFT")
        self._register_quote("ev-aapl-2", Decimal("155"), instrument_id="AAPL")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_atomic_persistence_and_cas_revision_control(self) -> None:
        slot1 = BoundSlotInput("slot_p", Decimal("100"), "CURRENCY", "USD", "ev-1")
        snap1 = SelectedInputSet.create(self.run_id, "PRICE", 1, [slot1])

        # Initial persistence with expected_revision=0 succeeds -> revision 1
        rev1 = self.manager.persist_contract_snapshot(snap1, expected_revision=0)
        self.assertEqual(rev1, 1)

        # Stale revision persistence with expected_revision=0 must fail with RevisionConflictError
        slot2 = BoundSlotInput("slot_p", Decimal("105"), "CURRENCY", "USD", "ev-2")
        snap2 = SelectedInputSet.create(self.run_id, "PRICE", 2, [slot2])
        with self.assertRaises(RevisionConflictError) as ctx:
            self.manager.persist_contract_snapshot(snap2, expected_revision=0)
        self.assertIn("Revision conflict", str(ctx.exception))

        # Persistence with expected_revision=1 succeeds -> revision 2
        rev2 = self.manager.persist_contract_snapshot(snap2, expected_revision=1)
        self.assertEqual(rev2, 2)

        # Verify snapshots reload
        latest = self.manager.fetch_latest_contract_snapshot("PRICE")
        self.assertIsNotNone(latest)
        self.assertEqual(latest.selection_version, 2)
        self.assertEqual(latest.get_slot("slot_p").canonical_value, Decimal("105"))

    def test_hash_chain_and_storage_integrity(self) -> None:
        slot1 = BoundSlotInput("s1", Decimal("50"), "CURRENCY", "USD", "ev-50")
        snap1 = SelectedInputSet.create(self.run_id, "MODE_A", 1, [slot1])
        self.manager.persist_contract_snapshot(snap1, expected_revision=0)

        slot2 = BoundSlotInput("s2", Decimal("60"), "CURRENCY", "USD", "ev-60")
        snap2 = SelectedInputSet.create(self.run_id, "MODE_A", 2, [slot2])
        self.manager.persist_contract_snapshot(snap2, expected_revision=1)

        self.assertTrue(self.manager.verify_contract_storage_integrity())

    def test_history_preservation_in_update_metadata(self) -> None:
        slot = BoundSlotInput("s1", Decimal("50"), "CURRENCY", "USD", "ev-50")
        snap = SelectedInputSet.create(self.run_id, "PRICE", 1, [slot])
        self.manager.persist_contract_snapshot(snap, expected_revision=0)

        # Call update_metadata with user metadata; contract history must NOT be wiped!
        self.manager.update_metadata(run_status="COMPLETED", metadata={"user_note": "finished"})

        reloaded = self.manager.fetch_latest_contract_snapshot("PRICE")
        self.assertIsNotNone(reloaded)
        self.assertEqual(reloaded.selection_version, 1)

        # Attempting to overwrite contract history with truncated history must be rejected
        truncated_meta = {
            "user_note": "evil",
            CONTRACT_STORAGE_KEY: {
                "contract_version": "0.2",
                "latest_revision": 0,  # rolled back revision!
                "history": [],  # emptied history!
            },
        }
        with self.assertRaises(HistoryPreservationError):
            self.manager.update_metadata(run_status="COMPLETED", metadata=truncated_meta)

    def test_counterexample_3_payload_tampering_with_same_hash_rejected(self) -> None:
        """Counterexample 3: Tampering with history entry payload while keeping snapshot_hash must be rejected."""
        slot = BoundSlotInput("s1", Decimal("50"), "CURRENCY", "USD", "ev-50")
        snap = SelectedInputSet.create(self.run_id, "PRICE", 1, [slot])
        self.manager.persist_contract_snapshot(snap, expected_revision=0)

        # Fetch raw metadata
        raw_meta = self.manager.fetch_metadata()
        meta_dict = json.loads(raw_meta["metadata_json"])
        tampered_meta = copy.deepcopy(meta_dict)

        # Alter the payload inside history entry without changing snapshot_hash
        entry = tampered_meta[CONTRACT_STORAGE_KEY]["history"][0]
        entry["envelope"]["payload"]["slots"][0]["canonical_value"] = "999"

        with self.assertRaises(HistoryPreservationError) as ctx:
            self.manager.update_metadata(run_status="COMPLETED", metadata=tampered_meta)
        self.assertIn("tamper", str(ctx.exception).lower())

    def test_unauthorized_contract_storage_injection_rejected(self) -> None:
        """Injecting a fake contract storage ledger via update_metadata when none exists must be rejected."""
        injected_meta = {
            CONTRACT_STORAGE_KEY: {
                "contract_version": "0.2",
                "latest_revision": 1,
                "latest_snapshot_hash": "fake",
                "history": [],
            }
        }
        with self.assertRaises(HistoryPreservationError) as ctx:
            self.manager.update_metadata(run_status="RUNNING", metadata=injected_meta)
        self.assertIn("Cannot inject contract storage", str(ctx.exception))

    def test_corrupted_storage_raises_corrupted_storage_error(self) -> None:
        """Corrupted contract storage must raise CorruptedStorageError, never silently reset to empty."""
        corrupted_json = json.dumps({
            CONTRACT_STORAGE_KEY: {
                "contract_version": "0.2",
                "latest_revision": -5,  # negative revision is corrupted
                "history": [],
            }
        })
        with self.assertRaises(CorruptedStorageError):
            extract_contract_storage(corrupted_json)

    def test_cross_run_and_missing_evidence_rejection(self) -> None:
        # 1. Missing evidence ID
        slot_missing = BoundSlotInput("s_miss", Decimal("50"), "USD", "USD", "ev-missing-nonexistent")
        snap_missing = SelectedInputSet.create(self.run_id, "PRICE", 1, [slot_missing])
        with self.assertRaises(EvidenceNotFoundError) as ctx:
            self.manager.persist_contract_snapshot(snap_missing, expected_revision=0)
        self.assertIn("does not exist", str(ctx.exception))

        # 2. Cross-run evidence ID
        other_run_id = "run-other-99"
        conn = sqlite3.connect(self.manager.database_path)
        try:
            with conn:
                conn.execute("PRAGMA foreign_keys=ON")
                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute(
                        "INSERT INTO evidence (evidence_id, run_id, evidence_type) VALUES (?, ?, ?)",
                        ("ev-cross-run", other_run_id, "test"),
                    )
        finally:
            conn.close()

    def test_calculation_integrity_and_bound_input_consistency(self) -> None:
        slot = BoundSlotInput("s1", Decimal("50"), "CURRENCY", "USD", "ev-50")
        snap = SelectedInputSet.create(self.run_id, "PRICE", 1, [slot])
        self.manager.persist_contract_snapshot(snap, expected_revision=0)

        # 1. UNAVAILABLE status with non-None result_numeric must be rejected
        with self.assertRaises(Exception):  # Either validation error or InputIntegrityError
            CalculationRecord.create(
                calculation_id="calc-bad-res",
                run_id=self.run_id,
                calculation_name="test_calc",
                formula_id="f1",
                formula_version="1.0",
                status=CalculationStatus.UNAVAILABLE,
                bound_inputs=[slot],
                selection_snapshot_hash=snap.snapshot_hash,
                result_numeric=Decimal("100"),
            )

        # 2. Calculation referencing unknown snapshot hash
        calc_unknown_snap = CalculationRecord.create(
            calculation_id="calc-unknown-snap",
            run_id=self.run_id,
            calculation_name="test_calc",
            formula_id="f1",
            formula_version="1.0",
            status=CalculationStatus.CALCULATED,
            bound_inputs=[slot],
            selection_snapshot_hash="unknown_snapshot_hash_1234567890",
            result_numeric=Decimal("50"),
        )
        with self.assertRaises(InputIntegrityError) as ctx:
            self.manager.persist_contract_calculation(calc_unknown_snap)
        self.assertIn("does not exist", str(ctx.exception))

        # 3. Calculation bound inputs not matching snapshot slots
        foreign_slot = BoundSlotInput("s_foreign", Decimal("60"), "USD", "USD", "ev-60")
        calc_foreign_slot = CalculationRecord.create(
            calculation_id="calc-foreign-slot",
            run_id=self.run_id,
            calculation_name="test_calc",
            formula_id="f1",
            formula_version="1.0",
            status=CalculationStatus.CALCULATED,
            bound_inputs=[foreign_slot],
            selection_snapshot_hash=snap.snapshot_hash,
            result_numeric=Decimal("50"),
        )
        with self.assertRaises(InputIntegrityError) as ctx:
            self.manager.persist_contract_calculation(calc_foreign_slot)
        self.assertIn("not found in referenced snapshot", str(ctx.exception))

    def test_idempotent_retry_handling(self) -> None:
        slot = BoundSlotInput("s1", Decimal("50"), "CURRENCY", "USD", "ev-50")
        snap = SelectedInputSet.create(self.run_id, "PRICE", 1, [slot])
        rev1 = self.manager.persist_contract_snapshot(snap, expected_revision=0)
        self.assertEqual(rev1, 1)

        # Retrying identical snapshot returns revision 1 without error
        rev_retry = self.manager.persist_contract_snapshot(snap, expected_revision=0)
        self.assertEqual(rev_retry, 1)

    def test_rollback_on_tampered_snapshot_failure(self) -> None:
        slot = BoundSlotInput("s1", Decimal("50"), "CURRENCY", "USD", "ev-50")
        snap = SelectedInputSet.create(self.run_id, "PRICE", 1, [slot])
        self.manager.persist_contract_snapshot(snap, expected_revision=0)

        # Create a tampered snapshot (hash mismatch)
        tampered = SelectedInputSet(
            run_id=self.run_id,
            purpose="PRICE",
            selection_version=2,
            slots=(slot,),
            excluded_candidates=(),
            created_at=snap.created_at,
            snapshot_hash="corrupted_hash_value",
        )
        with self.assertRaises(TamperDetectionError):
            self.manager.persist_contract_snapshot(tampered, expected_revision=1)

        # Ensure database is still at revision 1 and intact
        reloaded = self.manager.fetch_latest_contract_snapshot("PRICE")
        self.assertIsNotNone(reloaded)
        self.assertEqual(reloaded.selection_version, 1)

    def test_compatible_projections_into_sqlite_tables(self) -> None:
        # Insert evidence and market observation
        self._register_quote("ev-proj-1", Decimal("150"), instrument_id="AAPL")
        self.manager.add_market_observation(
            observation_id="obs-proj-1",
            evidence_id="ev-proj-1",
            instrument_id="AAPL",
            observed_at="2026-09-23T09:00:00+00:00",
            value="150.00",
            unit="USD",
            currency="USD",
            claimed_market_time="2026-09-23T09:00:00+00:00",
            market_session_date="2026-09-23",
            provider_id="kraken",
            freshness_status="FRESH",
        )

        slot = BoundSlotInput(
            slot_id="slot_proj",
            canonical_value=Decimal("150"),
            canonical_unit="CURRENCY",
            canonical_currency="USD",
            evidence_id="ev-proj-1",
            observation_id="obs-proj-1",
        )
        snap = SelectedInputSet.create(self.run_id, "PRICE", 1, [slot])
        calc = CalculationRecord.create(
            calculation_id="calc-proj-1",
            run_id=self.run_id,
            calculation_name="test_calc",
            formula_id="test_formula",
            formula_version="1.0",
            status=CalculationStatus.CALCULATED,
            bound_inputs=[slot],
            selection_snapshot_hash=snap.snapshot_hash,
            result_numeric=Decimal("150"),
        )
        self.manager.persist_contract_snapshot(snap, expected_revision=0, calculations=(calc,), project_compatible=True)

        # Check evidence projection
        evidence_rows = self.manager.fetch_evidence_rows()
        ev_map = {row["evidence_id"]: row for row in evidence_rows}
        self.assertEqual(ev_map["ev-proj-1"]["selection_state"], "SELECTED")

        # Check calculation projection
        calcs = self.manager.fetch_contract_calculations()
        self.assertEqual(len(calcs), 1)
        self.assertEqual(calcs[0].calculation_id, "calc-proj-1")

    def test_payload_size_limit_rejection(self) -> None:
        # Create a giant list of slots exceeding 256KB
        large_slots = [
            BoundSlotInput(
                slot_id=f"slot_{i:05d}",
                canonical_value=Decimal(str(i)),
                canonical_unit="USD",
                canonical_currency="USD",
                evidence_id="ev-large" * 10,
                input_fingerprint="fp" * 50,
            )
            for i in range(2500)
        ]
        snap = SelectedInputSet.create(self.run_id, "LARGE", 1, large_slots)
        with self.assertRaises(PayloadSizeExceededError):
            self.manager.persist_contract_snapshot(snap, expected_revision=0)

    def test_multi_instrument_active_selection_isolation_and_ambiguity_rejection(self) -> None:
        slot_aapl = BoundSlotInput("slot_p", Decimal("150"), "CURRENCY", "USD", "ev-aapl-1")
        snap_aapl1 = SelectedInputSet.create(self.run_id, "PRICE", 1, [slot_aapl], instrument_id="AAPL")
        self.manager.persist_contract_snapshot(snap_aapl1, expected_revision=0)

        # Single active snapshot for PRICE can be retrieved even without instrument_id
        active_single = self.manager.fetch_active_contract_snapshot("PRICE")
        self.assertIsNotNone(active_single)
        self.assertEqual(active_single.instrument_id, "AAPL")

        # Now persist snapshot for a second instrument under the same purpose PRICE
        slot_msft = BoundSlotInput("slot_p", Decimal("300"), "CURRENCY", "USD", "ev-msft-1")
        snap_msft = SelectedInputSet.create(self.run_id, "PRICE", 2, [slot_msft], instrument_id="MSFT")
        self.manager.persist_contract_snapshot(snap_msft, expected_revision=1)

        # Querying with specific instrument_id returns the respective isolated active snapshot
        active_aapl = self.manager.fetch_active_contract_snapshot("PRICE", instrument_id="AAPL")
        self.assertIsNotNone(active_aapl)
        self.assertEqual(active_aapl.get_slot("slot_p").canonical_value, Decimal("150"))

        active_msft = self.manager.fetch_active_contract_snapshot("PRICE", instrument_id="MSFT")
        self.assertIsNotNone(active_msft)
        self.assertEqual(active_msft.get_slot("slot_p").canonical_value, Decimal("300"))

        # Querying without instrument_id is now ambiguous and must raise AmbiguousSnapshotError
        with self.assertRaises(AmbiguousSnapshotError) as ctx:
            self.manager.fetch_active_contract_snapshot("PRICE")
        self.assertIn("Ambiguous active snapshot query", str(ctx.exception))

        # Querying for non-existent instrument returns None
        self.assertIsNone(self.manager.fetch_active_contract_snapshot("PRICE", instrument_id="GOOG"))

        # Updating revision for AAPL replaces only AAPL's active selection pointer
        slot_aapl2 = BoundSlotInput("slot_p", Decimal("155"), "CURRENCY", "USD", "ev-aapl-2")
        snap_aapl2 = SelectedInputSet.create(self.run_id, "PRICE", 3, [slot_aapl2], instrument_id="AAPL")
        self.manager.persist_contract_snapshot(snap_aapl2, expected_revision=2)

        active_aapl_rev2 = self.manager.fetch_active_contract_snapshot("PRICE", instrument_id="AAPL")
        self.assertIsNotNone(active_aapl_rev2)
        self.assertEqual(active_aapl_rev2.selection_version, 3)
        self.assertEqual(active_aapl_rev2.get_slot("slot_p").canonical_value, Decimal("155"))

        # MSFT remains unaffected
        active_msft_still = self.manager.fetch_active_contract_snapshot("PRICE", instrument_id="MSFT")
        self.assertIsNotNone(active_msft_still)
        self.assertEqual(active_msft_still.get_slot("slot_p").canonical_value, Decimal("300"))

        # Filtered snapshot history retrieval
        aapl_history = self.manager.fetch_contract_snapshots("PRICE", instrument_id="AAPL")
        self.assertEqual(len(aapl_history), 2)
        self.assertEqual([s.selection_version for s in aapl_history], [1, 3])

        msft_history = self.manager.fetch_contract_snapshots("PRICE", instrument_id="MSFT")
        self.assertEqual(len(msft_history), 1)
        self.assertEqual(msft_history[0].selection_version, 2)


if __name__ == "__main__":
    unittest.main()
