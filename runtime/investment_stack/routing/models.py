"""Typed routing models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RequestMode(StrEnum):
    """The complete and closed set of v1.3 request modes."""

    ASSET_UPDATE = "ASSET_UPDATE"
    PERSONAL_PORTFOLIO_ANALYSIS = "PERSONAL_PORTFOLIO_ANALYSIS"
    SINGLE_ASSET_ANALYSIS = "SINGLE_ASSET_ANALYSIS"
    ASSET_COMPARISON = "ASSET_COMPARISON"
    PORTFOLIO_SCENARIO = "PORTFOLIO_SCENARIO"
    THESIS_REVIEW = "THESIS_REVIEW"
    REPORT_REFRESH = "REPORT_REFRESH"

    @classmethod
    def parse(cls, value: str | RequestMode) -> RequestMode:
        if isinstance(value, cls):
            return value
        normalized = value.strip().upper().replace("-", "_").replace(" ", "_")
        try:
            return cls(normalized)
        except ValueError as exc:
            supported = ", ".join(mode.value for mode in cls)
            raise ValueError(f"Unsupported request mode {value!r}; expected one of: {supported}") from exc


class RequestIntent(StrEnum):
    ANALYSIS = "ANALYSIS"
    TRANSACTION_FACT = "TRANSACTION_FACT"
    BUY_QUESTION = "BUY_QUESTION"
    NEGATED_TRANSACTION = "NEGATED_TRANSACTION"
    ORDER_COMMAND = "ORDER_COMMAND"
    HYPOTHETICAL = "HYPOTHETICAL"
    REPORT_REFRESH = "REPORT_REFRESH"


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    """A deterministic routing result with an auditable reason."""

    mode: RequestMode
    reason: str
    explicit: bool = False
    intent: RequestIntent = RequestIntent.ANALYSIS
    supported: bool = True
    unsupported_reason: str | None = None

    def as_dict(self) -> dict[str, str | bool | None]:
        return {
            "mode": self.mode.value,
            "reason": self.reason,
            "explicit": self.explicit,
            "intent": self.intent.value,
            "supported": self.supported,
            "unsupported_reason": self.unsupported_reason,
        }

