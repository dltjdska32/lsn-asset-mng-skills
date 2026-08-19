"""Deterministic equity fundamental calculations using explicit reported inputs only."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping

from investment_stack.calculations.common import AnalysisResult, AnalysisStatus, MetricResult, pct_change, safe_ratio


@dataclass(frozen=True, slots=True)
class EquityFundamentalInput:
    instrument_id: str
    currency: str
    revenue: Decimal | None = None
    prior_revenue: Decimal | None = None
    operating_income: Decimal | None = None
    net_income: Decimal | None = None
    cash_from_operations: Decimal | None = None
    capex: Decimal | None = None
    total_debt: Decimal | None = None
    cash: Decimal | None = None
    equity: Decimal | None = None
    average_equity: Decimal | None = None
    invested_capital: Decimal | None = None
    tax_rate: Decimal | None = None
    current_assets: Decimal | None = None
    current_liabilities: Decimal | None = None
    shares_outstanding: Decimal | None = None
    guidance: Mapping[str, object] | None = None
    reported_period: str | None = None
    basis: str | None = None
    evidence_ids: tuple[str, ...] = ()


class EquityFundamentalAnalyzer:
    def analyze(self, data: EquityFundamentalInput) -> AnalysisResult:
        metrics: list[MetricResult] = []
        unknowns: list[str] = []

        def add(name: str, value: Decimal | None, formula: str, unit: str = "ratio") -> None:
            if value is None:
                unknowns.append(name)
                metrics.append(MetricResult(name, None, unit, formula, AnalysisStatus.UNAVAILABLE, "required input unavailable", data.evidence_ids))
            else:
                metrics.append(MetricResult(name, value, unit, formula, evidence_ids=data.evidence_ids))

        add("revenue_growth", pct_change(data.revenue, data.prior_revenue), "revenue / prior_revenue - 1")
        add("operating_margin", safe_ratio(data.operating_income, data.revenue), "operating_income / revenue")
        add("net_margin", safe_ratio(data.net_income, data.revenue), "net_income / revenue")

        free_cash_flow = None
        if data.cash_from_operations is not None and data.capex is not None:
            free_cash_flow = data.cash_from_operations - data.capex
            metrics.append(MetricResult("free_cash_flow", free_cash_flow, data.currency, "cash_from_operations - capex", evidence_ids=data.evidence_ids))
        else:
            unknowns.append("free_cash_flow")
            metrics.append(MetricResult("free_cash_flow", None, data.currency, "cash_from_operations - capex", AnalysisStatus.UNAVAILABLE, "required input unavailable", data.evidence_ids))
        add("free_cash_flow_margin", safe_ratio(free_cash_flow, data.revenue), "free_cash_flow / revenue")
        add("debt_to_equity", safe_ratio(data.total_debt, data.equity), "total_debt / equity")
        add("current_ratio", safe_ratio(data.current_assets, data.current_liabilities), "current_assets / current_liabilities")
        add("roe", safe_ratio(data.net_income, data.average_equity), "net_income / average_equity")

        roic = None
        if data.operating_income is not None and data.tax_rate is not None and data.invested_capital not in (None, Decimal("0")):
            nopat = data.operating_income * (Decimal("1") - data.tax_rate)
            roic = nopat / data.invested_capital
        add("roic", roic, "operating_income * (1-tax_rate) / invested_capital")

        available = sum(metric.value is not None for metric in metrics)
        status = AnalysisStatus.COMPLETE if not unknowns else (AnalysisStatus.PARTIAL if available else AnalysisStatus.UNAVAILABLE)
        findings: list[str] = []
        if data.reported_period:
            findings.append(f"reported period: {data.reported_period}")
        if data.basis:
            findings.append(f"accounting basis: {data.basis}")
        if data.guidance:
            findings.append("official guidance supplied; interpretation remains separate from reported results")
        return AnalysisResult(
            data.instrument_id,
            "EQUITY_FUNDAMENTAL",
            status,
            tuple(metrics),
            tuple(findings),
            (),
            tuple(sorted(set(unknowns))),
            {"currency": data.currency, "reported_period": data.reported_period, "basis": data.basis},
        )
