import sqlite3
from datetime import datetime, timezone
import numpy as np
from pathlib import Path
import pandas as pd

from investment_stack.forecasting.scenario import TerminalScenarioInput, calculate_terminal_scenario
from investment_stack.forecasting.contracts import ForecastRequest, FundamentalAnchor
from investment_stack.forecasting.engine import ForecastingEngine
from investment_stack.evidence.manager import RunDatabaseManager
from investment_stack.forecasting.adapters.base import ForecastAdapter
from investment_stack.forecasting.contracts import ModelForecast
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

def test_full_core_workflow(tmp_path: Path):
    # 1. Create a future-fundamental scenario
    scenario_input = TerminalScenarioInput(
        horizon_years=5,
        revenue_growth_cagr=0.1,
        terminal_multiple=15.0,
        terminal_multiple_metric="fcf",
        fcf_basis="fcff",
        multiple_target="enterprise",
        current_revenue=1000.0,
        fcf_margin=0.2,
        terminal_net_debt=500.0,
        fully_diluted_shares=100.0,
        source_refs=["doc1"]
    )
    res = calculate_terminal_scenario(scenario_input)
    assert res.terminal_value_per_share > 0

    # 2. Use it as an anchor
    anchor = FundamentalAnchor(
        "COMPLETE", "AAPL", "USD", datetime(2031, 9, 30, tzinfo=timezone.utc), "split-adjusted",
        value_kind="terminal_price",
        bear=res.terminal_value_per_share * 0.8,
        base=res.terminal_value_per_share,
        bull=res.terminal_value_per_share * 1.2,
        assumption_refs=["doc1"],
        evidence_refs=["doc1"],
        as_of=datetime(2026, 10, 5, tzinfo=timezone.utc)
    )

    # 3. Setup Request
    req = ForecastRequest(
        instrument_id="AAPL",
        currency="USD",
        as_of=datetime(2026, 10, 5, tzinfo=timezone.utc),
        current_price=150.0,
        target_date=datetime(2031, 9, 30, tzinfo=timezone.utc),
        horizon_steps=60,
        frequency="ME",
        metadata={"price_basis":"split-adjusted"},
        history=tuple(np.linspace(100, 150, 60)),
        timestamps=tuple(pd.date_range(end="2026-09-30", periods=60, freq="ME", tz="UTC").to_pydatetime())
    )

    # 4. Engine with injected model adapters
    engine = ForecastingEngine([
        FakeAdapter("xgboost-tabular-5y", res.terminal_value_per_share * 0.9, {0.1: res.terminal_value_per_share * 0.7, 0.5: res.terminal_value_per_share * 0.9, 0.9: res.terminal_value_per_share * 1.1}),
        FakeAdapter("lightgbm-tabular-5y", res.terminal_value_per_share * 1.05)
    ])

    # 5. Storage setup
    manager = RunDatabaseManager(tmp_path, "r1")
    manager.create()
    manager.initialize_run_context(request_mode="test", analysis_as_of=req.as_of.isoformat(), analysis_timezone="UTC")
    db = manager._operational_database_path()
    with sqlite3.connect(db) as con:
        con.execute("INSERT INTO instrument_resolutions (resolution_id,run_id,requested_identifier,resolved_identifier,resolution_status) VALUES (?,?,?,?,?)",("res-test","r1","AAPL","AAPL","RESOLVED"))

    # 6. Run Ensemble
    out, parts = engine.run(req, anchor, run_db_path=str(db), run_id="r1")
    assert out.status == "COMPLETE"
    assert out.point is not None

    # 7. Uncertainty/Assessment (Monte Carlo)
    assessment = simulate_terminal_distribution(
        current_price=req.current_price,
        target_median=out.point,
        historical_prices=np.array(req.history),
        horizon_steps=req.horizon_steps
    )
    assert assessment.terminal_quantiles
    assert assessment.expected_cagr is not None
