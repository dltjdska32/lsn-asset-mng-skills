"""Materiality gate that precedes portfolio deep research."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Iterable


class MaterialityDecision(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    AUTO_PASS_USER_SPECIFIED = "AUTO_PASS_USER_SPECIFIED"
    PASS_UNCERTAINTY = "PASS_UNCERTAINTY"


@dataclass(frozen=True, slots=True)
class MaterialityConfig:
    version: str
    min_weight: Decimal
    min_risk_proxy: Decimal
    uncertainty_pass_threshold: Decimal


@dataclass(frozen=True, slots=True)
class LightweightAsset:
    instrument_id: str
    confirmed_quantity: Decimal
    valued_weight: Decimal | None
    liquidity_score: Decimal | None
    risk_proxy: Decimal | None
    data_uncertainty: Decimal
    user_specified: bool = False
    strategic_relevance: bool = False


@dataclass(frozen=True, slots=True)
class MaterialityResult:
    instrument_id: str
    decision: MaterialityDecision
    reasons: tuple[str, ...]
    config_version: str


class MaterialityEngine:
    def __init__(self, config: MaterialityConfig) -> None:
        self.config = config

    def evaluate(self, asset: LightweightAsset) -> MaterialityResult:
        if asset.user_specified:
            return MaterialityResult(asset.instrument_id, MaterialityDecision.AUTO_PASS_USER_SPECIFIED, ("direct user specification",), self.config.version)
        reasons: list[str] = []
        if asset.valued_weight is not None and asset.valued_weight >= self.config.min_weight:
            reasons.append("portfolio weight threshold")
        if asset.risk_proxy is not None and asset.risk_proxy >= self.config.min_risk_proxy:
            reasons.append("lightweight risk threshold")
        if asset.strategic_relevance:
            reasons.append("strategic relevance")
        if reasons:
            return MaterialityResult(asset.instrument_id, MaterialityDecision.PASS, tuple(reasons), self.config.version)
        if asset.data_uncertainty >= self.config.uncertainty_pass_threshold and asset.confirmed_quantity != 0:
            return MaterialityResult(asset.instrument_id, MaterialityDecision.PASS_UNCERTAINTY, ("material uncertainty on confirmed position",), self.config.version)
        return MaterialityResult(asset.instrument_id, MaterialityDecision.FAIL, ("below configured materiality thresholds",), self.config.version)

    def evaluate_all(self, assets: Iterable[LightweightAsset]) -> tuple[MaterialityResult, ...]:
        return tuple(self.evaluate(asset) for asset in assets)
