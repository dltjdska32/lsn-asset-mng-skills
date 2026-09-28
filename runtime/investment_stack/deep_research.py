"""Live Phase 4 -> Phase 5 deep-research integration for selected equity assets.

The module is deliberately a thin fixed-flow bridge.  Provider/Web Research owns
retrieval and evidence persistence; deterministic Phase 5 analyzers own numeric
calculations.  No personal state is mutated here.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Callable, Iterable, Mapping

from investment_stack.asset_analysis import EquityDeepResult, Phase5AssetAnalysisRuntime
from investment_stack.calculations import BusinessType, DcfScenario, EquityFundamentalInput, EquityValuationInput
from investment_stack.freshness import FreshnessEngine, FreshnessStatus, observation_time
from investment_stack.providers import ProviderCapability, ProviderObservation, ProviderRequest
from investment_stack.providers.execution import assess_current_price_observation
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
    dcf_scenarios: tuple[DcfScenario, ...] = ()
    dcf_sensitivity_rates: tuple[tuple[Decimal, Decimal], ...] = ()


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

_DCF_ASSUMPTION_FIELDS = (
    "starting_fcf", "annual_growth_rate", "discount_rate", "terminal_growth_rate",
    "years", "net_debt", "shares_outstanding",
)


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _assumption_value(value: object) -> Decimal | None:
    try:
        parsed = json.loads(str(value))
        if isinstance(parsed, bool) or parsed is None:
            return None
        result = Decimal(str(parsed))
    except (TypeError, ValueError, InvalidOperation, json.JSONDecodeError):
        return None
    return result if result.is_finite() else None


_PER_SHARE_MONEY_METRICS = frozenset({"eps", "dividend_per_share", "book_value_per_share"})
_SHARE_COUNT_METRICS = frozenset({"shares_outstanding"})
_FLOW_METRICS = frozenset({"revenue", "prior_revenue", "operating_income", "net_income", "cash_from_operations", "capex", "eps", "ebitda", "dividend_per_share"})
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
    found: Decimal | None = None
    for field in _EXPLICIT_SCALE_FIELDS:
        raw = observation.metadata.get(field)
        if raw is None:
            continue
        parsed = _decimal(raw)
        if parsed is None or not parsed.is_finite() or parsed <= 0:
            if isinstance(raw, str):
                parsed = _named_scale(raw)
        if parsed is None or not parsed.is_finite() or parsed <= 0 or found is not None:
            return None
        found = parsed
    return found


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
    if any(observation.metadata.get(field) is not None for field in _EXPLICIT_SCALE_FIELDS):
        return None
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

    unit_token = _token(observation.unit or "")
    if canonical in _SHARE_COUNT_METRICS and not any(token in unit_token for token in ("share", "주")):
        return None, f"{canonical}: share-count unit is missing or incompatible"
    if canonical in _PER_SHARE_MONEY_METRICS and not any(token in unit_token for token in ("share", "주")):
        return None, f"{canonical}: per-share unit is missing or incompatible"
    if canonical in _TOTAL_MONEY_METRICS and ("share" in unit_token or "주당" in unit_token):
        return None, f"{canonical}: total monetary metric has per-share unit"

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

        current_price, price_warning = self._current_price(
            market, target_currency=spec.currency, instrument_id=spec.instrument_id
        )
        metrics, normalization_warnings_tup = self._normalize_financials(
            fundamentals,
            target_currency=spec.currency,
        )
        normalization_warnings = list(normalization_warnings_tup)
        if price_warning:
            normalization_warnings.append(price_warning)

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
        evidence_rows = self.analysis.run_db.fetch_evidence_rows()
        available_evidence_ids = {
            row.get("evidence_id") for row in evidence_rows
            if row.get("instrument_id") == spec.instrument_id and row.get("selection_state") == "SELECTED"
        }
        context = self.analysis.run_db.fetch_phase6_context()
        run_metadata = context.get("run_metadata", {})
        pinned_as_of = _timestamp(run_metadata.get("analysis_as_of")) if isinstance(run_metadata, Mapping) else None
        candidate_dcf_scenarios = tuple(
            scenario for scenario in spec.dcf_scenarios
            if scenario.assumption_evidence_ids
            and set(scenario.assumption_evidence_ids).issubset(available_evidence_ids)
            and self._verify_dcf_scenario_bindings(
                scenario, evidence_rows, self.analysis.run_db.run_id,
                spec.instrument_id, spec.currency, pinned_as_of
            )
        )
        bound_policy_scenarios = [
            scenario for scenario in candidate_dcf_scenarios
            if scenario.name.casefold() in {"base", "optimistic"}
        ]
        policy_binding_ids = [
            evidence_id
            for scenario in bound_policy_scenarios
            for _, evidence_id in scenario.assumption_value_bindings
        ]
        duplicate_policy_bindings = len(policy_binding_ids) != len(set(policy_binding_ids))
        valid_dcf_scenarios = tuple(
            scenario for scenario in candidate_dcf_scenarios
            if not (duplicate_policy_bindings and scenario.name.casefold() in {"base", "optimistic"})
        )
        if len(valid_dcf_scenarios) != len(spec.dcf_scenarios):
            normalization_warnings.append("valuation assumptions excluded: every assumption value must match unique selected same-run evidence available by pinned as_of")

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
            dcf=next((scenario.assumptions for scenario in valid_dcf_scenarios if scenario.name == "base"), None),
            dcf_scenarios=valid_dcf_scenarios,
            dcf_sensitivity_rates=spec.dcf_sensitivity_rates,
            evidence_ids=valuation_evidence,
        )
        analyzed = self.analysis.analyze_equity(fundamental_input, valuation_input)
        if market.selected.freshness is not None and market.selected.freshness.status is FreshnessStatus.LAST_VALID_CLOSE:
            obs = market.selected.observation
            assessment = market.selected.freshness
            detail = (
                f"가격 입력 기준: {assessment.market_session_date} 마지막 유효 거래일 종가 "
                f"({obs.currency}); 종가 시각 {obs.claimed_market_time}; "
                f"공개시각 {assessment.public_available_time}; 달력 {assessment.calendar_id}. 실시간 시세가 아닙니다."
            )
            valuation_result = analyzed.valuation
            analyzed = type(analyzed)(analyzed.fundamental, type(valuation_result)(
                valuation_result.subject, valuation_result.analysis_type, valuation_result.status,
                valuation_result.metrics, (*valuation_result.findings, detail), valuation_result.risks,
                valuation_result.unknowns, valuation_result.metadata,
            ))
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

    def _current_price(
        self, outcome: ResearchOutcome, *, target_currency: str, instrument_id: str
    ) -> tuple[Decimal | None, str | None]:
        observation = outcome.selected.observation
        if observation is None:
            return None, "price: No valid price observation selected"

        if observation.instrument_id and observation.instrument_id != instrument_id:
            return None, f"price: instrument mismatch {observation.instrument_id} != {instrument_id}"

        timestamp = observation_time(observation)
        if not timestamp:
            return None, "price: missing observation time"

        assessment = assess_current_price_observation(observation, analysis_as_of=self.analysis_as_of, engine=self.freshness)
        if assessment.status not in {FreshnessStatus.FRESH, FreshnessStatus.LAST_VALID_CLOSE}:
            return None, f"price: freshness assessment resulted in {assessment.status.name}"

        parsed = _decimal(observation.value)
        if parsed is None:
            return None, "price: missing or invalid numeric value"

        declared_currency = _declared_currency(observation)
        if declared_currency is None:
            return None, "price: missing currency"
        wanted_currency = target_currency.strip().upper()
        if declared_currency != wanted_currency:
            return None, f"price: currency mismatch {declared_currency} != {wanted_currency}"

        scale = _unit_scale(observation)
        if scale is None:
            return None, "price: invalid unit scale"

        return parsed * scale, None

    def _normalize_financials(
        self,
        outcome: ResearchOutcome,
        *,
        target_currency: str,
    ) -> tuple[dict[str, Decimal], tuple[str, ...]]:
        period_groups: dict[tuple[object, ...], dict[str, tuple[object, int, Decimal]]] = {}
        flow_starts: dict[tuple[object, ...], dict[str, str]] = {}
        warnings: list[str] = []
        selected_observations = outcome.selected.selected_observations
        if not selected_observations and outcome.selected.observation is not None:
            selected_observations = (outcome.selected.observation,)
        for observation in selected_observations:
            if observation.evidence_type != "financial":
                continue
            if observation.metadata.get("calculation_input_approved", True) is False:
                continue
            assessment = self.freshness.assess(observation, analysis_as_of=self.analysis_as_of)
            timestamp = observation_time(observation)
            if timestamp is None or assessment.status is FreshnessStatus.UNAVAILABLE:
                continue
            metadata = observation.metadata
            period_key = (
                str(metadata.get("period_end") or metadata.get("end") or ""),
                str(metadata.get("form") or metadata.get("reporting_frequency") or ""),
                str(metadata.get("fp") or metadata.get("reporting_period") or ""),
                str(metadata.get("basis") or metadata.get("accounting_standard") or ""),
                str(metadata.get("consolidation") or ""),
                str(metadata.get("adjustment_basis") or ""),
            )
            metrics_for_period = period_groups.setdefault(period_key, {})
            starts_for_period = flow_starts.setdefault(period_key, {})
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
                if canonical in _FLOW_METRICS:
                    starts_for_period[canonical] = str(metadata.get("start") or "")
                previous = metrics_for_period.get(canonical)
                if previous is None or (candidate[0], candidate[1]) > (previous[0], previous[1]):
                    metrics_for_period[canonical] = candidate
        # Choose one latest compatible period/basis group. Never assemble a model
        # from a newer revenue fact and older equity/debt facts implicitly.
        if period_groups:
            compatible_groups: dict[tuple[object, ...], dict[str, tuple[object, int, Decimal]]] = {}
            group_start: dict[tuple[object, ...], str] = {}
            for key, metrics_for_period in period_groups.items():
                starts = flow_starts.get(key, {})
                distinct_starts = [start for start in starts.values() if start]
                selected_start = (
                    sorted(Counter(distinct_starts).items(), key=lambda item: (-item[1], item[0]))[0][0]
                    if distinct_starts else ""
                )
                compatible = dict(metrics_for_period)
                for metric in _FLOW_METRICS:
                    start = starts.get(metric, "")
                    if start and selected_start and start != selected_start:
                        compatible.pop(metric, None)
                compatible_groups[key] = compatible
                group_start[key] = selected_start
            selected_period = max(
                compatible_groups,
                key=lambda key: (key[0], len(compatible_groups[key]), key[1:], group_start[key]),
            )
            candidates = compatible_groups[selected_period]
            for key, starts in flow_starts.items():
                if key == selected_period:
                    mismatched = sorted(
                        metric for metric, start in starts.items()
                        if start and group_start[key] and start != group_start[key]
                    )
                    if mismatched:
                        warnings.append("financial period length mismatch excluded: " + ", ".join(mismatched))
        else:
            candidates = {}
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

    @staticmethod
    def _verify_dcf_scenario_bindings(
        scenario: DcfScenario,
        evidence_rows: Iterable[Mapping[str, object]],
        run_id: str,
        instrument_id: str,
        currency: str,
        pinned_as_of: datetime | None,
    ) -> bool:
        """Require one selected, timestamped evidence value for every DCF input."""
        if pinned_as_of is None or len(scenario.assumption_value_bindings) != len(_DCF_ASSUMPTION_FIELDS):
            return False
        if any(
            not isinstance(binding, tuple) or len(binding) != 2
            or any(not isinstance(part, str) or not part.strip() for part in binding)
            for binding in scenario.assumption_value_bindings
        ):
            return False
        bindings = dict(scenario.assumption_value_bindings)
        if len(bindings) != len(_DCF_ASSUMPTION_FIELDS) or set(bindings) != set(_DCF_ASSUMPTION_FIELDS):
            return False
        binding_ids = tuple(bindings[field] for field in _DCF_ASSUMPTION_FIELDS)
        if any(not isinstance(item, str) or not item for item in binding_ids) or len(set(binding_ids)) != len(binding_ids):
            return False
        if set(binding_ids) != set(scenario.assumption_evidence_ids):
            return False
        values = {
            "starting_fcf": scenario.assumptions.starting_fcf,
            "annual_growth_rate": scenario.assumptions.annual_growth_rate,
            "discount_rate": scenario.assumptions.discount_rate,
            "terminal_growth_rate": scenario.assumptions.terminal_growth_rate,
            "years": Decimal(scenario.assumptions.years),
            "net_debt": scenario.assumptions.net_debt,
            "shares_outstanding": scenario.assumptions.shares_outstanding,
        }
        expected_units = {
            "starting_fcf": "currency", "annual_growth_rate": "ratio", "discount_rate": "ratio",
            "terminal_growth_rate": "ratio", "years": "years", "net_debt": "currency",
            "shares_outstanding": "shares",
        }
        rows = tuple(evidence_rows)
        for field in _DCF_ASSUMPTION_FIELDS:
            evidence_id = bindings[field]
            matching_metric = [
                row for row in rows
                if row.get("run_id") == run_id
                and row.get("evidence_id") == evidence_id
                and row.get("instrument_id") == instrument_id
                and row.get("metric") == f"dcf_assumption:{scenario.name.casefold()}:{field}"
                and row.get("selection_state") == "SELECTED"
            ]
            if len(matching_metric) != 1:
                return False
            row = matching_metric[0]
            if row.get("evidence_type") != "assumption" or not row.get("source_uri") or not row.get("source_name"):
                return False
            if row.get("unit") != expected_units[field]:
                return False
            if field in {"starting_fcf", "net_debt"} and str(row.get("currency") or "").upper() != currency.upper():
                return False
            if field not in {"starting_fcf", "net_debt"} and row.get("currency") not in (None, ""):
                return False
            retrieved, published = _timestamp(row.get("retrieved_at")), _timestamp(row.get("published_at"))
            if retrieved is None or published is None or retrieved > pinned_as_of or published > pinned_as_of:
                return False
            if _assumption_value(row.get("value_text")) != values[field]:
                return False
            # A competing selected value for the same assumption invalidates the slot,
            # even if the chosen reference itself matches.
            competitors = [
                item for item in rows
                if item.get("run_id") == run_id
                and item.get("instrument_id") == instrument_id
                and item.get("metric") == f"dcf_assumption:{scenario.name.casefold()}:{field}"
                and item.get("selection_state") == "SELECTED"
            ]
            if len(competitors) != 1:
                return False
        return True

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
