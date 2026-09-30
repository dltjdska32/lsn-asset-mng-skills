"""Audit test suite for contract storage residual checks, synthetic failure models, and reopen integrity."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from investment_stack.contracts.calculation import (
    CalculationRecord,
    CalculationStatus,
)
from investment_stack.contracts.codec import encode_envelope
from investment_stack.contracts.context import PublicAvailability
from investment_stack.contracts.errors import (
    ContractError,
    ContractValidationError,
    CorruptedStorageError,
    InputIntegrityError,
)
from investment_stack.contracts.market import MarketQuote, QuoteKind
from investment_stack.contracts.slots import (
    BoundSlotInput,
    SelectedInputSet,
)
from investment_stack.contracts.storage import (
    CONTRACT_STORAGE_KEY,
    empty_contract_storage,
)
from investment_stack.evidence.manager import RunDatabaseManager


class ContractStorageAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)
        self.run_id = "run-audit-synthetic-01"
        self.manager = RunDatabaseManager(self.workspace, self.run_id)
        report = self.manager.create()
        self.assertTrue(report.valid, f"RunDatabase creation failed: {report.errors}")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_value_free_evidence_cannot_authorize_price(self) -> None:
        """Raw untyped evidence without canonical binding projection cannot authorize bound calculation slots."""
        self.manager.add_evidence(evidence_id="value-free", evidence_type="test")
        slot = BoundSlotInput("price", Decimal("999999"), "USD", "USD", "value-free")
        snap = SelectedInputSet.create(self.manager.run_id, "CURRENT_PRICE", 1, [slot])

        with self.assertRaises(InputIntegrityError) as ctx:
            self.manager.persist_contract_snapshot(snap)
        self.assertIn("canonical binding projection", str(ctx.exception))

    def test_typed_evidence_decoder_is_required(self) -> None:
        """add_contract_evidence must strictly decode typed contract payload; malformed payload is rejected without DB insert."""
        malformed_envelope = encode_envelope("MarketQuote", {"currency": "USD"})

        with self.assertRaises(ContractValidationError) as ctx:
            self.manager.add_contract_evidence(
                evidence_id="malformed",
                contract_envelope=malformed_envelope,
            )
        self.assertIn("missing required keys", str(ctx.exception))

        # Verify no evidence row was inserted into the database
        with closing(sqlite3.connect(self.manager.database_path)) as connection:
            row = connection.execute(
                "SELECT evidence_id FROM evidence WHERE evidence_id = ?",
                ("malformed",),
            ).fetchone()
            self.assertIsNone(row, "Evidence row must NOT be inserted when decoder validation fails")

    def test_counter_tail_mismatch_read(self) -> None:
        """Counter-tail mismatch in contract storage ledger must fail closed with CorruptedStorageError."""
        storage = empty_contract_storage()
        storage.update(latest_revision=999)
        with closing(sqlite3.connect(self.manager.database_path)) as connection:
            connection.execute(
                "UPDATE run_metadata SET metadata_json=? WHERE run_id=?",
                (json.dumps({CONTRACT_STORAGE_KEY: storage}), self.manager.run_id),
            )
            connection.commit()

        with self.assertRaises(CorruptedStorageError) as ctx:
            self.manager.fetch_contract_snapshots()
        self.assertIn("Counter tail mismatch", str(ctx.exception))

    def test_missing_history_envelope_read(self) -> None:
        """History entry missing envelope must fail closed with CorruptedStorageError."""
        storage = empty_contract_storage()
        storage.update(
            history=[{"revision": 1, "snapshot_hash": "x"}],
            latest_revision=1,
            latest_snapshot_hash="x",
        )
        with closing(sqlite3.connect(self.manager.database_path)) as connection:
            connection.execute(
                "UPDATE run_metadata SET metadata_json=? WHERE run_id=?",
                (json.dumps({CONTRACT_STORAGE_KEY: storage}), self.manager.run_id),
            )
            connection.commit()

        with self.assertRaises(CorruptedStorageError) as ctx:
            self.manager.fetch_contract_snapshots()
        self.assertIn("missing 'envelope'", str(ctx.exception))

    def test_dangling_active_pointer_read(self) -> None:
        """Active selection pointer targeting non-existent snapshot hash must fail closed."""
        storage = empty_contract_storage()
        storage.update(active_selections={"CURRENT_PRICE:TEST": "missing"})
        with closing(sqlite3.connect(self.manager.database_path)) as connection:
            connection.execute(
                "UPDATE run_metadata SET metadata_json=? WHERE run_id=?",
                (json.dumps({CONTRACT_STORAGE_KEY: storage}), self.manager.run_id),
            )
            connection.commit()

        with self.assertRaises(CorruptedStorageError) as ctx:
            self.manager.fetch_contract_snapshots()
        self.assertIn("Dangling active selection pointer", str(ctx.exception))

    def test_positive_reopen_and_persistence(self) -> None:
        """Valid typed evidence, snapshot, and calculation can be persisted and reopened cleanly."""
        now = datetime.now(timezone.utc)
        pub = PublicAvailability.instant(now)
        quote = MarketQuote(
            quote_id="q-reopen-1",
            evidence_id="ev-reopen-1",
            instrument_id="AAPL",
            currency="USD",
            price=Decimal("150.50"),
            quote_kind=QuoteKind.REGULAR,
            retrieved_at=now,
            public_availability=pub,
        )
        self.manager.add_contract_evidence(
            evidence_id="ev-reopen-1",
            contract_envelope=encode_envelope("MarketQuote", quote),
        )

        slot = BoundSlotInput(
            slot_id="slot_price",
            canonical_value=Decimal("150.50"),
            canonical_unit="CURRENCY",
            canonical_currency="USD",
            evidence_id="ev-reopen-1",
        )
        snap = SelectedInputSet.create(
            self.manager.run_id,
            "CURRENT_PRICE",
            1,
            [slot],
            instrument_id="AAPL",
        )
        rev = self.manager.persist_contract_snapshot(snap, expected_revision=0)
        self.assertEqual(rev, 1)

        calc = CalculationRecord.create(
            calculation_id="calc-reopen-1",
            run_id=self.manager.run_id,
            calculation_name="test_reopen_calc",
            formula_id="price_identity",
            formula_version="1.0",
            status=CalculationStatus.CALCULATED,
            bound_inputs=[slot],
            selection_snapshot_hash=snap.snapshot_hash,
            result_numeric=Decimal("150.50"),
            result_currency="USD",
            result_unit="CURRENCY",
        )
        self.manager.persist_contract_calculation(calc)

        # Reopen in a new manager instance
        manager2 = RunDatabaseManager(self.workspace, self.run_id)
        manager2.open()
        self.assertTrue(manager2.verify_contract_storage_integrity())

        active = manager2.fetch_active_contract_snapshot("CURRENT_PRICE", instrument_id="AAPL")
        self.assertIsNotNone(active)
        self.assertEqual(active.get_slot("slot_price").canonical_value, Decimal("150.50"))

        calcs = manager2.fetch_contract_calculations()
        self.assertEqual(len(calcs), 1)
        self.assertEqual(calcs[0].result_numeric, Decimal("150.50"))

    def test_duplicate_bound_slot_rejected(self) -> None:
        """Calculations with duplicate bound input slot IDs must be rejected."""
        now = datetime.now(timezone.utc)
        pub = PublicAvailability.instant(now)
        quote = MarketQuote(
            quote_id="q-dup-1",
            evidence_id="ev-dup-1",
            instrument_id="AAPL",
            currency="USD",
            price=Decimal("100"),
            quote_kind=QuoteKind.REGULAR,
            retrieved_at=now,
            public_availability=pub,
        )
        self.manager.add_contract_evidence(
            evidence_id="ev-dup-1",
            contract_envelope=encode_envelope("MarketQuote", quote),
        )

        slot = BoundSlotInput(
            slot_id="s1",
            canonical_value=Decimal("100"),
            canonical_unit="CURRENCY",
            canonical_currency="USD",
            evidence_id="ev-dup-1",
        )
        snap = SelectedInputSet.create(self.manager.run_id, "PRICE", 1, [slot])
        self.manager.persist_contract_snapshot(snap, expected_revision=0)

        calc = CalculationRecord(
            calculation_id="calc-dup-slots",
            run_id=self.manager.run_id,
            calculation_name="dup_slots_calc",
            formula_id="f1",
            formula_version="1.0",
            status=CalculationStatus.CALCULATED,
            bound_inputs=(slot, slot),  # duplicate slot!
            selection_snapshot_hash=snap.snapshot_hash,
            result_numeric=Decimal("200"),
            result_unit="USD",
            result_currency="USD",
            calculated_at=now.isoformat(),
            lineage_hash="",
        )
        # Compute proper lineage hash for the duplicate record to test persistence check
        calc_with_hash = CalculationRecord(
            calculation_id=calc.calculation_id,
            run_id=calc.run_id,
            calculation_name=calc.calculation_name,
            formula_id=calc.formula_id,
            formula_version=calc.formula_version,
            status=calc.status,
            bound_inputs=calc.bound_inputs,
            selection_snapshot_hash=calc.selection_snapshot_hash,
            result_numeric=calc.result_numeric,
            result_unit=calc.result_unit,
            result_currency=calc.result_currency,
            calculated_at=calc.calculated_at,
            lineage_hash=calc.compute_lineage_hash(),
        )
        with self.assertRaises(InputIntegrityError) as ctx:
            self.manager.persist_contract_calculation(calc_with_hash)
        self.assertIn("duplicate bound input slot", str(ctx.exception))

    def test_preceding_calculation_reference_validation(self) -> None:
        """Calculations referencing non-existent preceding calculations must be rejected."""
        now = datetime.now(timezone.utc)
        pub = PublicAvailability.instant(now)
        quote = MarketQuote(
            quote_id="q-prec-1",
            evidence_id="ev-prec-1",
            instrument_id="AAPL",
            currency="USD",
            price=Decimal("100"),
            quote_kind=QuoteKind.REGULAR,
            retrieved_at=now,
            public_availability=pub,
        )
        self.manager.add_contract_evidence(
            evidence_id="ev-prec-1",
            contract_envelope=encode_envelope("MarketQuote", quote),
        )

        slot = BoundSlotInput(
            slot_id="s1",
            canonical_value=Decimal("100"),
            canonical_unit="CURRENCY",
            canonical_currency="USD",
            evidence_id="ev-prec-1",
        )
        snap = SelectedInputSet.create(self.manager.run_id, "PRICE", 1, [slot])
        self.manager.persist_contract_snapshot(snap, expected_revision=0)

        calc = CalculationRecord.create(
            calculation_id="calc-bad-preceding",
            run_id=self.manager.run_id,
            calculation_name="prec_calc",
            formula_id="f1",
            formula_version="1.0",
            status=CalculationStatus.CALCULATED,
            bound_inputs=[slot],
            selection_snapshot_hash=snap.snapshot_hash,
            result_numeric=Decimal("100"),
            preceding_calculation_ids=("calc-nonexistent",),
        )
        with self.assertRaises(InputIntegrityError) as ctx:
            self.manager.persist_contract_calculation(calc)
        self.assertIn("non-existent preceding calculation", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
