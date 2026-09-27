"""Test Decimal conversion and persistence in Phase 4 evidence layer."""

import os
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
        self.run_db_path = os.path.join(self.temp_dir.name, "run.db")
        self.run_db = RunDatabaseManager(self.run_db_path)
        self.run_db.initialize_schema()
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
        
        result = ProviderResult(
            provider_name="sec",
            capability=ProviderCapability.FUNDAMENTALS,
            status=ProviderStatus.AVAILABLE,
            observations=(obs,)
        )
        
        selected = self.store.persist_and_select([result], analysis_as_of=_now())
        self.assertIsNotNone(selected.observation)
        
        # Verify it was saved as a string in DB
        with self.run_db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM phase4_financial_observations WHERE evidence_id = ?", (selected.evidence_id,))
            row = cursor.fetchone()
            self.assertIsNotNone(row)
            
            # Find the string representation of our precise decimal in the stored row
            found_str = any(str(col) == "123456789.123456789123456789" for col in row)
            self.assertTrue(found_str, f"Decimal string not found in DB row: {row}")

if __name__ == "__main__":
    unittest.main()
