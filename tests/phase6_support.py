from __future__ import annotations

import tempfile
from pathlib import Path

from investment_stack.evidence import RunDatabaseManager


class Phase6RunFixture:
    cutoff = "2026-08-14T10:00:00+00:00"

    def make_run(self, run_id: str = "phase6-run"):
        temp = tempfile.TemporaryDirectory()
        manager = RunDatabaseManager(Path(temp.name) / "workspace", run_id)
        assert manager.create().valid
        manager.initialize_run_context(
            request_mode="SINGLE_ASSET_ANALYSIS",
            analysis_as_of=self.cutoff,
            analysis_timezone="Asia/Seoul",
            state_version=7,
            personal_db_instance_id="personal-instance",
            portfolio_data_as_of="2026-08-14T08:00:00+00:00",
        )
        return temp, manager


def add_market(manager: RunDatabaseManager, *, evidence_id: str = "e-market", freshness: str = "FRESH", observed_at: str | None = "2026-08-14T09:59:00+00:00", confirmation: str = "OFFICIAL", selected: bool = True):
    manager.add_phase4_evidence(
        evidence_id=evidence_id,
        evidence_type="market",
        source_uri="https://market.test/quote",
        retrieved_at="2026-08-14T10:00:00+00:00",
        instrument_id="TEST",
        metric="current_price",
        value="100",
        unit="PRICE",
        currency="USD",
        source_name="Official Market",
        source_tier=1,
        observed_at=observed_at,
        freshness_status=freshness,
        provider_id="market",
        official_confirmation_status=confirmation,
        metadata={},
    )
    manager.add_market_observation(
        observation_id=f"obs-{evidence_id}",
        evidence_id=evidence_id,
        instrument_id="TEST",
        observed_at=observed_at,
        value="100",
        unit="PRICE",
        currency="USD",
        claimed_market_time=observed_at,
        market_session_date="2026-08-14",
        provider_id="market",
        freshness_status=freshness,
        metadata={},
    )
    if selected:
        manager.mark_evidence_selected(evidence_id=evidence_id, reason="test selected")


def add_financial(manager: RunDatabaseManager, evidence_id: str = "e-fin"):
    manager.add_phase4_evidence(
        evidence_id=evidence_id,
        evidence_type="financial",
        source_uri="https://filing.test/1",
        retrieved_at="2026-08-14T10:00:00+00:00",
        instrument_id="TEST",
        metric="revenue",
        value="1000",
        unit="USD",
        currency="USD",
        source_name="Official Filing",
        source_tier=1,
        published_at="2026-08-13T00:00:00+00:00",
        freshness_status="FRESH",
        provider_id="filing",
        official_confirmation_status="OFFICIAL",
        metadata={"period_end": "2026-06-30"},
    )
    manager.add_financial_observation(
        observation_id=f"obs-{evidence_id}", evidence_id=evidence_id, metric_name="revenue",
        period_end="2026-06-30", value="1000", unit="USD", currency="USD", provider_id="filing", metadata={},
    )
    manager.mark_evidence_selected(evidence_id=evidence_id, reason="test selected")


def add_macro(manager: RunDatabaseManager, evidence_id: str = "e-macro"):
    manager.add_phase4_evidence(
        evidence_id=evidence_id,
        evidence_type="macro",
        source_uri="https://macro.test/1",
        retrieved_at="2026-08-14T10:00:00+00:00",
        metric="real_rate",
        value="1.5",
        unit="PERCENT",
        source_name="Central Bank",
        source_tier=1,
        observed_at="2026-08-12T00:00:00+00:00",
        freshness_status="FRESH",
        provider_id="macro",
        official_confirmation_status="OFFICIAL",
        metadata={},
    )
    manager.add_macro_observation(
        observation_id=f"obs-{evidence_id}", evidence_id=evidence_id, series_name="real_rate",
        observed_at="2026-08-12T00:00:00+00:00", value="1.5", unit="PERCENT", currency=None, provider_id="macro", metadata={},
    )
    manager.mark_evidence_selected(evidence_id=evidence_id, reason="test selected")
