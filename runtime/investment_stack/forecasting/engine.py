from __future__ import annotations

from typing import Mapping, Sequence

from .adapters.base import ForecastAdapter
from .contracts import EnsembleForecast, ForecastRequest, FundamentalAnchor, ModelForecast
from .ensemble import ForecastEnsembler
from .store import ForecastStore


class ForecastingEngine:
    """Optional post-valuation forecasting layer.

    It must never overwrite verified fundamental/valuation evidence. Model outputs are
    stored separately and blended only in the decision/report layer.
    """

    def __init__(self, adapters: Sequence[ForecastAdapter], ensembler: ForecastEnsembler | None = None):
        self.adapters = tuple(adapters)
        self.ensembler = ensembler or ForecastEnsembler()

    def run(
        self,
        request: ForecastRequest,
        anchor: FundamentalAnchor | None,
        reliability: Mapping[str, float] | None = None,
        run_db_path: str | None = None,
        run_id: str | None = None,
    ) -> tuple[EnsembleForecast, Sequence[ModelForecast]]:
        request.validate()
        # Anchor eligibility is established by the ensembler. Pre-validating
        # here would crash peer forecasts on rejected/invalid anchors.
        results = []
        for adapter in self.adapters:
            try:
                res = adapter.forecast(request)
                res.validate()
                if (res.instrument_id != request.instrument_id or res.currency != request.currency
                    or res.as_of != request.as_of or res.target_date != request.target_date
                    or res.price_basis != request.metadata["price_basis"]
                    or res.horizon_steps != request.horizon_steps or res.frequency != request.frequency
                    or res.target_semantics != request.target_semantics):
                    raise ValueError("Adapter output bindings mismatch")
                results.append(res)
            except Exception as e:
                model_id = getattr(adapter, "model_id", "unknown-adapter")
                results.append(ModelForecast(
                    model_id=model_id, status="ERROR", error=f"{type(e).__name__}: {e}",
                    instrument_id=request.instrument_id, currency=request.currency,
                    as_of=request.as_of, target_date=request.target_date,
                    price_basis=request.metadata.get("price_basis", "nominal"),
                    horizon_steps=request.horizon_steps, frequency=request.frequency,
                    target_semantics=request.target_semantics
                ))
        combined = self.ensembler.combine(request, results, anchor, reliability)
        
        assessment = None
        if combined.point is not None and request.history and len(request.history) >= 30:
            current = request.current_price
            if current > 0 and combined.point > 0:
                try:
                    from .monte_carlo import simulate_terminal_distribution
                    time_diff = request.target_date - request.as_of
                    years = time_diff.total_seconds() / (365.25 * 86400)
                    
                    if request.frequency == 'ME': steps_yr = 12
                    elif request.frequency.startswith('W'): steps_yr = 52
                    else: steps_yr = 252
                    
                    mc = simulate_terminal_distribution(
                        current_price=float(current),
                        target_median=float(combined.point),
                        historical_prices=request.history,
                        horizon_steps=request.horizon_steps,
                        history_frequency_steps_per_year=steps_yr,
                        horizon_years=years
                    )
                    
                    model_points = [c.point for c in combined.components if c.status == "COMPLETE" and c.point is not None and combined.component_weights.get(c.model_id, 0) > 0]
                    if len(model_points) > 1:
                        model_disagreement = float(max(model_points) - min(model_points))
                    else:
                        model_disagreement = None
                    
                    cfv = request.metadata.get("current_fair_value")
                    if cfv is not None:
                        try:
                            import math
                            if isinstance(cfv, bool): raise ValueError()
                            cfv_f = float(cfv)
                            if math.isnan(cfv_f) or math.isinf(cfv_f): raise ValueError()
                            cfv = cfv_f
                        except:
                            cfv = "UNAVAILABLE"
                        
                    actual_elapsed_years = years
                    
                    assessment = {
                        "status": "CONDITIONAL",
                        "ranking_allowed": False,
                        "ranking_withheld_reasons": ["Synthetic MC risk is conditional and cannot authorize automated investment ranking.", "Unverified components missing full risk validation."],
                        "model_disagreement_dispersion": model_disagreement,
                        "current_fair_value_metadata_unverified": cfv,
                        "horizon_nominal_steps": request.horizon_steps,
                        "actual_elapsed_years": actual_elapsed_years,
                        "annualization_convention": "actual elapsed 365.25 days/year",
                        "paths": mc.paths,
                        "terminal_quantiles": mc.terminal_quantiles,
                        "loss_probability": mc.loss_probability,
                        "representative_price_cagr": mc.representative_price_cagr,
                        "median_cagr": mc.median_cagr,
                        "expected_cumulative_return": mc.expected_cumulative_return,
                        "expected_cagr": mc.expected_cagr,
                        "assumptions": mc.assumptions + " WARNING: Conditional synthetic distribution. Model disagreement and extreme event risk uncalibrated."
                    }
                    if combined.status == "PARTIAL":
                        assessment["limitations"] = "Conditional assessment based on partial ensemble; model set incomplete."
                except Exception as e:
                    assessment = {"status": "ERROR", "reason": f"{type(e).__name__}: {e}", "ranking_allowed": False, "ranking_withheld_reasons": [str(e)]}
            else:
                assessment = {"status": "UNAVAILABLE", "reason": "Current price or combined point is invalid.", "ranking_allowed": False, "ranking_withheld_reasons": ["Invalid price"]}
        else:
            reason = ""
            if combined.point is None:
                reason += "No ensemble point estimate available. "
            if not request.history or len(request.history) < 30:
                reason += "Insufficient history (requires at least 30 observations). "
            assessment = {"status": "UNAVAILABLE", "reason": reason.strip(), "ranking_allowed": False, "ranking_withheld_reasons": [reason.strip()]}

        if run_db_path and run_id:
            store = ForecastStore(run_db_path)
            # Preserve all adapter results for audit; active synthetic anchor is a
            # first-class component and must be persisted in the same transaction.
            by_id = {f.model_id: f for f in results}
            for component in combined.components:
                if component.model_id == "fundamental-anchor":
                    by_id[component.model_id] = component
            store.save_bundle(run_id, request.instrument_id, tuple(by_id.values()), combined, assessment)
        
        # Optionally attach assessment to combined details for caller
        if assessment:
            import dataclasses
            new_details = dict(combined.details or {})
            new_details["assessment"] = assessment
            combined = dataclasses.replace(combined, details=new_details)
            
        return combined, tuple(results)
