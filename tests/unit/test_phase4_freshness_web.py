from __future__ import annotations

import unittest
from datetime import timedelta

from investment_stack.freshness import FreshnessEngine, FreshnessPolicy, FreshnessStatus
from investment_stack.providers import ProviderObservation, ProviderStatus
from investment_stack.web_research import WebResearchAdapter, WebResearchHit, WebResearchIntent, WebResearchResponse


class FreshnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = FreshnessEngine(FreshnessPolicy(timedelta(minutes=15), timedelta(hours=2)))
        self.cutoff = "2026-08-14T10:00:00+00:00"

    def obs(self, **kwargs):
        base = dict(evidence_type="market", source_name="official", source_url="https://example.test", source_tier=1, provider_id="p", value="1")
        base.update(kwargs)
        return ProviderObservation(**base)

    def test_retrieved_at_does_not_replace_observed_at(self) -> None:
        assessment = self.engine.assess(self.obs(retrieved_at=self.cutoff), analysis_as_of=self.cutoff)
        self.assertEqual(assessment.status, FreshnessStatus.UNKNOWN)

    def test_future_observation_is_unavailable(self) -> None:
        assessment = self.engine.assess(self.obs(observed_at="2026-08-14T10:01:00+00:00"), analysis_as_of=self.cutoff)
        self.assertEqual(assessment.status, FreshnessStatus.UNAVAILABLE)

    def test_latest_as_of_excludes_future(self) -> None:
        old = self.obs(observed_at="2026-08-14T09:59:00+00:00", value="old")
        future = self.obs(observed_at="2026-08-14T10:01:00+00:00", value="future")
        self.assertEqual(self.engine.latest_as_of([future, old], analysis_as_of=self.cutoff).value, "old")


class WebResearchTests(unittest.TestCase):
    cutoff = "2026-08-14T10:00:00+00:00"

    def test_article_price_and_undated_page_are_not_current_price(self) -> None:
        def backend(intent, query, cutoff):
            return WebResearchResponse(intent, (
                WebResearchHit("News", "https://news.test/a", "article", value="100", published_at="2026-08-14T09:00:00+00:00", source_kind="news_article"),
                WebResearchHit("Page", "https://page.test/a", "undated", value="101", source_kind="undated_page"),
            ))
        result = WebResearchAdapter(backend).fetch_current("TEST", analysis_as_of=self.cutoff)
        self.assertEqual(result.status, ProviderStatus.UNAVAILABLE)

    def test_timestamped_structured_page_can_supply_latest_as_of(self) -> None:
        def backend(intent, query, cutoff):
            return WebResearchResponse(intent, (
                WebResearchHit("Exchange", "https://exchange.test/q", "quote", value="101", claimed_market_time="2026-08-14T09:59:00+00:00", source_kind="official_exchange", source_tier=1),
            ))
        result = WebResearchAdapter(backend).fetch_current("TEST", analysis_as_of=self.cutoff)
        self.assertEqual(result.status, ProviderStatus.AVAILABLE)
        self.assertEqual(result.observations[0].value, "101")

    def test_news_deduplicates_event_cluster_and_cutoff(self) -> None:
        def backend(intent, query, cutoff):
            self.assertEqual(intent, WebResearchIntent.LATEST_RELEVANT_NEWS)
            return WebResearchResponse(intent, (
                WebResearchHit("IR", "https://ir.test/1", "confirmed", published_at="2026-08-14T09:00:00+00:00", source_kind="official_ir", event_cluster_id="evt1", official_confirmation_status="OFFICIAL"),
                WebResearchHit("Media", "https://media.test/1", "duplicate", published_at="2026-08-14T09:05:00+00:00", source_kind="news_article", event_cluster_id="evt1"),
                WebResearchHit("Future", "https://media.test/f", "future", published_at="2026-08-14T10:01:00+00:00", source_kind="news_article", event_cluster_id="evt2"),
            ))
        result = WebResearchAdapter(backend).fetch_news("TEST", analysis_as_of=self.cutoff)
        self.assertEqual(result.status, ProviderStatus.AVAILABLE)
        self.assertEqual(len(result.observations), 1)
        self.assertEqual(result.observations[0].event_cluster_id, "evt1")

    def test_news_reported_financial_number_is_not_approved_calculation_input(self) -> None:
        def backend(intent, query, cutoff):
            return WebResearchResponse(intent, (
                WebResearchHit(
                    "Media", "https://media.test/financial", "reported revenue",
                    value="500", published_at="2026-08-14T09:00:00+00:00",
                    source_kind="news_article",
                ),
            ))
        result = WebResearchAdapter(backend).fetch_latest_data(
            "TEST revenue", capability=__import__("investment_stack.providers", fromlist=["ProviderCapability"]).ProviderCapability.FUNDAMENTALS,
            analysis_as_of=self.cutoff, evidence_type="financial", metric="Revenue",
        )
        self.assertEqual(result.status, ProviderStatus.PARTIAL)
        self.assertEqual(result.observations[0].official_confirmation_status, "NEWS_REPORTED")
        self.assertFalse(result.observations[0].metadata["calculation_input_approved"])


if __name__ == "__main__":
    unittest.main()
