"""Historical portfolio risk calculations using aligned deterministic return series."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Mapping

from investment_stack.calculations.common import ZERO, correlation, max_drawdown, sample_stddev, simple_returns


@dataclass(frozen=True, slots=True)
class AssetRiskInput:
    instrument_id: str
    weight: Decimal
    prices: tuple[Decimal, ...]
    liquidity_score: Decimal | None = None
    custody_risk: str | None = None


@dataclass(frozen=True, slots=True)
class AssetRiskResult:
    instrument_id: str
    volatility: Decimal | None
    max_drawdown: Decimal | None
    contribution: Decimal | None


@dataclass(frozen=True, slots=True)
class PortfolioRiskResult:
    volatility: Decimal | None
    assets: tuple[AssetRiskResult, ...]
    correlations: Mapping[str, Decimal | None]
    partial: bool


class PortfolioRiskAnalyzer:
    def analyze(self, assets: tuple[AssetRiskInput, ...]) -> PortfolioRiskResult:
        if not assets:
            return PortfolioRiskResult(None, (), {}, True)
        return_series = {item.instrument_id: simple_returns(item.prices) if len(item.prices) >= 2 else () for item in assets}
        lengths = {len(series) for series in return_series.values() if series}
        aligned = bool(lengths) and len(lengths) == 1 and all(return_series[item.instrument_id] for item in assets)
        vols = {item.instrument_id: sample_stddev(return_series[item.instrument_id]) for item in assets}
        correlations: dict[str, Decimal | None] = {}
        if not aligned:
            results = tuple(AssetRiskResult(item.instrument_id, vols[item.instrument_id], max_drawdown(item.prices), None) for item in assets)
            return PortfolioRiskResult(None, results, correlations, True)

        ids = [item.instrument_id for item in assets]
        weights = {item.instrument_id: item.weight for item in assets}
        covariance: dict[tuple[str, str], Decimal] = {}
        for i, left in enumerate(ids):
            for right in ids[i:]:
                corr = correlation(return_series[left], return_series[right])
                key = f"{left}|{right}"
                correlations[key] = corr
                if corr is None or vols[left] is None or vols[right] is None:
                    return PortfolioRiskResult(None, tuple(AssetRiskResult(item.instrument_id, vols[item.instrument_id], max_drawdown(item.prices), None) for item in assets), correlations, True)
                covariance[(left, right)] = covariance[(right, left)] = corr * vols[left] * vols[right]
        variance = ZERO
        for left in ids:
            for right in ids:
                variance += weights[left] * weights[right] * covariance[(left, right)]
        if variance < ZERO:
            return PortfolioRiskResult(None, tuple(AssetRiskResult(item.instrument_id, vols[item.instrument_id], max_drawdown(item.prices), None) for item in assets), correlations, True)
        with localcontext() as ctx:
            ctx.prec = 34
            portfolio_vol = variance.sqrt()
        contributions: dict[str, Decimal | None] = {}
        for left in ids:
            if portfolio_vol == ZERO:
                contributions[left] = ZERO
                continue
            marginal = sum((weights[right] * covariance[(left, right)] for right in ids), ZERO) / portfolio_vol
            contributions[left] = weights[left] * marginal
        results = tuple(AssetRiskResult(item.instrument_id, vols[item.instrument_id], max_drawdown(item.prices), contributions[item.instrument_id]) for item in assets)
        return PortfolioRiskResult(portfolio_vol, results, correlations, False)
