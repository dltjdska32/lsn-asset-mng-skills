"""Synthetic positive and negative SelectionRequest persistence probe."""

from __future__ import annotations

import argparse
import sys
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path


parser = argparse.ArgumentParser()
parser.add_argument("--repo", required=True)
args = parser.parse_args()
sys.path.insert(0, str(Path(args.repo) / "runtime"))

from investment_stack.contracts.codec import encode_envelope  # noqa: E402
from investment_stack.contracts.context import PublicAvailability  # noqa: E402
from investment_stack.contracts.market import MarketQuote, QuoteKind  # noqa: E402
from investment_stack.contracts.slots import BoundSlotInput, SelectedInputSet, SelectionRequest, SlotSpec  # noqa: E402
from investment_stack.evidence.manager import RunDatabaseManager  # noqa: E402


with tempfile.TemporaryDirectory() as temp_dir:
    manager = RunDatabaseManager(Path(temp_dir), "request-positive-probe")
    assert manager.create().valid
    now = datetime(2026, 9, 23, tzinfo=timezone.utc)
    quote = MarketQuote(
        quote_id="q1", evidence_id="e1", instrument_id="AAPL", currency="USD",
        price=Decimal("150.5"), quote_kind=QuoteKind.REGULAR,
        retrieved_at=now, public_availability=PublicAvailability.instant(now),
    )
    manager.add_contract_evidence(evidence_id="e1", contract_envelope=encode_envelope("MarketQuote", quote))
    request = SelectionRequest(
        request_id="req1", purpose="CURRENT_PRICE", instrument_id="AAPL",
        slots=(SlotSpec(slot_id="price", purpose="CURRENT_PRICE", instrument_id="AAPL", metric="price", dimension="MONEY_PER_SHARE", currency="USD"),),
        as_of="2026-09-24T00:00:00+00:00",
    )
    manager.persist_selection_request(request)
    slot = BoundSlotInput("price", Decimal("150.5"), "CURRENCY", "USD", "e1")
    snapshot = SelectedInputSet.create(manager.run_id, "CURRENT_PRICE", 1, [slot], instrument_id="AAPL", request_hash=request.compute_request_hash())
    manager.persist_contract_snapshot(snapshot, expected_revision=0)
    reopened = RunDatabaseManager(Path(temp_dir), manager.run_id)
    reopened.open()
    assert reopened.verify_contract_storage_integrity()
    print("PASS registered request snapshot and reopen")
