"""Asset-appropriate equity valuation with explicit assumptions and no hidden defaults."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from investment_stack.calculations.common import AnalysisResult, AnalysisStatus, MetricResult


class ValuationModel(StrEnum):
    DCF_MULTIPLES = "DCF_MULTIPLES"
    FINANCIAL_PB_ROE_DIVIDEND = "FINANCIAL_PB_ROE_DIVIDEND"
    HIGH_GROWTH_SCENARIO = "HIGH_GROWTH_SCENARIO"
    SOTP = "SOTP"
    NAV_ASSET_BASED = "NAV_ASSET_BASED"


class BusinessType(StrEnum):
    STABLE_CASH_FLOW = "STABLE_CASH_FLOW"
    FINANCIAL = "FINANCIAL"
    HIGH_GROWTH_OR_LOSS = "HIGH_GROWTH_OR_LOSS"
    CONGLOMERATE = "CONGLOMERATE"
    ASSET_HEAVY = "ASSET_HEAVY"


@dataclass(frozen=True, slots=True)
class DcfAssumptions:
    starting_fcf: Decimal
    annual_growth_rate: Decimal
    discount_rate: Decimal
    terminal_growth_rate: Decimal
    years: int
    net_debt: Decimal
    shares_outstanding: Decimal


@dataclass(frozen=True, slots=True)
class HighGrowthScenario:
    name: str
    revenue: Decimal
    revenue_multiple: Decimal
    net_debt: Decimal
    shares_outstanding: Decimal


@dataclass(frozen=True, slots=True)
class EquityValuationInput:
    instrument_id: str
    business_type: BusinessType
    current_price: Decimal | None = None
    currency: str | None = None
    eps: Decimal | None = None
    book_value_per_share: Decimal | None = None
    enterprise_value: Decimal | None = None
    ebitda: Decimal | None = None
    revenue: Decimal | None = None
    market_cap: Decimal | None = None
    roe: Decimal | None = None
    dividend_per_share: Decimal | None = None
    dcf: DcfAssumptions | None = None
    explicit_segment_values: tuple[Decimal, ...] = ()
    high_growth_scenarios: tuple[HighGrowthScenario, ...] = ()
    unit_economics: dict[str, Decimal] | None = None
    nav_assets: Decimal | None = None
    nav_liabilities: Decimal | None = None
    evidence_ids: tuple[str, ...] = ()


def select_model(business_type: BusinessType) -> ValuationModel:
    return {
        BusinessType.STABLE_CASH_FLOW: ValuationModel.DCF_MULTIPLES,
        BusinessType.FINANCIAL: ValuationModel.FINANCIAL_PB_ROE_DIVIDEND,
        BusinessType.HIGH_GROWTH_OR_LOSS: ValuationModel.HIGH_GROWTH_SCENARIO,
        BusinessType.CONGLOMERATE: ValuationModel.SOTP,
        BusinessType.ASSET_HEAVY: ValuationModel.NAV_ASSET_BASED,
    }[business_type]


class EquityValuationAnalyzer:
    def analyze(self, data: EquityValuationInput) -> AnalysisResult:
        model = select_model(data.business_type)
        metrics: list[MetricResult] = []
        unknowns: list[str] = []

        def add(name: str, value: Decimal | None, formula: str, unit: str = "multiple") -> None:
            status = AnalysisStatus.COMPLETE if value is not None else AnalysisStatus.UNAVAILABLE
            if value is None:
                unknowns.append(name)
            metrics.append(MetricResult(name, value, unit, formula, status, None if value is not None else "required input unavailable", data.evidence_ids))

        if data.current_price is not None and data.eps is not None and data.eps > 0:
            add("pe", data.current_price / data.eps, "current_price / eps")
        else:
            add("pe", None, "current_price / eps")
        if data.current_price is not None and data.book_value_per_share not in (None, Decimal("0")):
            add("pb", data.current_price / data.book_value_per_share, "current_price / book_value_per_share")
        else:
            add("pb", None, "current_price / book_value_per_share")
        if data.enterprise_value is not None and data.ebitda not in (None, Decimal("0")):
            add("ev_to_ebitda", data.enterprise_value / data.ebitda, "enterprise_value / ebitda")
        else:
            add("ev_to_ebitda", None, "enterprise_value / ebitda")
        if data.market_cap is not None and data.revenue not in (None, Decimal("0")):
            add("price_to_sales", data.market_cap / data.revenue, "market_cap / revenue")
        else:
            add("price_to_sales", None, "market_cap / revenue")
        if data.current_price is not None and data.dividend_per_share is not None and data.current_price != 0:
            add("dividend_yield", data.dividend_per_share / data.current_price, "dividend_per_share / current_price", "ratio")

        if model is ValuationModel.DCF_MULTIPLES:
            dcf_value = self._dcf_per_share(data.dcf)
            add("dcf_value_per_share", dcf_value, "explicit discounted FCF + terminal value - net debt / shares", data.currency or "currency/share")
        elif model is ValuationModel.FINANCIAL_PB_ROE_DIVIDEND:
            add("roe", data.roe, "reported_or_calculated_roe", "ratio")
        elif model is ValuationModel.HIGH_GROWTH_SCENARIO:
            if not data.high_growth_scenarios:
                add("high_growth_scenario", None, "explicit revenue * revenue_multiple - net_debt / shares", data.currency or "currency/share")
            else:
                for scenario in data.high_growth_scenarios:
                    if scenario.shares_outstanding <= 0:
                        raise ValueError("high-growth scenario shares_outstanding must be positive")
                    implied = (scenario.revenue * scenario.revenue_multiple - scenario.net_debt) / scenario.shares_outstanding
                    add(f"scenario_{scenario.name}", implied, "(revenue * revenue_multiple - net_debt) / shares_outstanding", data.currency or "currency/share")
        elif model is ValuationModel.SOTP:
            add("sotp_explicit_value", sum(data.explicit_segment_values, Decimal("0")) if data.explicit_segment_values else None, "sum(explicit_segment_values)", data.currency or "currency")
        elif model is ValuationModel.NAV_ASSET_BASED:
            nav = None if data.nav_assets is None or data.nav_liabilities is None else data.nav_assets - data.nav_liabilities
            add("net_asset_value", nav, "nav_assets - nav_liabilities", data.currency or "currency")

        available = sum(metric.value is not None for metric in metrics)
        has_valuation_context = any(value is not None for value in (data.current_price, data.eps, data.book_value_per_share, data.enterprise_value, data.ebitda, data.revenue, data.market_cap, data.roe, data.dividend_per_share, data.dcf, data.nav_assets, data.nav_liabilities)) or bool(data.explicit_segment_values or data.high_growth_scenarios or data.unit_economics)
        status = AnalysisStatus.COMPLETE if not unknowns else (AnalysisStatus.PARTIAL if available or has_valuation_context else AnalysisStatus.UNAVAILABLE)
        return AnalysisResult(
            data.instrument_id,
            "EQUITY_VALUATION",
            status,
            tuple(metrics),
            (f"selected model: {model.value}",),
            (),
            tuple(sorted(set(unknowns))),
            {"model": model.value, "currency": data.currency, "current_price_available": data.current_price is not None, "unit_economics": data.unit_economics or {}},
        )

    @staticmethod
    def _dcf_per_share(assumptions: DcfAssumptions | None) -> Decimal | None:
        if assumptions is None:
            return None
        if assumptions.years <= 0 or assumptions.shares_outstanding <= 0:
            raise ValueError("DCF years and shares_outstanding must be positive")
        if assumptions.discount_rate <= assumptions.terminal_growth_rate:
            raise ValueError("DCF discount_rate must exceed terminal_growth_rate")
        if assumptions.discount_rate <= Decimal("-1") or assumptions.annual_growth_rate <= Decimal("-1"):
            raise ValueError("DCF rates are outside the supported domain")
        fcf = assumptions.starting_fcf
        pv = Decimal("0")
        for year in range(1, assumptions.years + 1):
            fcf *= Decimal("1") + assumptions.annual_growth_rate
            pv += fcf / ((Decimal("1") + assumptions.discount_rate) ** year)
        terminal = fcf * (Decimal("1") + assumptions.terminal_growth_rate) / (assumptions.discount_rate - assumptions.terminal_growth_rate)
        pv += terminal / ((Decimal("1") + assumptions.discount_rate) ** assumptions.years)
        equity_value = pv - assumptions.net_debt
        return equity_value / assumptions.shares_outstanding
