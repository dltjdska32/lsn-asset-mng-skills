"""Non-posting portfolio analysis and hypothetical scenario services.

The API consumes already pinned state and typed observations. It performs no personal
database I/O and has no ledger/transaction writer capability.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
import re
from typing import Callable, Mapping

from investment_stack.calculations import (
    AllocationAnalyzer,
    AllocationResult,
    AssetRiskInput,
    PortfolioRiskAnalyzer,
    PortfolioRiskResult,
    PositionExposure,
)
from investment_stack.reporting.models import Availability, ReportSectionInput


class ScenarioStatus(StrEnum):
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    WAIT = "WAIT"


class ScenarioTargetKind(StrEnum):
    POSITION = "POSITION"
    CASH = "CASH"
    LIABILITY = "LIABILITY"


class LimitStatus(StrEnum):
    WITHIN = "WITHIN"
    BREACHED = "BREACHED"
    UNKNOWN = "UNKNOWN"


def _decimal(value: Decimal | str | int, label: str) -> Decimal:
    if isinstance(value, (bool, float)):
        raise ValueError(f"{label} must use Decimal, string, or integer; binary floats are rejected")
    try:
        parsed = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite decimal") from exc
    if not parsed.is_finite():
        raise ValueError(f"{label} must be a finite decimal")
    return parsed


def _timestamp(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed


def _currency(value: str, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z]{3}", value.strip()):
        raise ValueError(f"{label} must be a three-letter currency code")
    return value.strip().upper()


@dataclass(frozen=True, slots=True)
class PinnedPortfolioState:
    state_version: int
    snapshot_ref: str
    analysis_as_of: str
    portfolio_data_as_of: str

    def __post_init__(self) -> None:
        if isinstance(self.state_version, bool) or self.state_version <= 0:
            raise ValueError("confirmed state_version must be positive")
        if not self.snapshot_ref.strip():
            raise ValueError("confirmed snapshot_ref is required")
        as_of = _timestamp(self.analysis_as_of, "analysis_as_of")
        portfolio_as_of = _timestamp(self.portfolio_data_as_of, "portfolio_data_as_of")
        if portfolio_as_of > as_of:
            raise ValueError("portfolio state cannot be newer than the pinned analysis clock")


@dataclass(frozen=True, slots=True)
class PortfolioPosition:
    instrument_id: str
    market_value: Decimal | None
    currency: str
    asset_class: str | None = None
    account: str | None = None
    country: str | None = None
    sector: str | None = None
    region: str | None = None
    liquidity: str | None = None
    custody: str | None = None
    leverage: Decimal | None = None
    unvalued_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.instrument_id.strip():
            raise ValueError("position instrument_id and currency are required")
        object.__setattr__(self, "currency", _currency(self.currency, "position currency"))
        if self.market_value is not None:
            value = _decimal(self.market_value, "market_value")
            if value < 0:
                raise ValueError("market_value cannot be negative")
            object.__setattr__(self, "market_value", value)
        if self.leverage is not None:
            object.__setattr__(self, "leverage", _decimal(self.leverage, "leverage"))


@dataclass(frozen=True, slots=True)
class MoneyBalance:
    balance_id: str
    amount: Decimal | None
    currency: str
    unvalued_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.balance_id.strip():
            raise ValueError("balance_id and currency are required")
        object.__setattr__(self, "currency", _currency(self.currency, "balance currency"))
        if self.amount is not None:
            amount = _decimal(self.amount, "balance amount")
            if amount < 0:
                raise ValueError("cash and liability balances must be nonnegative amounts")
            object.__setattr__(self, "amount", amount)


@dataclass(frozen=True, slots=True)
class FxEvidence:
    from_currency: str
    to_currency: str
    rate: Decimal
    evidence_id: str
    observed_at: str
    public_available_at: str
    eligibility_status: str
    freshness_status: str
    selected: bool

    def __post_init__(self) -> None:
        rate = _decimal(self.rate, "FX rate")
        if rate <= 0 or not self.evidence_id.strip():
            raise ValueError("FX rate must be positive and evidence_id is required")
        object.__setattr__(self, "rate", rate)
        object.__setattr__(self, "from_currency", _currency(self.from_currency, "FX from_currency"))
        object.__setattr__(self, "to_currency", _currency(self.to_currency, "FX to_currency"))
        if type(self.selected) is not bool:
            raise ValueError("FX selected flag must be boolean")


@dataclass(frozen=True, slots=True)
class RiskObservation:
    period: str
    price: Decimal
    currency: str
    evidence_id: str
    public_available_at: str
    eligibility_status: str
    freshness_status: str
    selected: bool

    def __post_init__(self) -> None:
        price = _decimal(self.price, "risk observation price")
        if price <= 0 or not self.evidence_id.strip():
            raise ValueError("risk observation price and evidence reference must be positive/nonempty")
        try:
            date.fromisoformat(self.period)
        except ValueError as exc:
            raise ValueError("risk observation period must be an ISO date") from exc
        object.__setattr__(self, "price", price)
        object.__setattr__(self, "currency", _currency(self.currency, "risk observation currency"))


@dataclass(frozen=True, slots=True)
class HistoricalPriceSeries:
    instrument_id: str
    frequency: str
    observations: tuple[RiskObservation, ...]

    def __post_init__(self) -> None:
        if not self.instrument_id.strip() or not self.frequency.strip():
            raise ValueError("historical price series needs instrument and frequency")
        periods = [item.period for item in self.observations]
        if len(periods) != len(set(periods)):
            raise ValueError("historical price periods must be unique per instrument")
        object.__setattr__(self, "observations", tuple(sorted(self.observations, key=lambda item: item.period)))


@dataclass(frozen=True, slots=True)
class RiskPeriodPolicy:
    policy_ref: str
    frequency: str
    period_start: str
    period_end: str
    minimum_observations: int

    def __post_init__(self) -> None:
        if not self.policy_ref.strip() or not self.frequency.strip():
            raise ValueError("risk period policy reference and frequency are required")
        start = date.fromisoformat(self.period_start)
        end = date.fromisoformat(self.period_end)
        if (start > end or isinstance(self.minimum_observations, bool)
                or not isinstance(self.minimum_observations, int) or self.minimum_observations < 2):
            raise ValueError("risk period requires a valid ordered date range and at least two observations")


@dataclass(frozen=True, slots=True)
class PortfolioRiskPolicy:
    policy_ref: str
    approved: bool
    approval_ref: str | None
    max_volatility_per_period: Decimal | None = None
    max_drawdown: Decimal | None = None
    validation_ref: str | None = None

    def __post_init__(self) -> None:
        if not self.policy_ref.strip():
            raise ValueError("risk policy reference is required")
        if type(self.approved) is not bool:
            raise ValueError("risk policy approved flag must be boolean")
        for field_name in ("max_volatility_per_period", "max_drawdown"):
            value = getattr(self, field_name)
            if value is not None:
                value = _decimal(value, field_name)
                if value < 0:
                    raise ValueError(f"{field_name} cannot be negative")
                object.__setattr__(self, field_name, value)


@dataclass(frozen=True, slots=True)
class PortfolioAnalysisRequest:
    pinned_state: PinnedPortfolioState
    evaluation_currency: str
    positions: tuple[PortfolioPosition, ...]
    cash: tuple[MoneyBalance, ...]
    liabilities: tuple[MoneyBalance, ...]
    fx_evidence: tuple[FxEvidence, ...] = ()
    price_series: tuple[HistoricalPriceSeries, ...] = ()
    period_policy: RiskPeriodPolicy | None = None
    risk_policy: PortfolioRiskPolicy | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "evaluation_currency", _currency(self.evaluation_currency, "evaluation_currency"))
        identifiers = [p.instrument_id for p in self.positions]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("portfolio position instrument IDs must be unique")
        if len({b.balance_id for b in self.cash}) != len(self.cash):
            raise ValueError("cash balance IDs must be unique")
        if len({b.balance_id for b in self.liabilities}) != len(self.liabilities):
            raise ValueError("liability IDs must be unique")


@dataclass(frozen=True, slots=True)
class RiskLimitAssessment:
    metric: str
    value: Decimal | None
    limit: Decimal | None
    status: LimitStatus
    reason: str


@dataclass(frozen=True, slots=True)
class PortfolioAnalysisResult:
    availability: Availability
    state_version: int
    snapshot_ref: str
    evaluation_currency: str
    valued_asset_subtotal: Decimal
    total_cash: Decimal | None
    gross_assets: Decimal | None
    total_liabilities: Decimal | None
    net_worth: Decimal | None
    unvalued_items: tuple[str, ...]
    allocation: AllocationResult
    risk: PortfolioRiskResult | None
    risk_limits: tuple[RiskLimitAssessment, ...]
    missing_inputs: tuple[str, ...]
    section: ReportSectionInput


@dataclass(frozen=True, slots=True)
class ScenarioApproval:
    gate_id: str
    policy_ref: str
    approval_ref: str
    validation_ref: str
    enabled: bool

    def __post_init__(self) -> None:
        if not all(isinstance(value, str) and value.strip() for value in
                   (self.gate_id, self.policy_ref, self.approval_ref, self.validation_ref)):
            raise ValueError("scenario approval needs gate, policy, approval, and validation references")
        if type(self.enabled) is not bool:
            raise ValueError("scenario gate enabled flag must be boolean")


@dataclass(frozen=True, slots=True)
class ScenarioAdjustment:
    target_kind: ScenarioTargetKind | str
    target_id: str
    value_delta: Decimal
    currency: str
    assumption_ref: str

    def __post_init__(self) -> None:
        try:
            kind = ScenarioTargetKind(self.target_kind)
        except ValueError as exc:
            raise ValueError(f"unsupported scenario target kind: {self.target_kind!r}") from exc
        if not self.target_id.strip() or not self.currency.strip() or not self.assumption_ref.strip():
            raise ValueError("scenario adjustment needs a target, currency, and assumption reference")
        object.__setattr__(self, "currency", _currency(self.currency, "scenario adjustment currency"))
        object.__setattr__(self, "target_kind", kind)
        object.__setattr__(self, "value_delta", _decimal(self.value_delta, "scenario value_delta"))


@dataclass(frozen=True, slots=True)
class ScenarioFxAssumption:
    from_currency: str
    to_currency: str
    rate: Decimal
    assumption_ref: str

    def __post_init__(self) -> None:
        rate = _decimal(self.rate, "scenario FX rate")
        if rate <= 0 or not self.assumption_ref.strip():
            raise ValueError("scenario FX rate must be positive with an explicit assumption reference")
        object.__setattr__(self, "rate", rate)
        object.__setattr__(self, "from_currency", _currency(self.from_currency, "scenario FX from_currency"))
        object.__setattr__(self, "to_currency", _currency(self.to_currency, "scenario FX to_currency"))


@dataclass(frozen=True, slots=True)
class ScenarioRiskShock:
    instrument_id: str
    last_observation_return_shock: Decimal
    assumption_ref: str

    def __post_init__(self) -> None:
        shock = _decimal(self.last_observation_return_shock, "scenario return shock")
        if shock <= -1 or not self.instrument_id.strip() or not self.assumption_ref.strip():
            raise ValueError("scenario risk shock must exceed -100% and include instrument/assumption reference")
        object.__setattr__(self, "last_observation_return_shock", shock)


@dataclass(frozen=True, slots=True)
class PortfolioScenario:
    scenario_id: str
    description: str
    approval: ScenarioApproval | None
    adjustments: tuple[ScenarioAdjustment, ...]
    fx_assumptions: tuple[ScenarioFxAssumption, ...] = ()
    risk_shocks: tuple[ScenarioRiskShock, ...] = ()


@dataclass(frozen=True, slots=True)
class PortfolioScenarioResult:
    status: ScenarioStatus
    scenario_id: str
    before: PortfolioAnalysisResult | None
    after: PortfolioAnalysisResult | None
    gross_assets_delta: Decimal | None
    liabilities_delta: Decimal | None
    net_worth_delta: Decimal | None
    risk_volatility_delta: Decimal | None
    missing_inputs: tuple[str, ...]
    section: ReportSectionInput


def _fx_rate(
    source: str,
    target: str,
    as_of: datetime,
    fx_evidence: tuple[FxEvidence, ...],
    override: Mapping[tuple[str, str], Decimal] | None = None,
) -> Decimal | None:
    if source.upper() == target.upper():
        return Decimal("1")
    pair = (source.upper(), target.upper())
    if override and pair in override:
        return override[pair]
    candidates: list[tuple[datetime, FxEvidence]] = []
    for quote in fx_evidence:
        if (
            (quote.from_currency.upper(), quote.to_currency.upper()) != pair
            or not quote.selected
            or quote.eligibility_status.upper() != "ELIGIBLE"
            or quote.freshness_status.upper() not in {"FRESH", "CURRENT"}
        ):
            continue
        try:
            observed = _timestamp(quote.observed_at, "FX observed_at")
            published = _timestamp(quote.public_available_at, "FX public_available_at")
        except ValueError:
            continue
        if observed <= as_of and published <= as_of:
            candidates.append((observed, quote))
    if not candidates:
        return None
    latest_at = max(stamp for stamp, _ in candidates)
    rates = {quote.rate for stamp, quote in candidates if stamp == latest_at}
    return next(iter(rates)) if len(rates) == 1 else None


def _convert(
    value: Decimal | None,
    source: str,
    target: str,
    as_of: datetime,
    fx: tuple[FxEvidence, ...],
    override: Mapping[tuple[str, str], Decimal] | None = None,
) -> Decimal | None:
    if value is None:
        return None
    rate = _fx_rate(source, target, as_of, fx, override)
    return None if rate is None else value * rate


def _risk_result(
    request: PortfolioAnalysisRequest,
    positions: tuple[PortfolioPosition, ...],
    converted_positions: Mapping[str, Decimal | None],
    gross: Decimal | None,
):
    period = request.period_policy
    if (period is None or request.risk_policy is None or not request.risk_policy.approved
            or not request.risk_policy.approval_ref or not request.risk_policy.validation_ref):
        return None, ("승인된 위험 정책 또는 명시적 기간 정책이 없어 위험 계산을 확정할 수 없습니다.",)
    risk_by_instrument = {series.instrument_id: series for series in request.price_series}
    if len(risk_by_instrument) != len(request.price_series):
        return None, ("위험 가격 series에 중복 자산이 있습니다.",)
    if gross is None or gross <= 0:
        return None, ("완전한 양수 총자산 baseline이 없어 위험 가중치를 계산할 수 없습니다.",)
    as_of = _timestamp(request.pinned_state.analysis_as_of, "analysis_as_of")
    start, end = date.fromisoformat(period.period_start), date.fromisoformat(period.period_end)
    risk_inputs: list[AssetRiskInput] = []
    timeline: tuple[str, ...] | None = None
    missing: list[str] = []
    priced_positions = [position for position in positions if converted_positions.get(position.instrument_id) is not None]
    for position in priced_positions:
        converted_value = converted_positions.get(position.instrument_id)
        if converted_value is None:
            missing.append(f"{position.instrument_id}: 평가통화 기준 위험 가중치가 없습니다.")
            continue
        series = risk_by_instrument.get(position.instrument_id)
        if series is None or series.frequency != period.frequency:
            missing.append(f"{position.instrument_id}: 위험 series 또는 빈도 불일치")
            continue
        valid = []
        for observation in series.observations:
            observed_day = date.fromisoformat(observation.period)
            if (
                observed_day < start or observed_day > end
                or observed_day > as_of.date()
                or observation.currency.upper() != request.evaluation_currency.upper()
                or observation.eligibility_status.upper() != "ELIGIBLE"
                or observation.freshness_status.upper() not in {"FRESH", "CURRENT"}
                or not observation.selected
            ):
                continue
            try:
                if _timestamp(observation.public_available_at, "risk public_available_at") > as_of:
                    continue
            except ValueError:
                continue
            valid.append(observation)
        valid.sort(key=lambda item: item.period)
        current_timeline = tuple(item.period for item in valid)
        if len(valid) < period.minimum_observations or len(set(current_timeline)) != len(current_timeline):
            missing.append(f"{position.instrument_id}: 적격 위험 관측치가 기간 요건에 부족합니다.")
            continue
        if timeline is None:
            timeline = current_timeline
        elif current_timeline != timeline:
            missing.append(f"{position.instrument_id}: 위험 관측 시점이 다른 자산과 정렬되지 않습니다.")
            continue
        risk_inputs.append(AssetRiskInput(
            position.instrument_id, converted_value / gross,
            tuple(item.price for item in valid),
        ))
    if missing or len(risk_inputs) != len(priced_positions):
        return None, tuple(missing or ["위험 계산에 필요한 자산 series가 누락되었습니다."])
    return PortfolioRiskAnalyzer().analyze(tuple(risk_inputs)), ()


def _analyze(request: PortfolioAnalysisRequest, fx_override: Mapping[tuple[str, str], Decimal] | None = None) -> PortfolioAnalysisResult:
    state = request.pinned_state
    as_of = _timestamp(state.analysis_as_of, "analysis_as_of")
    unknown: list[str] = []
    unvalued: list[str] = []
    exposures: list[PositionExposure] = []
    converted_positions: dict[str, Decimal | None] = {}
    for position in request.positions:
        amount = _convert(position.market_value, position.currency, request.evaluation_currency, as_of,
                          request.fx_evidence, fx_override)
        converted_positions[position.instrument_id] = amount
        if amount is None:
            unvalued.append(position.instrument_id)
            unknown.append(f"{position.instrument_id}: {position.unvalued_reason or '가치 또는 적격 통화 환산 자료를 확인할 수 없습니다.'}")
        exposures.append(PositionExposure(
            position.instrument_id, amount, account=position.account,
            asset_class=position.asset_class, country=position.country,
            currency=position.currency.upper(), sector=position.sector,
            region=position.region, liquidity=position.liquidity,
            custody=position.custody, leverage=position.leverage,
        ))

    converted_cash: dict[str, Decimal | None] = {}
    for balance in request.cash:
        amount = _convert(balance.amount, balance.currency, request.evaluation_currency, as_of,
                          request.fx_evidence, fx_override)
        converted_cash[balance.balance_id] = amount
        if amount is None:
            unvalued.append(f"cash:{balance.balance_id}")
            unknown.append(f"cash:{balance.balance_id}: {balance.unvalued_reason or '잔액 또는 적격 통화 환산 자료를 확인할 수 없습니다.'}")
        exposures.append(PositionExposure(f"cash:{balance.balance_id}", amount, asset_class="CASH", currency=balance.currency.upper()))

    converted_liabilities: dict[str, Decimal | None] = {}
    for balance in request.liabilities:
        amount = _convert(balance.amount, balance.currency, request.evaluation_currency, as_of,
                          request.fx_evidence, fx_override)
        converted_liabilities[balance.balance_id] = amount
        if amount is None:
            unvalued.append(f"liability:{balance.balance_id}")
            unknown.append(f"liability:{balance.balance_id}: {balance.unvalued_reason or '부채 또는 적격 통화 환산 자료를 확인할 수 없습니다.'}")

    all_assets_known = all(value is not None for value in converted_positions.values()) and all(value is not None for value in converted_cash.values())
    all_liabilities_known = all(value is not None for value in converted_liabilities.values())
    asset_subtotal = sum((value for value in (*converted_positions.values(), *converted_cash.values()) if value is not None), Decimal("0"))
    total_cash = sum((value for value in converted_cash.values() if value is not None), Decimal("0")) if all(value is not None for value in converted_cash.values()) else None
    gross_assets = asset_subtotal if all_assets_known else None
    liabilities = sum((value for value in converted_liabilities.values() if value is not None), Decimal("0")) if all_liabilities_known else None
    net_worth = gross_assets - liabilities if gross_assets is not None and liabilities is not None else None
    allocation = AllocationAnalyzer().analyze(
        exposures, denominator=gross_assets, denominator_resolved=gross_assets is not None,
    )

    risk, risk_missing = _risk_result(request, request.positions, converted_positions, gross_assets)
    unknown.extend(risk_missing)
    if risk is not None and risk.partial:
        unknown.append("정렬된 위험 자료가 불완전하여 portfolio volatility/contribution은 미확정입니다.")
        risk = None

    policy = (request.risk_policy if request.risk_policy and request.risk_policy.approved
              and request.risk_policy.approval_ref and request.risk_policy.validation_ref else None)
    limits: list[RiskLimitAssessment] = []
    for metric, value, limit in (
        ("portfolio_volatility_per_period", risk.volatility if risk else None, policy.max_volatility_per_period if policy else None),
        ("maximum_drawdown", abs(min((asset.max_drawdown for asset in risk.assets if asset.max_drawdown is not None), default=Decimal("0"))) if risk else None,
         policy.max_drawdown if policy else None),
    ):
        if value is None or limit is None:
            limits.append(RiskLimitAssessment(metric, value, limit, LimitStatus.UNKNOWN, "적격 산출값 또는 승인 정책 한도가 없습니다."))
        else:
            limits.append(RiskLimitAssessment(metric, value, limit,
                                              LimitStatus.BREACHED if value > limit else LimitStatus.WITHIN,
                                              "명시된 승인 한도와 대조했습니다."))
    if request.period_policy is None:
        unknown.append("위험 분석 기간 정책이 없습니다.")
    if policy is None:
        unknown.append("승인된 위험 정책 provenance가 없습니다.")

    availability = Availability.PARTIAL if unknown else Availability.AVAILABLE
    lines = [
        f"상태 기준: state_version={state.state_version}; snapshot={state.snapshot_ref}; portfolio_as_of={state.portfolio_data_as_of}.",
        f"평가통화: {request.evaluation_currency.upper()}.",
        f"총자산: {gross_assets if gross_assets is not None else 'UNKNOWN'}; 확인된 자산 소계: {asset_subtotal}.",
        f"현금: {total_cash if total_cash is not None else 'UNKNOWN'}.",
        f"부채: {liabilities if liabilities is not None else 'UNKNOWN'}; 순자산: {net_worth if net_worth is not None else 'UNKNOWN'}.",
        "미평가 항목: " + (", ".join(sorted(unvalued)) if unvalued else "없음"),
        "자산군 비중: " + (", ".join(f"{key}={value}" for key, value in allocation.by_asset_class.items()) or "UNKNOWN"),
        "통화 비중: " + (", ".join(f"{key}={value}" for key, value in allocation.by_currency.items()) or "UNKNOWN"),
        "위험: " + (f"기간별 변동성 {risk.volatility}" if risk and risk.volatility is not None else "UNKNOWN"),
    ]
    lines.extend(
        f"위험 한도 {item.metric}: {item.status.value}; value={item.value if item.value is not None else 'UNKNOWN'}; limit={item.limit if item.limit is not None else 'UNKNOWN'}."
        for item in limits
    )
    lines.extend(f"UNKNOWN: {reason}" for reason in unknown)
    section = ReportSectionInput(
        name="portfolio_analysis", title="Portfolio Analysis", status=availability,
        lines=tuple(lines), metadata={"state_version": state.state_version,
                                    "snapshot_ref": state.snapshot_ref,
                                    "evaluation_currency": request.evaluation_currency.upper()},
    )
    return PortfolioAnalysisResult(
        availability, state.state_version, state.snapshot_ref, request.evaluation_currency.upper(),
        asset_subtotal, total_cash, gross_assets, liabilities, net_worth, tuple(sorted(unvalued)),
        allocation, risk, tuple(limits), tuple(unknown), section,
    )


def analyze_portfolio(request: PortfolioAnalysisRequest) -> PortfolioAnalysisResult:
    """Calculate only supported allocation/risk facts from the pinned portfolio snapshot."""
    return _analyze(request)


def simulate_portfolio_scenario(
    request: PortfolioAnalysisRequest,
    scenario: PortfolioScenario,
    *,
    gate_verifier: Callable[[ScenarioApproval], bool] | None = None,
) -> PortfolioScenarioResult:
    """Apply explicit value/FX/risk shocks in memory and return partial-aware deltas."""
    missing: list[str] = []
    if not scenario.scenario_id.strip() or not scenario.description.strip():
        missing.append("시나리오 식별자와 설명이 없습니다.")
    if scenario.approval is None or not (
        scenario.approval.enabled and scenario.approval.gate_id.strip()
        and scenario.approval.policy_ref.strip() and scenario.approval.approval_ref.strip()
        and scenario.approval.validation_ref.strip()
    ):
        missing.append("활성 상태의 시나리오 gate와 승인/검증 reference가 없습니다.")
    elif gate_verifier is None:
        missing.append("등록된 시나리오 gate verifier가 없습니다.")
    elif not gate_verifier(scenario.approval):
        missing.append("시나리오 gate verifier가 승인/검증 reference를 확인하지 못했습니다.")
    if not scenario.adjustments and not scenario.fx_assumptions and not scenario.risk_shocks:
        missing.append("명시적 가상 변경·FX·위험 가정이 없습니다.")
    if missing:
        section = ReportSectionInput(
            name="portfolio_scenario", title="Portfolio Scenario", status=Availability.UNAVAILABLE,
            lines=tuple("WAIT: " + item for item in missing),
            metadata={"scenario_id": scenario.scenario_id or "UNKNOWN"},
        )
        return PortfolioScenarioResult(ScenarioStatus.WAIT, scenario.scenario_id, None, None, None, None, None, None, tuple(missing), section)

    fx_override: dict[tuple[str, str], Decimal] = {}
    for assumption in scenario.fx_assumptions:
        key = (assumption.from_currency.upper(), assumption.to_currency.upper())
        if key[0] == key[1] or key[1] != request.evaluation_currency.upper():
            missing.append(f"FX 가정은 다른 통화에서 평가통화로 지정해야 합니다: {key[0]}/{key[1]}.")
        if key in fx_override:
            missing.append(f"FX 가정 중복: {key[0]}/{key[1]}.")
        fx_override[key] = assumption.rate
    if missing:
        section = ReportSectionInput("portfolio_scenario", "Portfolio Scenario", status=Availability.UNAVAILABLE,
                                     lines=tuple("WAIT: " + item for item in missing),
                                     metadata={"scenario_id": scenario.scenario_id})
        return PortfolioScenarioResult(ScenarioStatus.WAIT, scenario.scenario_id, None, None, None, None, None, None, tuple(missing), section)

    # A scenario assumption can change only the hypothetical after-state. The
    # baseline must be supported by actual eligible portfolio/FX evidence.
    before = _analyze(request)
    if before.gross_assets is None or before.total_liabilities is None or before.net_worth is None:
        missing.append("완전한 valued asset/cash/liability baseline이 없어 전체 차이를 계산할 수 없습니다.")
    position_map = {item.instrument_id: item for item in request.positions}
    cash_map = {item.balance_id: item for item in request.cash}
    liability_map = {item.balance_id: item for item in request.liabilities}
    for adjustment in scenario.adjustments:
        target_map = {
            ScenarioTargetKind.POSITION: position_map,
            ScenarioTargetKind.CASH: cash_map,
            ScenarioTargetKind.LIABILITY: liability_map,
        }[adjustment.target_kind]
        target = target_map.get(adjustment.target_id)
        if target is None:
            missing.append(f"시나리오 대상이 baseline에 없습니다: {adjustment.target_kind.value}/{adjustment.target_id}.")
        elif target.currency.upper() != adjustment.currency.upper():
            missing.append(f"시나리오 금액 통화가 baseline과 다릅니다: {adjustment.target_id}.")
        elif (target.market_value is None if adjustment.target_kind is ScenarioTargetKind.POSITION else target.amount is None):
            missing.append(f"미평가 baseline에 값을 임의로 보충할 수 없습니다: {adjustment.target_id}.")
        else:
            prior_value = target.market_value if adjustment.target_kind is ScenarioTargetKind.POSITION else target.amount
            assert prior_value is not None
            after_value = prior_value + adjustment.value_delta
            if after_value < 0:
                missing.append(f"시나리오 변경으로 값이 음수가 됩니다: {adjustment.target_id}.")
            elif adjustment.target_kind is ScenarioTargetKind.POSITION:
                position_map[adjustment.target_id] = replace(target, market_value=after_value)
            elif adjustment.target_kind is ScenarioTargetKind.CASH:
                cash_map[adjustment.target_id] = replace(target, amount=after_value)
            else:
                liability_map[adjustment.target_id] = replace(target, amount=after_value)

    positions_after = tuple(position_map.values())
    cash_after = tuple(cash_map.values())
    liabilities_after = tuple(liability_map.values())
    series_map = {series.instrument_id: series for series in request.price_series}
    risk_shock_by_id = {shock.instrument_id: shock for shock in scenario.risk_shocks}
    if len(risk_shock_by_id) != len(scenario.risk_shocks):
        missing.append("scenario risk shock 자산이 중복되었습니다.")
    for shock in scenario.risk_shocks:
        series = series_map.get(shock.instrument_id)
        if shock.instrument_id not in position_map or series is None or not series.observations:
            missing.append(f"scenario risk shock price series 누락: {shock.instrument_id}.")
    if missing:
        section = ReportSectionInput(
            name="portfolio_scenario", title="Portfolio Scenario", status=Availability.UNAVAILABLE,
            lines=tuple("WAIT: " + item for item in missing), metadata={"scenario_id": scenario.scenario_id},
        )
        return PortfolioScenarioResult(ScenarioStatus.WAIT, scenario.scenario_id, before, None, None, None, None, None, tuple(missing), section)

    shocked_series: list[HistoricalPriceSeries] = []
    for series in request.price_series:
        shock = risk_shock_by_id.get(series.instrument_id)
        if shock is None:
            shocked_series.append(series)
            continue
        observations = list(series.observations)
        if observations:
            final = observations[-1]
            observations[-1] = replace(final, price=final.price * (Decimal("1") + shock.last_observation_return_shock))
        shocked_series.append(replace(series, observations=tuple(observations)))
    after_request = replace(request, positions=positions_after, cash=cash_after,
                            liabilities=liabilities_after, price_series=tuple(shocked_series))
    after = _analyze(after_request, fx_override)
    gross_delta = after.gross_assets - before.gross_assets if after.gross_assets is not None and before.gross_assets is not None else None
    liability_delta = after.total_liabilities - before.total_liabilities if after.total_liabilities is not None and before.total_liabilities is not None else None
    net_delta = after.net_worth - before.net_worth if after.net_worth is not None and before.net_worth is not None else None
    risk_delta = after.risk.volatility - before.risk.volatility if after.risk and before.risk and after.risk.volatility is not None and before.risk.volatility is not None else None
    unknown = []
    if gross_delta is None or liability_delta is None or net_delta is None:
        unknown.append("전체 baseline/delta를 계산할 수 없습니다.")
    if scenario.risk_shocks and risk_delta is None:
        unknown.append("정책/기간/가격 자료가 불완전하여 위험 충격 delta는 UNKNOWN입니다.")
    lines = [
        f"가상 scenario={scenario.scenario_id}: {scenario.description}",
        "위험 충격은 마지막 과거 관측값에 적용한 가상 stress이며 예측이나 최신 시세가 아닙니다.",
        f"기준 총자산={before.gross_assets if before.gross_assets is not None else 'UNKNOWN'}; 이후 총자산={after.gross_assets if after.gross_assets is not None else 'UNKNOWN'}; delta={gross_delta if gross_delta is not None else 'UNKNOWN'}.",
        f"기준 부채={before.total_liabilities if before.total_liabilities is not None else 'UNKNOWN'}; 이후 부채={after.total_liabilities if after.total_liabilities is not None else 'UNKNOWN'}; delta={liability_delta if liability_delta is not None else 'UNKNOWN'}.",
        f"순자산 delta={net_delta if net_delta is not None else 'UNKNOWN'}; 위험 변동성 delta={risk_delta if risk_delta is not None else 'UNKNOWN'}.",
        "가정 refs: " + ", ".join(sorted({item.assumption_ref for item in scenario.adjustments} | {item.assumption_ref for item in scenario.fx_assumptions} | {item.assumption_ref for item in scenario.risk_shocks})),
    ]
    lines.extend(f"UNKNOWN: {item}" for item in unknown)
    availability = Availability.PARTIAL if unknown or before.availability is Availability.PARTIAL or after.availability is Availability.PARTIAL else Availability.AVAILABLE
    section = ReportSectionInput(
        name="portfolio_scenario", title="Portfolio Scenario", status=availability,
        lines=tuple(lines), metadata={"scenario_id": scenario.scenario_id,
                                    "state_version": request.pinned_state.state_version,
                                    "snapshot_ref": request.pinned_state.snapshot_ref,
                                    "posting_enabled": False},
    )
    status = ScenarioStatus.PARTIAL if availability is Availability.PARTIAL else ScenarioStatus.COMPLETED
    return PortfolioScenarioResult(status, scenario.scenario_id, before, after, gross_delta, liability_delta,
                                   net_delta, risk_delta, tuple(unknown), section)


__all__ = [
    "FxEvidence", "HistoricalPriceSeries", "LimitStatus", "MoneyBalance", "PinnedPortfolioState",
    "PortfolioAnalysisRequest", "PortfolioAnalysisResult", "PortfolioPosition", "PortfolioRiskPolicy",
    "PortfolioScenario", "PortfolioScenarioResult", "RiskLimitAssessment", "RiskObservation",
    "RiskPeriodPolicy", "ScenarioAdjustment", "ScenarioApproval", "ScenarioFxAssumption",
    "ScenarioRiskShock", "ScenarioStatus", "ScenarioTargetKind", "analyze_portfolio",
    "simulate_portfolio_scenario",
]
