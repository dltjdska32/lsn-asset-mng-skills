"""Cross-asset allocation aggregation that preserves unvalued positions."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable


@dataclass(frozen=True, slots=True)
class PositionExposure:
    instrument_id: str
    value: Decimal | None
    account: str | None = None
    asset_class: str | None = None
    country: str | None = None
    currency: str | None = None
    sector: str | None = None
    region: str | None = None
    liquidity: str | None = None
    custody: str | None = None
    leverage: Decimal | None = None
    lookthrough: tuple[tuple[str, Decimal], ...] = ()


@dataclass(frozen=True, slots=True)
class AllocationResult:
    valued_total: Decimal
    valued_positions: int
    unvalued_positions: tuple[str, ...]
    by_asset_class: dict[str, Decimal]
    by_country: dict[str, Decimal]
    by_currency: dict[str, Decimal]
    by_sector: dict[str, Decimal]
    by_region: dict[str, Decimal]
    by_account: dict[str, Decimal]
    by_liquidity: dict[str, Decimal]
    by_custody: dict[str, Decimal]
    lookthrough_exposure: dict[str, Decimal]
    weighted_leverage: Decimal | None
    status: str = "AVAILABLE"
    denominator: Decimal | None = None


class AllocationAnalyzer:
    def analyze(
        self,
        positions: Iterable[PositionExposure],
        *,
        denominator: Decimal | None = None,
        denominator_resolved: bool = True,
    ) -> AllocationResult:
        items = tuple(positions)
        valued = tuple(item for item in items if item.value is not None)
        component_total = sum((item.value for item in valued if item.value is not None), Decimal("0"))
        total = denominator if denominator is not None else component_total
        weighting_total = total if denominator_resolved else Decimal("0")
        return AllocationResult(
            component_total,
            len(valued),
            tuple(item.instrument_id for item in items if item.value is None),
            self._axis(valued, "asset_class", weighting_total),
            self._axis(valued, "country", weighting_total),
            self._axis(valued, "currency", weighting_total),
            self._axis(valued, "sector", weighting_total),
            self._axis(valued, "region", weighting_total),
            self._axis(valued, "account", weighting_total),
            self._axis(valued, "liquidity", weighting_total),
            self._axis(valued, "custody", weighting_total),
            self._lookthrough(valued, weighting_total),
            self._weighted_leverage(valued, weighting_total),
            "AVAILABLE" if denominator_resolved else "PARTIAL",
            total if denominator_resolved else None,
        )

    @staticmethod
    def _axis(items: tuple[PositionExposure, ...], field: str, total: Decimal) -> dict[str, Decimal]:
        if total == 0:
            return {}
        raw: dict[str, Decimal] = {}
        for item in items:
            key = getattr(item, field)
            if key and item.value is not None:
                raw[key] = raw.get(key, Decimal("0")) + item.value
        return {key: value / total for key, value in sorted(raw.items())}

    @staticmethod
    def _lookthrough(items: tuple[PositionExposure, ...], total: Decimal) -> dict[str, Decimal]:
        if total == 0:
            return {}
        raw: dict[str, Decimal] = {}
        for item in items:
            if item.value is None:
                continue
            for label, weight in item.lookthrough:
                raw[label] = raw.get(label, Decimal("0")) + item.value * weight
        return {key: value / total for key, value in sorted(raw.items())}

    @staticmethod
    def _weighted_leverage(items: tuple[PositionExposure, ...], total: Decimal) -> Decimal | None:
        if total == 0:
            return None
        known = [item for item in items if item.value is not None and item.leverage is not None]
        if not known:
            return None
        return sum((item.value * item.leverage for item in known), Decimal("0")) / total
