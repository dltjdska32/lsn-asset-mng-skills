"""Live Phase 4 -> Phase 5 deep-research integration for selected equity assets.

The module is deliberately a thin fixed-flow bridge.  Provider/Web Research owns
retrieval and evidence persistence; deterministic Phase 5 analyzers own numeric
calculations.  No personal state is mutated here.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Callable, Iterable, Mapping

from investment_stack.asset_analysis import EquityDeepResult, Phase5AssetAnalysisRuntime
from investment_stack.calculations import BusinessType, EquityFundamentalInput, EquityValuationInput
from investment_stack.freshness import FreshnessEngine, FreshnessStatus, observation_time
from investment_stack.providers import ProviderCapability, ProviderObservation, ProviderRequest
from investment_stack.research import Phase4ResearchRuntime, ResearchOutcome


@dataclass(frozen=True, slots=True)
class EquityResearchSpec:
    """Resolved equity identity and source hints supplied by the orchestrator.

    Provider parameters are explicit because identifiers such as OpenDART corp
    codes are resolution outputs, not values the runtime should guess.
    """

    instrument_id: str
    display_name: str
    country: str
    currency: str
    business_type: BusinessType = BusinessType.STABLE_CASH_FLOW
    ticker: str | None = None
    market_query: str | None = None
    fundamentals_query: str | None = None
    news_query: str | None = None
    market_parameters: Mapping[str, object] | None = None
    fundamentals_parameters: Mapping[str, object] | None = None


@dataclass(frozen=True, slots=True)
class EquityResearchOutcome:
    instrument_id: str
    market: ResearchOutcome
    fundamentals: ResearchOutcome
    news: ResearchOutcome | None
    analysis: EquityDeepResult
    normalized_metrics: Mapping[str, Decimal]
    evidence_ids: tuple[str, ...]


_METRIC_ALIASES: dict[str, frozenset[str]] = {
    "revenue": frozenset({"revenue", "revenues", "sales", "netsales", "매출", "매출액", "영업수익"}),
    "prior_revenue": frozenset({"priorrevenue", "priorsales", "전기매출액", "전년매출액"}),
    "operating_income": frozenset({"operatingincome", "operatingprofit", "영업이익"}),
    "net_income": frozenset({"netincome", "profitloss", "netprofit", "당기순이익", "연결당기순이익"}),
    "cash_from_operations": frozenset({"cashfromoperations", "operatingcashflow", "netcashprovidedbyoperatingactivities", "영업활동현금흐름"}),
    "capex": frozenset({"capex", "capitalexpenditure", "capitalexpenditures", "설비투자", "자본적지출"}),
    "total_debt": frozenset({"totaldebt", "총차입금", "총부채성차입금"}),
    "cash": frozenset({"cash", "cashandcashequivalents", "현금및현금성자산"}),
    "equity": frozenset({"equity", "stockholdersequity", "stockholdersequity", "자본총계", "지배기업소유주지분"}),
    "average_equity": frozenset({"averageequity", "평균자기자본"}),
    "invested_capital": frozenset({"investedcapital", "투하자본"}),
    "current_assets": frozenset({"currentassets", "유동자산"}),
    "current_liabilities": frozenset({"currentliabilities", "유동부채"}),
    "shares_outstanding": frozenset({"sharesoutstanding", "commonsharesoutstanding", "발행주식수", "유통주식수"}),
    "eps": frozenset({"eps", "earningspershare", "basiceps", "기본주당이익", "주당순이익"}),
    "ebitda": frozenset({"ebitda"}),
    "dividend_per_share": frozenset({"dividendpershare", "dps", "주당배당금"}),
    "book_value_per_share": frozenset({"bookvaluepershare", "bvps", "주당순자산"}),
    "enterprise_value": frozenset({"enterprisevalue", "ev"}),
    "market_cap": frozenset({"marketcap", "marketcapitalization", "시가총액"}),
}

_TOTAL_MONEY_METRICS = frozenset(
    {
        "revenue",
        "prior_revenue",
        "operating_income",
        "net_income",
        "cash_from_operations",
        "capex",
        "total_debt",
        "cash",
        "equity",
        "average_equity",
        "invested_capital",
        "current_assets",
        "current_liabilities",
        "ebitda",
        "enterprise_value",
        "market_cap",
    }
)
_PER_SHARE_MONEY_METRICS = frozenset({"eps", "dividend_per_share", "book_value_per_share"})
_SHARE_COUNT_METRICS = frozenset({"shares_outstanding"})
_EXPLICIT_SCALE_FIELDS = ("unit_multiplier", "value_multiplier", "unit_scale", "value_scale")

_NAMED_SCALES: tuple[tuple[tuple[str, ...], Decimal], ...] = (
    (("trillion", "trillions", "兆", "조"), Decimal("1000000000000")),
    (("billion", "billions", "十億", "십억"), Decimal("1000000000")),
    (("億", "억"), Decimal("100000000")),
    (("million", "millions", "百万", "백만"), Decimal("1000000")),
    (("thousand", "thousands", "千", "천"), Decimal("1000")),
)
_ABBREVIATED_SCALES = {
    "tn": Decimal("1000000000000"),
    "bn": Decimal("1000000000"),
    "mn": Decimal("1000000"),
    "mm": Decimal("1000000"),
    "mio": Decimal("1000000"),
}

_CURRENCY_MARKERS: dict[str, tuple[str, ...]] = {
    "JPY": ("JPY", "円", "엔"),
    "KRW": ("KRW", "원"),
    "USD": ("USD", "US$", "$"),
    "EUR": ("EUR", "€"),
    "GBP": ("GBP", "£"),
    "CNY": ("CNY", "RMB", "人民币", "元"),
    "HKD": ("HKD", "HK$"),
}


def _token(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum() or "가" <= character <= "힣")


def _canonical_metric(observation: ProviderObservation, raw_name: str) -> str | None:
    explicit = observation.metadata.get("canonical_metric")
    if isinstance(explicit, str) and explicit in _METRIC_ALIASES:
        return explicit
    token = _token(raw_name)
    for canonical, aliases in _METRIC_ALIASES.items():
        if token == _token(canonical) or token in {_token(alias) for alias in aliases}:
            return canonical
    return None


def _decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "")
        if cleaned.startswith("(") and cleaned.endswith(")"):
            cleaned = "-" + cleaned[1:-1]
        if cleaned in {"", "-", "—", "N/A", "NA", "null", "None"}:
            return None
        try:
            return Decimal(cleaned)
        except InvalidOperation:
            return None
    return None


def _explicit_scale(observation: ProviderObservation) -> Decimal | None:
    for field in _EXPLICIT_SCALE_FIELDS:
        raw = observation.metadata.get(field)
        if raw is None:
            continue
        parsed = _decimal(raw)
        if parsed is not None and parsed > 0:
            return parsed
        if isinstance(raw, str):
            named = _named_scale(raw)
            if named is not None:
                return named
        return None
    return None


def _named_scale(label: str) -> Decimal | None:
    folded = label.casefold()
    for names, scale in _NAMED_SCALES:
        if any(name.casefold() in folded for name in names):
            return scale
    ascii_tokens = re.findall(r"[a-z]+", folded)
    for token in ascii_tokens:
        if token in _ABBREVIATED_SCALES:
            return _ABBREVIATED_SCALES[token]
    return None


def _unit_scale(observation: ProviderObservation) -> Decimal | None:
    explicit = _explicit_scale(observation)
    if explicit is not None:
        return explicit
    if observation.unit is None or not observation.unit.strip():
        return Decimal("1")
    return _named_scale(observation.unit) or Decimal("1")


def _declared_currency(observation: ProviderObservation) -> str | None:
    if observation.currency:
        return observation.currency.strip().upper()
    if not observation.unit:
        return None
    unit = observation.unit.upper()
    for currency, markers in _CURRENCY_MARKERS.items():
        if any(marker.upper() in unit for marker in markers):
            return currency
    return None


def _has_explicit_unit(observation: ProviderObservation) -> bool:
    return bool(observation.unit and observation.unit.strip()) or any(
        observation.metadata.get(field) is not None for field in _EXPLICIT_SCALE_FIELDS
    )


def _normalize_metric_value(
    canonical: str,
    value: Decimal,
    observation: ProviderObservation,
    *,
    target_currency: str,
) -> tuple[Decimal | None, str | None]:
    """Normalize financial metrics to base currency/share-count units.

    Total monetary metrics become base currency (for example JPY, not JPY
    millions), share counts become individual shares, and per-share metrics
    become base currency/share.  Web-research numeric financial facts must carry
    an explicit unit/scale so an LLM cannot silently treat "JPY million" as JPY.
    """

    if canonical not in _TOTAL_MONEY_METRICS | _PER_SHARE_MONEY_METRICS | _SHARE_COUNT_METRICS:
        return value, None

    if observation.provider_id == "web_research" and not _has_explicit_unit(observation):
        return None, f"{canonical}: web financial input missing explicit unit/scale"

    scale = _unit_scale(observation)
    if scale is None:
        return None, f"{canonical}: invalid unit scale"

    if canonical in _SHARE_COUNT_METRICS:
        return value * scale, None

    declared_currency = _declared_currency(observation)
    wanted_currency = target_currency.strip().upper()
    if declared_currency is None:
        return None, f"{canonical}: monetary input missing currency"
    if declared_currency != wanted_currency:
        return None, f"{canonical}: currency mismatch {declared_currency} != {wanted_currency}"
    return value * scale, None


def _observation_metrics(observation: ProviderObservation) -> Iterable[tuple[str, Decimal]]:
    if isinstance(observation.value, Mapping):
        for key, value in observation.value.items():
            canonical = _canonical_metric(observation, str(key))
            parsed = _decimal(value)
            if canonical is not None and parsed is not None:
                yield canonical, parsed
        return
    metric_name = observation.metric or ""
    canonical = _canonical_metric(observation, metric_name)
    parsed = _decimal(observation.value)
    if canonical is not None and parsed is not None:
        yield canonical, parsed


class LiveDeepResearchRuntime:
    """Execute selected-equity live research before deterministic analysis.

    This is the missing integration seam between the Phase 4 retrieval/evidence
    runtime and the Phase 5 analyzers.  It intentionally does not perform web
    search itself; the existing WebResearchAdapter remains the injected boundary.
    """

    def __init__(
        self,
        *,
        research: Phase4ResearchRuntime,
        analysis: Phase5AssetAnalysisRuntime,
        analysis_as_of: str,
        analysis_timezone: str,
        freshness: FreshnessEngine | None = None,
    ) -> None:
        self.research = research
        self.analysis = analysis
        self.analysis_as_of = analysis_as_of
        self.analysis_timezone = analysis_timezone
        self.freshness = freshness or FreshnessEngine()

    def equity_callback(self, spec: EquityResearchSpec) -> Callable[[], EquityResearchOutcome]:
        return lambda: self.analyze_equity(spec)

    def analyze_equity(self, spec: EquityResearchSpec) -> EquityResearchOutcome:
        self.analysis.run_db.record_task_state(
            task_name=f"deep_research:{spec.instrument_id}",
            task_status="RUNNING",
            metadata={"country": spec.country, "ticker": spec.ticker},
        )
        market_query = spec.market_query or self._market_query(spec)
        fundamentals_query = spec.fundamentals_query or self._fundamentals_query(spec)
        market = self.research.collect(
            ProviderRequest(
                ProviderCapability.CURRENT_PRICE,
                self.analysis_as_of,
                self.analysis_timezone,
                spec.instrument_id,
                "current_price",
                dict(spec.market_parameters or {}),
            ),
            web_query=market_query,
        )
        fundamentals = self.research.collect(
            ProviderRequest(
                ProviderCapability.FUNDAMENTALS,
                self.analysis_as_of,
                self.analysis_timezone,
                spec.instrument_id,
                "fundamentals",
                dict(spec.fundamentals_parameters or {}),
            ),
            web_query=fundamentals_query,
        )
        news: ResearchOutcome | None = None
        if spec.news_query:
            news = self.research.collect(
                ProviderRequest(
                    ProviderCapability.NEWS,
                    self.analysis_as_of,
                    self.analysis_timezone,
                    spec.instrument_id,
                    "latest_relevant_news",
                ),
                web_query=spec.news_query,
            )

        current_price = self._current_price(market, target_currency=spec.currency)
        metrics, normalization_warnings = self._normalize_financials(
            fundamentals,
            target_currency=spec.currency,
        )
        evidence_ids = self._selected_evidence_ids(spec.instrument_id)
        fundamental_evidence = tuple(
            evidence_id for evidence_id in evidence_ids if self._evidence_type(evidence_id) == "financial"
        )
        market_evidence = tuple(
            evidence_id for evidence_id in evidence_ids if self._evidence_type(evidence_id) == "market"
        )
        if not fundamental_evidence and fundamentals.selected.evidence_id:
            fundamental_evidence = (fundamentals.selected.evidence_id,)
        valuation_evidence = tuple(dict.fromkeys((*market_evidence, *fundamental_evidence)))

        shares = metrics.get("shares_outstanding")
        equity = metrics.get("equity")
        book_value_per_share = metrics.get("book_value_per_share")
        if book_value_per_share is None and shares not in (None, Decimal("0")) and equity is not None:
            book_value_per_share = equity / shares
        market_cap = metrics.get("market_cap")
        if market_cap is None and current_price is not None and shares is not None:
            market_cap = current_price * shares
        enterprise_value = metrics.get("enterprise_value")
        debt = metrics.get("total_debt")
        cash = metrics.get("cash")
        if enterprise_value is None and market_cap is not None and debt is not None and cash is not None:
            enterprise_value = market_cap + debt - cash

        reported_period = self._latest_financial_period(spec.instrument_id)
        fundamental_input = EquityFundamentalInput(
            instrument_id=spec.instrument_id,
            currency=spec.currency,
            revenue=metrics.get("revenue"),
            prior_revenue=metrics.get("prior_revenue"),
            operating_income=metrics.get("operating_income"),
            net_income=metrics.get("net_income"),
            cash_from_operations=metrics.get("cash_from_operations"),
            capex=metrics.get("capex"),
            total_debt=debt,
            cash=cash,
            equity=equity,
            average_equity=metrics.get("average_equity"),
            invested_capital=metrics.get("invested_capital"),
            current_assets=metrics.get("current_assets"),
            current_liabilities=metrics.get("current_liabilities"),
            shares_outstanding=shares,
            reported_period=reported_period,
            evidence_ids=fundamental_evidence,
        )
        valuation_input = EquityValuationInput(
            instrument_id=spec.instrument_id,
            business_type=spec.business_type,
            current_price=current_price,
            currency=spec.currency,
            eps=metrics.get("eps"),
            book_value_per_share=book_value_per_share,
            enterprise_value=enterprise_value,
            ebitda=metrics.get("ebitda"),
            revenue=metrics.get("revenue"),
            market_cap=market_cap,
            dividend_per_share=metrics.get("dividend_per_share"),
            evidence_ids=valuation_evidence,
        )
        analyzed = self.analysis.analyze_equity(fundamental_input, valuation_input)
        status = "COMPLETED"
        if current_price is None or not metrics or normalization_warnings:
            status = "PARTIAL"
        self.analysis.run_db.record_task_state(
            task_name=f"deep_research:{spec.instrument_id}",
            task_status=status,
            metadata={
                "market_selected": market.selected.evidence_id,
                "financial_selected_count": len(fundamental_evidence),
                "normalized_metrics": sorted(metrics),
                "normalization_warnings": list(normalization_warnings),
                "fundamental_calculation_id": analyzed.fundamental.metadata.get("calculation_id"),
                "valuation_calculation_id": analyzed.valuation.metadata.get("calculation_id"),
            },
        )
        return EquityResearchOutcome(
            spec.instrument_id,
            market,
            fundamentals,
            news,
            analyzed,
            dict(metrics),
            valuation_evidence,
        )

    def _current_price(self, outcome: ResearchOutcome, *, target_currency: str) -> Decimal | None:
        observation = outcome.selected.observation
        if observation is None:
            return None
        assessment = self.freshness.assess(observation, analysis_as_of=self.analysis_as_of)
        if assessment.status in {FreshnessStatus.UNKNOWN, FreshnessStatus.UNAVAILABLE}:
            return None
        parsed = _decimal(observation.value)
        if parsed is None:
            return None
        declared_currency = _declared_currency(observation)
        if declared_currency is not None and declared_currency != target_currency.strip().upper():
            return None
        scale = _unit_scale(observation)
        if scale is None:
            return None
        return parsed * scale

    def _normalize_financials(
        self,
        outcome: ResearchOutcome,
        *,
        target_currency: str,
    ) -> tuple[dict[str, Decimal], tuple[str, ...]]:
        candidates: dict[str, tuple[object, int, Decimal]] = {}
        warnings: list[str] = []
        for result in outcome.provider_results:
            for observation in result.observations:
                if observation.evidence_type != "financial":
                    continue
                if observation.metadata.get("calculation_input_approved", True) is False:
                    continue
                assessment = self.freshness.assess(observation, analysis_as_of=self.analysis_as_of)
                timestamp = observation_time(observation)
                if timestamp is None or assessment.status is FreshnessStatus.UNAVAILABLE:
                    continue
                for canonical, value in _observation_metrics(observation):
                    normalized, warning = _normalize_metric_value(
                        canonical,
                        value,
                        observation,
                        target_currency=target_currency,
                    )
                    if normalized is None:
                        if warning:
                            warnings.append(warning)
                        continue
                    candidate = (timestamp, -observation.source_tier, normalized)
                    previous = candidates.get(canonical)
                    if previous is None or (candidate[0], candidate[1]) > (previous[0], previous[1]):
                        candidates[canonical] = candidate
        return (
            {name: candidate[2] for name, candidate in candidates.items()},
            tuple(sorted(set(warnings))),
        )

    def _selected_evidence_ids(self, instrument_id: str) -> tuple[str, ...]:
        return tuple(
            row["evidence_id"]
            for row in self.analysis.run_db.fetch_evidence_rows()
            if row.get("instrument_id") == instrument_id and row.get("selection_state") == "SELECTED"
        )

    def _evidence_type(self, evidence_id: str) -> str | None:
        for row in self.analysis.run_db.fetch_evidence_rows():
            if row.get("evidence_id") == evidence_id:
                return row.get("evidence_type")
        return None

    def _latest_financial_period(self, instrument_id: str) -> str | None:
        context = self.analysis.run_db.fetch_phase6_context()
        periods = [
            row.get("period_end")
            for row in context["financial_observations"]
            if row.get("evidence_id") in {
                evidence["evidence_id"]
                for evidence in context["evidence"]
                if evidence.get("instrument_id") == instrument_id
            }
            and row.get("period_end")
        ]
        return max(periods) if periods else None

    @staticmethod
    def _market_query(spec: EquityResearchSpec) -> str:
        market = {"KOREA": "KRX/KIND", "JAPAN": "JPX", "USA": "official exchange"}.get(spec.country.upper(), "official exchange")
        ticker = f" {spec.ticker}" if spec.ticker else ""
        return f"{spec.display_name}{ticker} {market} latest timestamped market price"

    @staticmethod
    def _fundamentals_query(spec: EquityResearchSpec) -> str:
        source = {
            "KOREA": "OpenDART company IR latest filing earnings guidance",
            "JAPAN": "EDINET TDnet JPX company IR latest filing earnings guidance",
            "USA": "SEC EDGAR company IR latest filing earnings guidance",
        }.get(spec.country.upper(), "company regulatory filing IR latest earnings guidance")
        ticker = f" {spec.ticker}" if spec.ticker else ""
        return f"{spec.display_name}{ticker} {source}"
