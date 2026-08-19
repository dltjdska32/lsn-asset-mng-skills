"""Asset-specific Bitcoin, gold and silver analysis without corporate valuation."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Mapping

from investment_stack.calculations.common import AnalysisResult, AnalysisStatus, MetricResult, max_drawdown, sample_stddev, simple_returns


class AlternativeAsset(StrEnum):
    BITCOIN = "BITCOIN"
    GOLD = "GOLD"
    SILVER = "SILVER"


@dataclass(frozen=True, slots=True)
class AlternativeAssetInput:
    instrument_id: str
    asset: AlternativeAsset
    wrapper: str
    custody_or_account: str | None
    price_series: tuple[Decimal, ...]
    quote_currency: str
    venue: str | None = None
    price_as_of: str | None = None
    physical_premium: Decimal | None = None
    real_rate: Decimal | None = None
    usd_index_change: Decimal | None = None
    industrial_demand_change: Decimal | None = None
    liquidity_score: Decimal | None = None
    supply_metric: Decimal | None = None
    network_activity_change: Decimal | None = None
    regulatory_status: str | None = None
    context: Mapping[str, object] = field(default_factory=dict)
    evidence_ids: tuple[str, ...] = ()


class AlternativeAssetAnalyzer:
    def analyze(self, data: AlternativeAssetInput) -> AnalysisResult:
        if not data.wrapper.strip():
            raise ValueError("alternative asset wrapper must be explicit")
        returns = simple_returns(data.price_series) if len(data.price_series) >= 2 else ()
        period_return = None
        if len(data.price_series) >= 2:
            period_return = (data.price_series[-1] / data.price_series[0]) - Decimal("1")
        metrics = [
            MetricResult("period_return", period_return, "ratio", "last_price / first_price - 1", AnalysisStatus.COMPLETE if period_return is not None else AnalysisStatus.UNAVAILABLE, evidence_ids=data.evidence_ids),
            MetricResult("return_volatility", sample_stddev(returns), "ratio", "sample_stddev(simple_returns)", AnalysisStatus.COMPLETE if len(returns) >= 2 else AnalysisStatus.UNAVAILABLE, evidence_ids=data.evidence_ids),
            MetricResult("max_drawdown", max_drawdown(data.price_series), "ratio", "min(price / running_peak - 1)", AnalysisStatus.COMPLETE if data.price_series else AnalysisStatus.UNAVAILABLE, evidence_ids=data.evidence_ids),
        ]
        unknowns: list[str] = []
        risks: list[str] = []
        findings: list[str] = [f"wrapper: {data.wrapper}", f"quote currency: {data.quote_currency}"]
        metadata: dict[str, object] = {"asset": data.asset.value, "wrapper": data.wrapper, "price_as_of": data.price_as_of}

        if data.asset is AlternativeAsset.BITCOIN:
            if not data.venue:
                unknowns.append("venue")
            else:
                findings.append(f"venue-specific quote context: {data.venue}")
            if not data.custody_or_account:
                unknowns.append("custody_or_account")
            metrics.extend([
                MetricResult("liquidity_score", data.liquidity_score, "score", "validated_liquidity_input", AnalysisStatus.COMPLETE if data.liquidity_score is not None else AnalysisStatus.UNAVAILABLE, evidence_ids=data.evidence_ids),
                MetricResult("supply_metric", data.supply_metric, "asset_units", "validated_supply_input", AnalysisStatus.COMPLETE if data.supply_metric is not None else AnalysisStatus.UNAVAILABLE, evidence_ids=data.evidence_ids),
                MetricResult("network_activity_change", data.network_activity_change, "ratio", "validated_network_metric_change", AnalysisStatus.COMPLETE if data.network_activity_change is not None else AnalysisStatus.UNAVAILABLE, evidence_ids=data.evidence_ids),
            ])
            if data.regulatory_status:
                findings.append(f"regulatory context: {data.regulatory_status}")
            risks.extend(["protocol/regulatory risk", "custody/counterparty risk", "24/7 market liquidity can vary by venue"])
            metadata["corporate_valuation_allowed"] = False
        elif data.asset is AlternativeAsset.GOLD:
            metrics.extend([
                MetricResult("physical_premium", data.physical_premium, "ratio", "user_or_market_supplied_physical_premium", AnalysisStatus.COMPLETE if data.physical_premium is not None else AnalysisStatus.UNAVAILABLE, evidence_ids=data.evidence_ids),
                MetricResult("real_rate_context", data.real_rate, "rate", "official_macro_input", AnalysisStatus.COMPLETE if data.real_rate is not None else AnalysisStatus.UNAVAILABLE, evidence_ids=data.evidence_ids),
                MetricResult("usd_change_context", data.usd_index_change, "ratio", "official_or_validated_market_input", AnalysisStatus.COMPLETE if data.usd_index_change is not None else AnalysisStatus.UNAVAILABLE, evidence_ids=data.evidence_ids),
            ])
            risks.extend(["real-rate sensitivity", "currency sensitivity", "physical premium/storage risk depends on wrapper"])
            metadata["corporate_valuation_allowed"] = False
        else:
            metrics.extend([
                MetricResult("physical_premium", data.physical_premium, "ratio", "user_or_market_supplied_physical_premium", AnalysisStatus.COMPLETE if data.physical_premium is not None else AnalysisStatus.UNAVAILABLE, evidence_ids=data.evidence_ids),
                MetricResult("industrial_demand_change", data.industrial_demand_change, "ratio", "validated_industrial_demand_input", AnalysisStatus.COMPLETE if data.industrial_demand_change is not None else AnalysisStatus.UNAVAILABLE, evidence_ids=data.evidence_ids),
            ])
            risks.extend(["industrial-cycle sensitivity", "higher volatility than gold can occur", "physical premium/inventory uncertainty"])
            metadata["corporate_valuation_allowed"] = False

        available = sum(metric.value is not None for metric in metrics)
        unavailable = [metric.name for metric in metrics if metric.value is None]
        unknowns.extend(unavailable)
        status = AnalysisStatus.COMPLETE if not unknowns else (AnalysisStatus.PARTIAL if available else AnalysisStatus.UNAVAILABLE)
        metadata.update(dict(data.context))
        return AnalysisResult(data.instrument_id, f"ALTERNATIVE_{data.asset.value}", status, tuple(metrics), tuple(findings), tuple(risks), tuple(sorted(set(unknowns))), metadata)
