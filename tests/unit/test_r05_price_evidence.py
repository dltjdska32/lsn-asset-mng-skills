"""Test price evidence selection constraints in Phase 4."""

import os
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from investment_stack.evidence.manager import RunDatabaseManager
from investment_stack.evidence.research import EvidenceResearchStore
from investment_stack.freshness.engine import FreshnessEngine
from investment_stack.providers.models import ProviderObservation, ProviderResult, ProviderCapability, ProviderStatus

class PriceEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.run_db_path = os.path.join(self.temp_dir.name, "run.db")
        self.run_db = RunDatabaseManager(self.run_db_path)
        self.run_db.initialize_schema()
        self.store = EvidenceResearchStore(self.run_db, freshness=FreshnessEngine())

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_current_price_rejects_invalid_values(self):
        base_time = datetime(2024, 4, 1, 10, 0, tzinfo=timezone.utc)
        analysis_as_of = base_time.isoformat()
        
        # 1. Invalid values for current_price (should be rejected from selection)
        invalid_vals = [0, -10, Decimal("-5.5"), float("nan"), float("inf"), True, False]
        
        obs_invalid = [
            ProviderObservation(
                evidence_type="market",
                source_name="test",
                source_url="http://test",
                source_tier=1,
                provider_id="test",
                value=val,
                metric="current_price",
                observed_at=(base_time - timedelta(minutes=5)).isoformat(), # Very fresh
                metadata={"calculation_input_approved": True}
            ) for val in invalid_vals
        ]
        
        # 2. Valid stale value (should be selected as PARTIAL over the rejected fresh ones)
        obs_stale = ProviderObservation(
            evidence_type="market",
            source_name="test",
            source_url="http://test",
            source_tier=1,
            provider_id="test",
            value=150.0,
            metric="current_price",
            observed_at=(base_time - timedelta(days=2)).isoformat(), # Stale
            metadata={"calculation_input_approved": True}
        )
        
        result = ProviderResult(
            provider_name="test_provider",
            capability=ProviderCapability.CURRENT_PRICE,
            status=ProviderStatus.AVAILABLE,
            observations=tuple(obs_invalid + [obs_stale])
        )
        
        selected = self.store.persist_and_select([result], analysis_as_of=analysis_as_of)
        
        # Should select the stale valid value, not the fresh invalid ones
        self.assertIsNotNone(selected.observation)
        self.assertEqual(selected.observation.value, 150.0)
        self.assertTrue(selected.partial)
        
        # Verify invalid values are still recorded in DB (not totally dropped from storage)
        with self.run_db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM phase4_market_observations")
            count = cursor.fetchone()[0]
            self.assertEqual(count, len(invalid_vals) + 1)

if __name__ == "__main__":
    unittest.main()
