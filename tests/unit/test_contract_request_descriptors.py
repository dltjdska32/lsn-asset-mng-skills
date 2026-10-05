"""Test suite for contract request descriptor edge cases and reopen integrity."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from investment_stack.contracts.codec import encode_envelope
from investment_stack.contracts.context import PublicAvailability
from investment_stack.contracts.errors import InputIntegrityError
from investment_stack.contracts.market import MarketQuote, QuoteKind
from investment_stack.contracts.slots import (
    BoundSlotInput,
    SelectedInputSet,
    SelectionRequest,
    SlotSpec,
)
from investment_stack.contracts.storage import CONTRACT_STORAGE_KEY
from investment_stack.evidence.manager import RunDatabaseManager


class ContractRequestDescriptorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)
        self.run_id = "run-descriptor-tests-01"
        self.manager = RunDatabaseManager(self.workspace, self.run_id)
        report = self.manager.create()
        self.assertTrue(report.valid, f"RunDatabase creation failed: {report.errors}")
        self.manager.initialize_run_context(
            request_mode="single_asset_analysis",
            analysis_as_of="2024-03-31T23:59:59Z",
            analysis_timezone="UTC",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _create_market_quote_evidence(
        self, evidence_id: str, instrument_id: str, price: str, public_available_at: str
    ) -> None:
        now = datetime.now(timezone.utc)
        dt_available = datetime.fromisoformat(public_available_at.replace("Z", "+00:00"))
        pub = PublicAvailability.instant(dt_available)
        quote = MarketQuote(
            quote_id=f"q-{evidence_id}",
            evidence_id=evidence_id,
            instrument_id=instrument_id,
            currency="USD",
            price=Decimal(price),
            quote_kind=QuoteKind.REGULAR,
            retrieved_at=now,
            public_availability=pub,
        )
        self.manager.add_contract_evidence(
            evidence_id=evidence_id,
            contract_envelope=encode_envelope("MarketQuote", quote),
        )

    def test_missing_requested_slots_rejected(self) -> None:
        """등록된 request가 slot price를 요구하는데 snapshot이 빈 slots이거나 다른 slot만 갖는 경우."""
        req = SelectionRequest(
            request_id="req-1",
            purpose="CURRENT_PRICE",
            instrument_id="AAPL",
            slots=(
                SlotSpec(
                    slot_id="price",
                    purpose="CURRENT_PRICE",
                    instrument_id="AAPL",
                    metric="price",
                    dimension="MONEY_PER_SHARE",
                    currency="USD",
                ),
            ),
        )
        self.manager.persist_selection_request(req)

        # Empty slots
        snap_empty = SelectedInputSet.create(
            run_id=self.manager.run_id,
            purpose="CURRENT_PRICE",
            selection_version=1,
            slots=(),
            instrument_id="AAPL",
            request_hash=req.compute_request_hash(),
        )
        with self.assertRaises(InputIntegrityError) as ctx:
            self.manager.persist_contract_snapshot(snap_empty)
        self.assertIn("Snapshot missing requested slots", str(ctx.exception))

        # Wrong slots
        self._create_market_quote_evidence("ev-wrong", "AAPL", "150.0", "2024-03-31T20:00:00Z")
        snap_wrong = SelectedInputSet.create(
            run_id=self.manager.run_id,
            purpose="CURRENT_PRICE",
            selection_version=1,
            slots=(
                BoundSlotInput(
                    slot_id="other_slot",
                    canonical_value=Decimal("150.0"),
                    canonical_unit="CURRENCY",
                    canonical_currency="USD",
                    evidence_id="ev-wrong",
                ),
            ),
            instrument_id="AAPL",
            request_hash=req.compute_request_hash(),
        )
        with self.assertRaises(InputIntegrityError) as ctx:
            self.manager.persist_contract_snapshot(snap_wrong)
        self.assertIn("not requested by the selection request", str(ctx.exception))

    def test_evidence_missing_slot_rejected(self) -> None:
        """evidence 없는 slot 반례."""
        req = SelectionRequest(
            request_id="req-2",
            purpose="CURRENT_PRICE",
            instrument_id="AAPL",
            slots=(
                SlotSpec(
                    slot_id="price",
                    purpose="CURRENT_PRICE",
                    instrument_id="AAPL",
                    metric="price",
                    dimension="MONEY_PER_SHARE",
                    currency="USD",
                ),
            ),
        )
        self.manager.persist_selection_request(req)

        snap_missing_ev = SelectedInputSet.create(
            run_id=self.manager.run_id,
            purpose="CURRENT_PRICE",
            selection_version=1,
            slots=(
                BoundSlotInput(
                    slot_id="price",
                    canonical_value=Decimal("150.0"),
                    canonical_unit="CURRENCY",
                    canonical_currency="USD",
                    evidence_id="ev-nonexistent",
                ),
            ),
            instrument_id="AAPL",
            request_hash=req.compute_request_hash(),
        )
        with self.assertRaises(Exception) as ctx:
            self.manager.persist_contract_snapshot(snap_missing_ev)
        self.assertIn("does not exist in run.db", str(ctx.exception))

    def test_instrument_mismatch(self) -> None:
        """descriptor instrument와 snapshot instrument 불일치 반례."""
        req = SelectionRequest(
            request_id="req-3",
            purpose="CURRENT_PRICE",
            instrument_id="AAPL",
            slots=(
                SlotSpec(
                    slot_id="price",
                    purpose="CURRENT_PRICE",
                    instrument_id="AAPL",
                    metric="price",
                    dimension="MONEY_PER_SHARE",
                    currency="USD",
                ),
            ),
        )
        self.manager.persist_selection_request(req)

        snap = SelectedInputSet.create(
            run_id=self.manager.run_id,
            purpose="CURRENT_PRICE",
            selection_version=1,
            slots=(),
            instrument_id="MSFT",
            request_hash=req.compute_request_hash(),
        )
        with self.assertRaises(InputIntegrityError) as ctx:
            self.manager.persist_contract_snapshot(snap)
        self.assertIn("does not match request", str(ctx.exception))

    def test_timezone_aware_as_of_comparison(self) -> None:
        """descriptor의 as_of 이후 공개된 typed evidence (timezone-aware)."""
        req = SelectionRequest(
            request_id="req-4",
            purpose="CURRENT_PRICE",
            instrument_id="AAPL",
            as_of="2024-03-31T23:59:59Z",  # UTC
            slots=(
                SlotSpec(
                    slot_id="price",
                    purpose="CURRENT_PRICE",
                    instrument_id="AAPL",
                    metric="price",
                    dimension="MONEY_PER_SHARE",
                    currency="USD",
                ),
            ),
        )
        self.manager.persist_selection_request(req)

        # Add evidence published after as_of.
        # as_of is 23:59:59 UTC
        # evidence published at 20:00:00 -05:00 (which is 01:00:00 UTC next day, so after as_of)
        self._create_market_quote_evidence("ev-future", "AAPL", "150.0", "2024-03-31T20:00:00-05:00")

        snap = SelectedInputSet.create(
            run_id=self.manager.run_id,
            purpose="CURRENT_PRICE",
            selection_version=1,
            slots=(
                BoundSlotInput(
                    slot_id="price",
                    canonical_value=Decimal("150.0"),
                    canonical_unit="CURRENCY",
                    canonical_currency="USD",
                    evidence_id="ev-future",
                    public_available_at="2024-03-31T20:00:00-05:00",
                ),
            ),
            instrument_id="AAPL",
            request_hash=req.compute_request_hash(),
        )

        with self.assertRaises(InputIntegrityError) as ctx:
            self.manager.persist_contract_snapshot(snap)
        self.assertIn("is after request as_of", str(ctx.exception))

    def test_policy_version_mismatch(self) -> None:
        """eligibility decision의 policy_version 불일치 반례."""
        req = SelectionRequest(
            request_id="req-5",
            purpose="CURRENT_PRICE",
            instrument_id="AAPL",
            policy_version="1.0",
            slots=(
                SlotSpec(
                    slot_id="price",
                    purpose="CURRENT_PRICE",
                    instrument_id="AAPL",
                    metric="price",
                    dimension="MONEY_PER_SHARE",
                    currency="USD",
                ),
            ),
        )
        self.manager.persist_selection_request(req)

        self._create_market_quote_evidence("ev-policy", "AAPL", "150.0", "2024-03-31T20:00:00Z")

        # Mutate the db directly to add an eligibility decision with wrong policy version
        with closing(sqlite3.connect(self.manager.database_path)) as connection:
            row = connection.execute(
                "SELECT metadata_json FROM evidence WHERE evidence_id = ?",
                ("ev-policy",),
            ).fetchone()
            meta = json.loads(row[0])
            meta["eligibility_decisions"] = {
                "elig-1": {
                    "status": "ELIGIBLE",
                    "policy_version": "2.0",  # mismatch
                }
            }
            connection.execute(
                "UPDATE evidence SET metadata_json = ? WHERE evidence_id = ?",
                (json.dumps(meta), "ev-policy"),
            )
            connection.commit()

        snap = SelectedInputSet.create(
            run_id=self.manager.run_id,
            purpose="CURRENT_PRICE",
            selection_version=1,
            slots=(
                BoundSlotInput(
                    slot_id="price",
                    canonical_value=Decimal("150.0"),
                    canonical_unit="CURRENCY",
                    canonical_currency="USD",
                    evidence_id="ev-policy",
                    eligibility_id="elig-1",
                    public_available_at="2024-03-31T20:00:00+00:00",
                ),
            ),
            instrument_id="AAPL",
            request_hash=req.compute_request_hash(),
        )
        with self.assertRaises(InputIntegrityError) as ctx:
            self.manager.persist_contract_snapshot(snap)
        self.assertIn("does not match request", str(ctx.exception))

    def test_corrupt_descriptor_and_reopen(self) -> None:
        """손상된 저장 request descriptor 및 정상 reopen을 테스트하라."""
        req = SelectionRequest(
            request_id="req-6",
            purpose="CURRENT_PRICE",
            instrument_id="AAPL",
            slots=(),
        )
        self.manager.persist_selection_request(req)
        req_hash = req.compute_request_hash()

        # Corrupt it manually
        with closing(sqlite3.connect(self.manager.database_path)) as connection:
            row = connection.execute(
                "SELECT metadata_json FROM run_metadata WHERE run_id = ?", (self.manager.run_id,)
            ).fetchone()
            meta = json.loads(row[0])
            storage = meta[CONTRACT_STORAGE_KEY]
            # Corrupt the hash
            storage["requests"][0]["request_hash"] = "corrupted_hash_that_is_long_enough_to_pass_but_wrong_abcdef12345678"
            connection.execute(
                "UPDATE run_metadata SET metadata_json = ? WHERE run_id = ?",
                (json.dumps(meta), self.manager.run_id),
            )
            connection.commit()

        # Reopen should fail due to integrity failure in storage.py during validation
        # manager.open() returns RunValidationReport(valid=False, errors=(...))
        report_fail = self.manager.open()
        self.assertFalse(report_fail.valid)
        self.assertTrue(any("invalid request" in err or "!= expected" in err for err in report_fail.errors))

        # Fix it
        with closing(sqlite3.connect(self.manager.database_path)) as connection:
            row = connection.execute(
                "SELECT metadata_json FROM run_metadata WHERE run_id = ?", (self.manager.run_id,)
            ).fetchone()
            meta = json.loads(row[0])
            storage = meta[CONTRACT_STORAGE_KEY]
            storage["requests"][0]["request_hash"] = req_hash
            connection.execute(
                "UPDATE run_metadata SET metadata_json = ? WHERE run_id = ?",
                (json.dumps(meta), self.manager.run_id),
            )
            connection.commit()

        # Reopen should succeed
        report_ok = self.manager.open()
        self.assertTrue(report_ok.valid)

    def test_legacy_request_hash_none(self) -> None:
        """request_hash=None legacy 경로는 보존한다."""
        self._create_market_quote_evidence("ev-legacy", "AAPL", "150.0", "2024-03-31T20:00:00Z")
        snap = SelectedInputSet.create(
            run_id=self.manager.run_id,
            purpose="CURRENT_PRICE",
            selection_version=1,
            slots=(
                BoundSlotInput(
                    slot_id="price",
                    canonical_value=Decimal("150.0"),
                    canonical_unit="CURRENCY",
                    canonical_currency="USD",
                    evidence_id="ev-legacy",
                    public_available_at="2024-03-31T20:00:00+00:00",
                ),
            ),
            instrument_id="AAPL",
            request_hash=None,
        )
        rev = self.manager.persist_contract_snapshot(snap)
        self.assertEqual(rev, 1)


if __name__ == "__main__":
    unittest.main()
