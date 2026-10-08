from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

import numpy as np

from investment_stack.forecasting.adapters.base import ForecastAdapter
from investment_stack.forecasting.contracts import ForecastRequest, FundamentalAnchor, ModelForecast
from investment_stack.forecasting.engine import ForecastingEngine
from investment_stack.evidence.manager import RunDatabaseManager
from investment_stack.forecasting.ensemble import ForecastEnsembler
from investment_stack.forecasting.monte_carlo import simulate_terminal_distribution


class FakeAdapter(ForecastAdapter):
    def __init__(self, model_id, point, qs=None, status="COMPLETE"):
        self.model_id = model_id
        self.point = point
        self.qs = qs or {}
        self.status = status

    def available(self):
        return True, None

    def forecast(self, request):
        return ModelForecast(
            self.model_id, self.status, request.instrument_id, request.currency, request.as_of,
            request.target_date, "split-adjusted", request.horizon_steps, request.frequency,
            point=self.point, quantiles=self.qs
        )


def req():
    return ForecastRequest(
        instrument_id="TEST",
        currency="USD",
        as_of=datetime(2026, 10, 5, tzinfo=timezone.utc),
        current_price=100.0,
        target_date=datetime(2027, 9, 30, tzinfo=timezone.utc),
        horizon_steps=12,
        frequency="ME",
        metadata={"price_basis":"split-adjusted"},
        history=tuple(np.linspace(80, 100, 60)),
        timestamps=tuple(pd.date_range(end="2026-09-30", periods=60, freq="ME", tz="UTC").to_pydatetime())
    )


def test_anchor_keeps_control():
    anchor = FundamentalAnchor("COMPLETE", "TEST", "USD", datetime(2027, 9, 30, tzinfo=timezone.utc), "split-adjusted", bear=90, base=120, bull=160, value_kind="terminal_price", evidence_refs=("test-doc",), assumption_refs=("test-assumption",), as_of=req().as_of)
    fs = [
        ModelForecast("autogluon/chronos-2-small", "COMPLETE", "TEST", "USD", datetime(2026, 10, 5, tzinfo=timezone.utc), datetime(2027, 9, 30, tzinfo=timezone.utc), "split-adjusted", 12, "ME", point=140, quantiles={0.1: 100, 0.5: 140, 0.9: 190}),
        ModelForecast("NeoQuasar/Kronos-mini", "COMPLETE", "TEST", "USD", datetime(2026, 10, 5, tzinfo=timezone.utc), datetime(2027, 9, 30, tzinfo=timezone.utc), "split-adjusted", 12, "ME", point=150),
    ]
    out = ForecastEnsembler().combine(req(), fs, anchor)
    assert out.status == "COMPLETE"
    assert 120 < out.point < 150
    assert abs(sum(out.component_weights.values()) - 1) < 1e-9


def test_engine_degrades_when_models_missing():
    anchor = FundamentalAnchor("COMPLETE", "TEST", "USD", datetime(2027, 9, 30, tzinfo=timezone.utc), "split-adjusted", bear=90, base=120, bull=160, value_kind="terminal_price", evidence_refs=("test-doc",), assumption_refs=("test-assumption",), as_of=req().as_of)
    engine = ForecastingEngine([FakeAdapter("bad", None, status="UNAVAILABLE")])
    out, parts = engine.run(req(), anchor)
    assert out.status == "PARTIAL"
    assert abs(out.point - 120) < 1e-9
    assert len(parts) == 1


def test_store_persists(tmp_path: Path):
    manager = RunDatabaseManager(tmp_path, "r1")
    manager.create()
    manager.initialize_run_context(request_mode="test", analysis_as_of=req().as_of.isoformat(), analysis_timezone="UTC")
    db = manager._operational_database_path()
    with sqlite3.connect(db) as con:
        con.execute("INSERT INTO instrument_resolutions (resolution_id,run_id,requested_identifier,resolved_identifier,resolution_status) VALUES (?,?,?,?,?)",("res-test","r1","TEST","TEST","RESOLVED"))
    engine = ForecastingEngine([FakeAdapter("autogluon/chronos-2-small", 130, {0.1: 95, 0.5: 130, 0.9: 175})])
    out, _ = engine.run(req(), FundamentalAnchor("COMPLETE", "TEST", "USD", datetime(2027, 9, 30, tzinfo=timezone.utc), "split-adjusted", "terminal_price", bear=90, base=120, bull=160, evidence_refs=("test-doc",), assumption_refs=("test-assumption",), as_of=req().as_of), run_db_path=str(db), run_id="r1")
    con = sqlite3.connect(db)
    assert con.execute("select count(*) from forecast_model_runs").fetchone()[0] == 2
    assert con.execute("select count(*) from forecast_ensembles").fetchone()[0] == 1
    con.close()


def test_monte_carlo_is_deterministic():
    hist = np.exp(np.linspace(np.log(70), np.log(100), 120))
    a = simulate_terminal_distribution(100, 140, hist, 12, paths=1000, seed=11)
    b = simulate_terminal_distribution(100, 140, hist, 12, paths=1000, seed=11)
    assert a.terminal_quantiles == b.terminal_quantiles
    assert 0 <= a.loss_probability <= 1
