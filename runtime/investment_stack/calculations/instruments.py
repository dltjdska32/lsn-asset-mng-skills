"""Three-axis instrument resolution used to select the Phase 5 analysis path."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class EconomicUnderlying(StrEnum):
    COMPANY = "COMPANY"
    EQUITY_INDEX = "EQUITY_INDEX"
    BITCOIN = "BITCOIN"
    GOLD = "GOLD"
    SILVER = "SILVER"
    OTHER = "OTHER"


class InstrumentWrapper(StrEnum):
    LISTED_EQUITY = "LISTED_EQUITY"
    ETF = "ETF"
    ETP = "ETP"
    FUND = "FUND"
    TRUST = "TRUST"
    NATIVE_CRYPTO = "NATIVE_CRYPTO"
    PHYSICAL = "PHYSICAL"
    EXCHANGE_SPOT = "EXCHANGE_SPOT"
    FUTURE = "FUTURE"
    OPTION = "OPTION"
    LEVERAGED = "LEVERAGED"


class AnalysisRoute(StrEnum):
    EQUITY = "EQUITY"
    FUND = "FUND"
    ALTERNATIVE = "ALTERNATIVE"
    DERIVATIVE_LIMITED = "DERIVATIVE_LIMITED"


@dataclass(frozen=True, slots=True)
class InstrumentProfile:
    instrument_id: str
    economic_underlying: EconomicUnderlying
    instrument_wrapper: InstrumentWrapper
    custody_or_account: str | None = None


@dataclass(frozen=True, slots=True)
class InstrumentResolution:
    profile: InstrumentProfile
    route: AnalysisRoute
    requires_alternative_context: bool


_FUND_WRAPPERS = frozenset({InstrumentWrapper.ETF, InstrumentWrapper.ETP, InstrumentWrapper.FUND, InstrumentWrapper.TRUST})
_DERIVATIVE_WRAPPERS = frozenset({InstrumentWrapper.FUTURE, InstrumentWrapper.OPTION, InstrumentWrapper.LEVERAGED})
_ALT_UNDERLYINGS = frozenset({EconomicUnderlying.BITCOIN, EconomicUnderlying.GOLD, EconomicUnderlying.SILVER})


def resolve_instrument(profile: InstrumentProfile) -> InstrumentResolution:
    wrapper = profile.instrument_wrapper
    underlying = profile.economic_underlying
    if wrapper in _DERIVATIVE_WRAPPERS:
        return InstrumentResolution(profile, AnalysisRoute.DERIVATIVE_LIMITED, underlying in _ALT_UNDERLYINGS)
    if wrapper in _FUND_WRAPPERS:
        return InstrumentResolution(profile, AnalysisRoute.FUND, underlying in _ALT_UNDERLYINGS)
    if wrapper is InstrumentWrapper.LISTED_EQUITY:
        return InstrumentResolution(profile, AnalysisRoute.EQUITY, False)
    if underlying in _ALT_UNDERLYINGS and wrapper in {
        InstrumentWrapper.NATIVE_CRYPTO,
        InstrumentWrapper.PHYSICAL,
        InstrumentWrapper.EXCHANGE_SPOT,
    }:
        return InstrumentResolution(profile, AnalysisRoute.ALTERNATIVE, False)
    raise ValueError(
        f"unsupported or ambiguous instrument combination: {underlying.value}/{wrapper.value}"
    )
