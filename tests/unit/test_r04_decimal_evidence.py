"""Test Decimal conversion and persistence in Phase 4 evidence layer."""

import os
import sqlite3
import json
from contextlib import closing
import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal

from investment_stack.evidence.manager import RunDatabaseManager
from investment_stack.evidence.research import EvidenceResearchStore
from investment_stack.freshness.engine import FreshnessEngine
from investment_stack.providers.models import ProviderObservation, ProviderResult, ProviderCapability, ProviderStatus

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

class DecimalEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.run_db = RunDatabaseManager(self.temp_dir.name, "r04-decimal-test")
        report = self.run_db.create()
        self.assertTrue(report.valid, report.errors)
        self.store = EvidenceResearchStore(self.run_db, freshness=FreshnessEngine())

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_persist_decimal_precision(self):
        # A decimal that would lose precision if cast to float
        precise_val = Decimal("123456789.123456789123456789")
        
        obs = ProviderObservation(
            evidence_type="financial",
            source_name="SEC",
            source_url="http://sec",
            source_tier=1,
            provider_id="sec",
            value=precise_val,
            metric="revenue",
            observed_at=_now(),
            metadata={"period_end": "2023-12-31"}
        )
        
        result = ProviderResult("sec", ProviderCapability.FUNDAMENTALS, ProviderStatus.AVAILABLE, (obs,))
        
        selected = self.store.persist_and_select([result], analysis_as_of=_now())
        self.assertIsNotNone(selected.observation)
        
        # Verify it was saved as a string in DB
        with closing(sqlite3.connect(self.run_db.database_path)) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM financial_observations WHERE evidence_id = ?", (selected.evidence_id,))
            row = cursor.fetchone()
            self.assertIsNotNone(row)
            
            # NUMERIC affinity stores the projection as a float; exact input remains in lineage metadata.
            metadata = json.loads(row[7])
            self.assertEqual(metadata["exact_value_decimal"], "123456789.123456789123456789")

if __name__ == "__main__":
    unittest.main()
