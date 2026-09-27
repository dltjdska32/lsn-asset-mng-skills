"""Independent follow-up regression expectations for fixed SHA 979cc5e.

No implementation edits, actual personal database, credentials, or orders.
Run: python docs/workflow/reviews/review_code_01_interim_probes.py -v
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "runtime"))

from datetime import datetime
from decimal import Decimal as D
import json
import unittest
from tests.integration.test_r14_equity_mode_bundles import R14EquityModeBundleIntegrationTests
from investment_stack.execution import ModeRequest, execute_mode
from investment_stack.routing import RequestMode
from investment_stack.contracts.institutional import Holding13F, HoldingSet13F
from investment_stack.contracts.context import PublicAvailability
from investment_stack.institutional.compare import compare_portfolios
from investment_stack.institutional.scoring import compute_institutional_features


class FollowUpReview(unittest.TestCase):
    def test_rc04_missing_eps_period_cannot_borrow_other_metric_context(self):
        class MissingMetricContext(R14EquityModeBundleIntegrationTests):
            def bundle(self, specs, **kwargs):
                data = super().bundle(specs, **kwargs)
                for hit in data["responses"][3]["hits"]:
                    if hit["metadata"]["metric"] == "eps":
                        hit["metadata"].pop("start", None)
                        hit["metadata"].pop("restatement", None)
                return data
        fixture = MissingMetricContext()
        try:
            specs = fixture.specs()
            run, services = fixture.make_services("review-eps-period", specs, mode=RequestMode.ASSET_COMPARISON)
            execute_mode(ModeRequest("review-eps-period", RequestMode.ASSET_COMPARISON,
                                    {"research_specs": specs}), services)
            row = next(row for row in run.fetch_phase6_context()["calculations"]
                       if row["calculation_name"] == "asset_comparison")
            comparisons = json.loads(row["result_json"])["comparisons"]
            self.assertNotIn("eps", {item["metric"] for item in comparisons},
                             "EPS period missing but other metrics' context authorized its comparison")
        finally:
            fixture.doCleanups()

    @staticmethod
    def holdings(fid, period, quantity):
        holding = Holding13F("h-" + fid, fid, "037833100", "SYNTHETIC",
            D(quantity), D("1000"), D("1000"), D(quantity), security_class="COM", value_scale=D(1))
        return HoldingSet13F.create(fid, "0000000001", period, (holding,))

    def comparison(self, prior, current):
        public = PublicAvailability.exact(datetime.fromisoformat("2026-08-15T00:00:00+00:00"),
                                          locator="synthetic:filing")
        return compare_portfolios(prior, current, prior_public_availability=public,
                                  current_public_availability=public)

    @staticmethod
    def features(comparisons):
        return compute_institutional_features("037833100", "0000000001", comparisons,
            datetime.fromisoformat("2026-09-27T12:00:00+00:00"))

    def test_rc05_reversed_quarters_cannot_create_current_direction(self):
        reversed_comparison = self.comparison(self.holdings("q2", "2026-06-30", "200"),
                                             self.holdings("q1", "2026-03-31", "100"))
        feature = self.features((reversed_comparison,))
        self.assertIsNone(feature.institutional_consensus_direction,
                          "Reversed quarters were accepted as a point-in-time reduction")

    def test_rc05_duplicate_gap_comparisons_are_not_consecutive_quarters(self):
        first = self.comparison(self.holdings("y1", "2024-03-31", "100"),
                                self.holdings("y2", "2025-03-31", "200"))
        second = self.comparison(self.holdings("y3", "2025-03-31", "200"),
                                 self.holdings("y4", "2026-06-30", "200"))
        feature = self.features((first, second, second))
        self.assertLessEqual(feature.consecutive_quarters_held, 1,
                             "Missing quarters and duplicated current period cannot prove continuity")


if __name__ == "__main__":
    unittest.main(defaultTest="FollowUpReview")
