"""Test suite for R01: Deep research price consumption path and bindings."""

import unittest
from decimal import Decimal
from unittest.mock import MagicMock

from investment_stack.asset_analysis import Phase5AssetAnalysisRuntime
from investment_stack.deep_research import (
    EquityResearchSpec,
    LiveDeepResearchRuntime,
)
from investment_stack.evidence import SelectedEvidence
from investment_stack.freshness import FreshnessAssessment, FreshnessStatus
from investment_stack.providers.models import ProviderObservation
from investment_stack.research import Phase4ResearchRuntime, ResearchOutcome


class R01PriceBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mock_research = MagicMock(spec=Phase4ResearchRuntime)
        self.mock_analysis = MagicMock(spec=Phase5AssetAnalysisRuntime)

        # Mock run_db responses
        self.mock_analysis.run_db = MagicMock()
        self.mock_analysis.run_db.fetch_evidence_rows.return_value = []
        self.mock_analysis.run_db.fetch_phase6_context.return_value = {
            "financial_observations": [],
            "evidence": []
        }

        # Mock analysis result
        mock_analyzed = MagicMock()
        mock_analyzed.fundamental.metadata = {}
        mock_analyzed.valuation.metadata = {}
        self.mock_analysis.analyze_equity.return_value = mock_analyzed

        self.runtime = LiveDeepResearchRuntime(
            research=self.mock_research,
            analysis=self.mock_analysis,
            analysis_as_of="2024-03-31T23:59:59Z",
            analysis_timezone="UTC"
        )
        # We will mock freshness per test to return specific statuses
        self.runtime.freshness = MagicMock()

        self.spec = EquityResearchSpec(
            instrument_id="AAPL",
            display_name="Apple Inc.",
            country="USA",
            currency="USD",
        )

    def _setup_market_outcome(self, observation: ProviderObservation | None) -> None:
        freshness = FreshnessAssessment(FreshnessStatus.FRESH, "2024-03-31T20:00:00Z", 14400, "ok") if observation else None
        outcome = ResearchOutcome(
            selected=SelectedEvidence(
                observation=observation,
                freshness=freshness,
                evidence_id="ev-1" if observation else None,
                observation_id="obs-1" if observation else None,
                partial=False,
                reason="test"
            ),
            provider_results=(),
            used_web_fallback=False
        )

        # Default empty outcomes for fundamentals and news
        empty_outcome = ResearchOutcome(
            selected=SelectedEvidence(
                observation=None,
                freshness=None,
                evidence_id=None,
                observation_id=None,
                partial=False,
                reason=""
            ),
            provider_results=(),
            used_web_fallback=False
        )

        self.mock_research.collect.side_effect = [
            outcome,       # market
            empty_outcome, # fundamentals
            empty_outcome  # news (if called)
        ]

    def test_valid_fresh_price(self):
        obs = ProviderObservation(
            evidence_type="market",
            source_name="test_source",
            source_url="http://test",
            source_tier=1,
            provider_id="test",
            instrument_id="AAPL",
            value="150.0",
            currency="USD",
            unit="USD",
            observed_at="2024-03-31T20:00:00Z"
        )
        self._setup_market_outcome(obs)
        self.runtime.freshness.assess.return_value = FreshnessAssessment(FreshnessStatus.FRESH, "2024-03-31T20:00:00Z", 14400, "ok")

        outcome = self.runtime.analyze_equity(self.spec)

        # Verify analysis received the valid price
        val_input = self.mock_analysis.analyze_equity.call_args[0][1]
        self.assertEqual(val_input.current_price, Decimal("150.0"))

        # Verify task state metadata doesn't have price warning
        record_call = self.mock_analysis.run_db.record_task_state.call_args_list[-1]
        metadata = record_call[1]["metadata"]
        self.assertFalse(any("price:" in w for w in metadata["normalization_warnings"]))

    def test_stale_price_rejected(self):
        obs = ProviderObservation(
            evidence_type="market",
            source_name="test_source",
            source_url="http://test",
            source_tier=1,
            provider_id="test",
            instrument_id="AAPL",
            value="150.0",
            currency="USD",
            unit="USD",
            observed_at="2024-03-30T20:00:00Z"
        )
        self._setup_market_outcome(obs)
        self.runtime.freshness.assess.return_value = FreshnessAssessment(FreshnessStatus.STALE, "2024-03-30T20:00:00Z", 100800, "stale")

        outcome = self.runtime.analyze_equity(self.spec)

        val_input = self.mock_analysis.analyze_equity.call_args[0][1]
        self.assertIsNone(val_input.current_price)

        record_call = self.mock_analysis.run_db.record_task_state.call_args_list[-1]
        metadata = record_call[1]["metadata"]
        self.assertTrue(any("price: freshness assessment resulted in STALE" in w for w in metadata["normalization_warnings"]))

    def test_currency_mismatch_rejected(self):
        obs = ProviderObservation(
            evidence_type="market",
            source_name="test_source",
            source_url="http://test",
            source_tier=1,
            provider_id="test",
            instrument_id="AAPL",
            value="150.0",
            currency="EUR", # mismatch with spec.currency
            unit="EUR",
            observed_at="2024-03-31T20:00:00Z"
        )
        self._setup_market_outcome(obs)
        self.runtime.freshness.assess.return_value = FreshnessAssessment(FreshnessStatus.FRESH, "2024-03-31T20:00:00Z", 14400, "ok")

        outcome = self.runtime.analyze_equity(self.spec)

        val_input = self.mock_analysis.analyze_equity.call_args[0][1]
        self.assertIsNone(val_input.current_price)

        record_call = self.mock_analysis.run_db.record_task_state.call_args_list[-1]
        metadata = record_call[1]["metadata"]
        self.assertTrue(any("currency mismatch EUR != USD" in w for w in metadata["normalization_warnings"]))

    def test_instrument_mismatch_rejected(self):
        obs = ProviderObservation(
            evidence_type="market",
            source_name="test_source",
            source_url="http://test",
            source_tier=1,
            provider_id="test",
            instrument_id="MSFT", # mismatch
            value="150.0",
            currency="USD",
            unit="USD",
            observed_at="2024-03-31T20:00:00Z"
        )
        self._setup_market_outcome(obs)
        self.runtime.freshness.assess.return_value = FreshnessAssessment(FreshnessStatus.FRESH, "2024-03-31T20:00:00Z", 14400, "ok")

        outcome = self.runtime.analyze_equity(self.spec)

        val_input = self.mock_analysis.analyze_equity.call_args[0][1]
        self.assertIsNone(val_input.current_price)

        record_call = self.mock_analysis.run_db.record_task_state.call_args_list[-1]
        metadata = record_call[1]["metadata"]
        self.assertTrue(any("instrument mismatch MSFT != AAPL" in w for w in metadata["normalization_warnings"]))

    def test_missing_observation_time_rejected(self):
        obs = ProviderObservation(
            evidence_type="market",
            source_name="test_source",
            source_url="http://test",
            source_tier=1,
            provider_id="test",
            instrument_id="AAPL",
            value="150.0",
            currency="USD",
            unit="USD",
            observed_at=None # missing time
        )
        self._setup_market_outcome(obs)
        self.runtime.freshness.assess.return_value = FreshnessAssessment(FreshnessStatus.FRESH, None, None, "ok")

        outcome = self.runtime.analyze_equity(self.spec)

        val_input = self.mock_analysis.analyze_equity.call_args[0][1]
        self.assertIsNone(val_input.current_price)

        record_call = self.mock_analysis.run_db.record_task_state.call_args_list[-1]
        metadata = record_call[1]["metadata"]
        self.assertTrue(any("missing observation time" in w for w in metadata["normalization_warnings"]))


if __name__ == "__main__":
    unittest.main()
