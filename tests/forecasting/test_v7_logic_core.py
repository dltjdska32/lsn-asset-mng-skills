from datetime import datetime, timezone
import pytest

from investment_stack.forecasting.contracts import ForecastRequest, FundamentalAnchor, ModelForecast, EnsembleForecast
from investment_stack.forecasting.scenario import TerminalScenarioInput, calculate_terminal_scenario

def test_forecast_request_covariates_validation():
    # Historical without timestamp bindings should fail
    req1 = ForecastRequest(
        instrument_id="X", currency="USD", as_of=datetime(2020, 1, 1, tzinfo=timezone.utc),
        current_price=10.0, target_date=datetime(2020, 12, 31, tzinfo=timezone.utc),
        horizon_steps=1, frequency="YE", target_semantics="terminal_price",
        covariates={"gdp": [1, 2, 3]}, metadata={"price_basis": "split-adjusted"}
    )
    with pytest.raises(ValueError, match="mandatory publication/timestamp bindings"):
        req1.validate()

    import pandas as pd
    ts = list(pd.date_range(end=datetime(2020, 1, 1, tzinfo=timezone.utc), periods=8, freq="YE").to_pydatetime())
    # Future covariate should be rejected completely
    req2 = ForecastRequest(
        instrument_id="X", currency="USD", as_of=datetime(2020, 1, 1, tzinfo=timezone.utc),
        current_price=10.0, target_date=datetime(2020, 12, 31, tzinfo=timezone.utc),
        horizon_steps=1, frequency="YE", target_semantics="terminal_price",
        history=[10.0 + i for i in range(8)],
        timestamps=ts,
        covariates={"gdp": [1]*8}, 
        metadata={"price_basis": "split-adjusted", 
                  "covariate_timestamps": ts[:-1] + [datetime(2025, 1, 1, tzinfo=timezone.utc)],
                  "covariate_publication": ts}
    )
    with pytest.raises(ValueError, match="publication before observation timestamp|future covariates explicitly rejected"):
        req2.validate()

    # Valid covariates
    req3 = ForecastRequest(
        instrument_id="X", currency="USD", as_of=datetime(2020, 1, 1, tzinfo=timezone.utc),
        current_price=10.0, target_date=datetime(2020, 12, 31, tzinfo=timezone.utc),
        horizon_steps=1, frequency="YE", target_semantics="terminal_price",
        history=[10.0 + i for i in range(8)],
        timestamps=ts,
        covariates={"gdp": [1]*8}, 
        metadata={"price_basis": "split-adjusted", 
                  "covariate_timestamps": ts,
                  "covariate_publication": ts}
    )
    req3.validate()  # should not raise

def test_fundamental_anchor_explicit_value_kind():
    # Should fail if value_kind is missing or invalid
    with pytest.raises(ValueError):
        anchor = FundamentalAnchor(
            status="COMPLETE", instrument_id="X", currency="USD",
            target_date=datetime(2025, 1, 1, tzinfo=timezone.utc), price_basis="split-adjusted",
            value_kind="nonsense"
        )
        anchor.validate()

    # Should reject current_fair_value for terminal anchor in ensemble
    anchor2 = FundamentalAnchor(
        status="COMPLETE", instrument_id="X", currency="USD",
        target_date=datetime(2025, 1, 1, tzinfo=timezone.utc), price_basis="split-adjusted",
        value_kind="current_fair_value", bear=10, base=12, bull=15,
        assumption_refs=["ref1"], evidence_refs=["ref2"]
    )
    anchor2.validate()  # valid on its own
    
    # but Ensemble should reject it
    ens = EnsembleForecast(
        instrument_id="X", currency="USD", as_of=datetime(2024, 1, 1, tzinfo=timezone.utc),
        target_date=datetime(2025, 1, 1, tzinfo=timezone.utc), price_basis="split-adjusted",
        horizon_steps=1, frequency="YE", status="COMPLETE", point=12, quantiles={},
        component_weights={}, components=[], anchor=anchor2
    )
    with pytest.raises(ValueError, match="current fair value cannot be used as terminal anchor"):
        ens.validate()

