from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from investment_stack.contracts.calculation import (
    CalculationRecord,
    CalculationStatus,
    OutputKind,
    TypedOutput,
)
from investment_stack.contracts.codec import encode_envelope
from investment_stack.contracts.context import PublicAvailability
from investment_stack.contracts.market import MarketQuote, QuoteKind
from investment_stack.contracts.slots import BoundSlotInput, SelectedInputSet
from investment_stack.decisions.persisted_context import bind_persisted_numeric
from investment_stack.evidence.manager import RunDatabaseManager


class PersistedNumericContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.manager = RunDatabaseManager(Path(self.temp_dir.name), "run-persisted-context")
        self.assertTrue(self.manager.create().valid)
        self.cutoff = datetime.now(timezone.utc)
        self.manager.initialize_run_context(
            request_mode="SINGLE_ASSET_ANALYSIS",
            analysis_as_of=self.cutoff.isoformat(),
            analysis_timezone="UTC",
            state_version=0,
            personal_db_instance_id="NONE:TEST",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _persist(
        self,
        *,
        value: Decimal = Decimal("1.23"),
        typed: bool = True,
        available_at: datetime | None = None,
    ) -> None:
        now = available_at or self.cutoff - timedelta(minutes=1)
        available_text = now.isoformat()
        quote = MarketQuote(
            quote_id="q-price",
            evidence_id="ev-price",
            instrument_id="TEST",
            currency="USD",
            price=Decimal("1.23"),
            quote_kind=QuoteKind.REGULAR,
            retrieved_at=now,
            public_availability=PublicAvailability.instant(now),
        )
        self.manager.add_contract_evidence(
            evidence_id="ev-price",
            contract_envelope=encode_envelope("MarketQuote", quote),
        )
        slot = BoundSlotInput(
            "slot-price", Decimal("1.23"), "CURRENCY", "USD", "ev-price",
            public_available_at=available_text,
        )
        snapshot = SelectedInputSet.create(self.manager.run_id, "CURRENT_PRICE", 1, [slot])
        calc = CalculationRecord.create(
            calculation_id="calc-price",
            run_id=self.manager.run_id,
            calculation_name="current_price",
            formula_id="spot-price",
            formula_version="1",
            status=CalculationStatus.CALCULATED,
            bound_inputs=(slot,),
            selection_snapshot_hash=snapshot.snapshot_hash,
            result_numeric=value,
            result_unit="USD/share",
            result_currency="USD",
            typed_outputs=(TypedOutput(OutputKind.PRICE, value, "USD/share", "USD"),) if typed else (),
            purpose="CURRENT_PRICE",
        )
        self.manager.persist_contract_snapshot(snapshot, expected_revision=0, calculations=(calc,))

    def test_same_persisted_ids_do_not_bind_a_different_requested_numeric(self) -> None:
        self._persist()

        binding = bind_persisted_numeric(
            self.manager,
            calculation_id="calc-price",
            requested_value=Decimal("999999"),
            evidence_ids=("ev-price",),
            output_kind=OutputKind.PRICE,
            analysis_as_of=self.cutoff,
        )

        self.assertIsNone(binding)

    def test_exact_persisted_value_binds_to_its_persisted_evidence(self) -> None:
        self._persist()

        binding = bind_persisted_numeric(
            self.manager,
            calculation_id="calc-price",
            requested_value=Decimal("1.23"),
            evidence_ids=("ev-price",),
            output_kind=OutputKind.PRICE,
            analysis_as_of=self.cutoff,
        )

        self.assertIsNotNone(binding)
        self.assertEqual(binding.value, Decimal("1.23"))
        self.assertEqual(binding.evidence_ids, ("ev-price",))

    def test_no_persisted_typed_calculation_is_unavailable(self) -> None:
        self._persist(typed=False)

        binding = bind_persisted_numeric(
            self.manager,
            calculation_id="calc-price",
            requested_value=Decimal("1.23"),
            evidence_ids=("ev-price",),
            output_kind=OutputKind.PRICE,
            analysis_as_of=self.cutoff,
        )

        self.assertIsNone(binding)

    def test_missing_persisted_calculation_is_unavailable(self) -> None:
        binding = bind_persisted_numeric(
            self.manager,
            calculation_id="calc-missing",
            requested_value=Decimal("1.23"),
            evidence_ids=("ev-price",),
            output_kind=OutputKind.PRICE,
            analysis_as_of=self.cutoff,
        )

        self.assertIsNone(binding)

    def test_future_public_evidence_is_unavailable_at_the_pinned_cutoff(self) -> None:
        self._persist(available_at=self.cutoff + timedelta(hours=1))

        binding = bind_persisted_numeric(
            self.manager,
            calculation_id="calc-price",
            requested_value=Decimal("1.23"),
            evidence_ids=("ev-price",),
            output_kind=OutputKind.PRICE,
            analysis_as_of=self.cutoff,
        )

        self.assertIsNone(binding)

    def test_same_evidence_id_with_a_changed_canonical_value_is_unavailable(self) -> None:
        self._persist()
        with closing(sqlite3.connect(self.manager.database_path)) as connection:
            row = connection.execute(
                "SELECT metadata_json FROM evidence WHERE evidence_id = ?", ("ev-price",)
            ).fetchone()
            metadata = json.loads(row[0])
            metadata["canonical_payload"]["canonical_value"] = "999"
            connection.execute(
                "UPDATE evidence SET metadata_json = ? WHERE evidence_id = ?",
                (json.dumps(metadata, sort_keys=True), "ev-price"),
            )
            connection.commit()

        binding = bind_persisted_numeric(
            self.manager,
            calculation_id="calc-price",
            requested_value=Decimal("1.23"),
            evidence_ids=("ev-price",),
            output_kind=OutputKind.PRICE,
            analysis_as_of=self.cutoff,
        )

        self.assertIsNone(binding)

    def test_caller_cannot_advance_pinned_cutoff_to_admit_future_evidence(self) -> None:
        self._persist(available_at=self.cutoff + timedelta(hours=1))
        binding = bind_persisted_numeric(
            self.manager,
            calculation_id="calc-price",
            requested_value=Decimal("1.23"),
            evidence_ids=("ev-price",),
            output_kind=OutputKind.PRICE,
            analysis_as_of=self.cutoff + timedelta(days=1),
        )
        self.assertIsNone(binding)


if __name__ == "__main__":
    unittest.main()