def test_scenario_fcf_basis():
    # FCFF requires enterprise
    inp1 = TerminalScenarioInput(
        horizon_years=5, revenue_growth_cagr=0.1, terminal_multiple=10,
        terminal_multiple_metric="fcf", multiple_target="equity",
        current_revenue=100, terminal_net_debt=50, fully_diluted_shares=10,
        source_refs=["ref"], fcf_margin=0.2, fcf_basis="fcff"
    )
    with pytest.raises(ValueError, match="FCFF requires enterprise"):
        calculate_terminal_scenario(inp1)

    # FCFE requires equity
    inp2 = TerminalScenarioInput(
        horizon_years=5, revenue_growth_cagr=0.1, terminal_multiple=10,
        terminal_multiple_metric="fcf", multiple_target="enterprise",
        current_revenue=100, terminal_net_debt=50, fully_diluted_shares=10,
        source_refs=["ref"], fcf_margin=0.2, fcf_basis="fcfe"
    )
    with pytest.raises(ValueError, match="FCFE requires equity"):
        calculate_terminal_scenario(inp2)

def test_engine_assessment():
    from investment_stack.forecasting.engine import ForecastingEngine
    from investment_stack.forecasting.adapters.base import ForecastAdapter
    class DummyAdapter(ForecastAdapter):
        model_id = "autogluon/chronos-2-small"
        def available(self):
            return True
        def forecast(self, request):
            return ModelForecast("autogluon/chronos-2-small", "COMPLETE", request.instrument_id, request.currency, request.as_of, request.target_date, request.metadata["price_basis"], request.horizon_steps, request.frequency, point=120)
    
    engine = ForecastingEngine([DummyAdapter()])
    import pandas as pd
    timestamps = list(pd.date_range(end=datetime(2020, 1, 1, tzinfo=timezone.utc), periods=30, freq="ME").to_pydatetime())
    req = ForecastRequest(
        instrument_id="X", currency="USD", as_of=datetime(2020, 1, 1, tzinfo=timezone.utc),
        current_price=100.0, target_date=datetime(2020, 12, 31, tzinfo=timezone.utc),
        horizon_steps=12, frequency="ME", target_semantics="terminal_price",
        history=[100.0 + i for i in range(30)], timestamps=timestamps,
        metadata={"price_basis": "split-adjusted"}
    )
    out, _ = engine.run(req, None)
    
    print(out.details["assessment"])
    assert out.details["assessment"]["ranking_allowed"] is False
    assert len(out.details["assessment"]["ranking_withheld_reasons"]) > 0
    assert out.details["assessment"]["horizon_nominal_steps"] == 12
    assert "actual_elapsed_years" in out.details["assessment"]

def test_engine_failing_adapter():
    from investment_stack.forecasting.engine import ForecastingEngine
    from investment_stack.forecasting.adapters.base import ForecastAdapter
    class DummyHealthy(ForecastAdapter):
        model_id = "autogluon/chronos-2-small"
        def available(self): return True
        def forecast(self, request):
            return ModelForecast("autogluon/chronos-2-small", "COMPLETE", request.instrument_id, request.currency, request.as_of, request.target_date, request.metadata["price_basis"], request.horizon_steps, request.frequency, point=120)
    class DummyFailing(ForecastAdapter):
        model_id = "failing"
        def available(self): return True
        def forecast(self, request):
            raise RuntimeError("some internal failure")
    
    engine = ForecastingEngine([DummyHealthy(), DummyFailing()])
    import pandas as pd
    timestamps = list(pd.date_range(end=datetime(2020, 1, 1, tzinfo=timezone.utc), periods=30, freq="ME").to_pydatetime())
    req = ForecastRequest(
        instrument_id="X", currency="USD", as_of=datetime(2020, 1, 1, tzinfo=timezone.utc),
        current_price=100.0, target_date=datetime(2020, 12, 31, tzinfo=timezone.utc),
        horizon_steps=12, frequency="ME", target_semantics="terminal_price",
        history=[100.0 + i for i in range(30)], timestamps=timestamps,
        metadata={"price_basis": "split-adjusted"}
    )
    out, results = engine.run(req, None)
    # The healthy adapter succeeded, the failing one returned an ERROR forecast
    assert len(results) == 2
    failing_res = next(r for r in results if r.model_id == "failing")
    assert failing_res.status == "ERROR"
    assert "some internal failure" in failing_res.error
    
    healthy_res = next(r for r in results if r.model_id == "autogluon/chronos-2-small")
    assert healthy_res.status == "COMPLETE"
    
    assert out.status == "PARTIAL"
    assert round(out.point) == 120

