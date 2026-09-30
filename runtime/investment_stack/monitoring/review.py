"""Deterministic monitoring that does not replace D12 B prices.

Drop flags, alerts, news deduplication, and the volatility shadow price are
review context. They never post an order or change the 80/75/70 entry prices.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from statistics import median
from urllib.parse import urlsplit, urlunsplit


_SESSION_DROP = Decimal("-0.05")
_FIVE_SESSION_DROP = Decimal("-0.08")
_BAR_DROP = Decimal("-0.03")
_VOLUME_MULTIPLE = Decimal("2")
_MAX_VOLATILITY_HAIRCUT = Decimal("0.05")
_CUSTOMER_CONCENTRATION = Decimal("0.20")
_DATACENTER_FIELDS = ("power", "permit", "schedule", "customer", "funding")


@dataclass(frozen=True, slots=True)
class BarClose:
    close: Decimal
    volume: Decimal | None = None


@dataclass(frozen=True, slots=True)
class DropReview:
    status: str
    session_return: Decimal | None
    five_session_return: Decimal | None
    one_bar_return: Decimal | None
    volume_ratio: Decimal | None
    reason: str


@dataclass(frozen=True, slots=True)
class AlertDecision:
    status: str
    reason: str


def _return(new: Decimal, old: Decimal) -> Decimal | None:
    if old == 0:
        return None
    return (new - old) / old


def review_drops(bars: tuple[BarClose, ...]) -> DropReview:
    """Classify completed closes. Two closes are required; otherwise WAIT."""
    if len(bars) < 2:
        return DropReview("WAIT", None, None, None, None, "completed bars are missing")
    session_return = _return(bars[-1].close, bars[-2].close)
    one_bar_return = session_return
    five_session_return = _return(bars[-1].close, bars[-6].close) if len(bars) >= 6 else None
    volumes = [bar.volume for bar in bars[:-1] if bar.volume is not None]
    volume_ratio = None
    if bars[-1].volume is not None and volumes:
        baseline = Decimal(str(median(volumes[-20:])))
        if baseline > 0:
            volume_ratio = bars[-1].volume / baseline
    triggered = (
        (session_return is not None and session_return <= _SESSION_DROP)
        or (five_session_return is not None and five_session_return <= _FIVE_SESSION_DROP)
        or (
            one_bar_return is not None and one_bar_return <= _BAR_DROP
            and volume_ratio is not None and volume_ratio >= _VOLUME_MULTIPLE
        )
    )
    if triggered:
        return DropReview(
            "DROP_REVIEW", session_return, five_session_return, one_bar_return, volume_ratio,
            "stored closes crossed the review threshold; D12 entry prices are unchanged",
        )
    return DropReview(
        "NO_DROP", session_return, five_session_return, one_bar_return, volume_ratio,
        "stored closes did not cross the review threshold",
    )


def volatility_shadow_price(policy_price: Decimal, bars: tuple[BarClose, ...]) -> Decimal | None:
    """Return a review-only price. The caller must keep the D12 price as the action price."""
    if len(bars) < 3 or policy_price <= 0:
        return None
    returns = []
    for previous, current in zip(bars, bars[1:]):
        change = _return(current.close, previous.close)
        if change is not None:
            returns.append(change)
    if len(returns) < 2:
        return None
    mean = sum(returns, Decimal(0)) / Decimal(len(returns))
    variance = sum((item - mean) ** 2 for item in returns) / Decimal(len(returns))
    deviation = variance.sqrt()
    haircut = min(deviation, _MAX_VOLATILITY_HAIRCUT)
    return policy_price * (Decimal(1) - haircut)


def news_identity(url: str | None, title: str | None) -> str:
    if url:
        parts = urlsplit(url.strip())
        normalized = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))
        if normalized:
            return normalized
    compact = " ".join((title or "").casefold().split())
    return compact or "untitled"


def dedupe_news(items: tuple[dict, ...]) -> tuple[dict, ...]:
    seen: set[str] = set()
    kept: list[dict] = []
    for item in items:
        identity = str(item.get("event_cluster_id") or news_identity(
            item.get("source_url") if isinstance(item.get("source_url"), str) else None,
            item.get("title") if isinstance(item.get("title"), str) else None,
        ))
        if identity in seen:
            continue
        seen.add(identity)
        kept.append(item)
    return tuple(kept)


def decide_alert(
    *,
    known_event_ids: frozenset[str],
    incoming_event_ids: tuple[str, ...],
    drop_status: str,
    last_checked_at: datetime | None,
    observed_at: datetime | None,
) -> AlertDecision:
    """Alert only for a new event id or a new drop review. Repeats stay NO_ALERT."""
    if last_checked_at is not None and observed_at is not None and observed_at <= last_checked_at and drop_status != "DROP_REVIEW":
        return AlertDecision("NO_ALERT", "observation is not later than the saved check")
    fresh = tuple(item for item in incoming_event_ids if item not in known_event_ids)
    if drop_status == "DROP_REVIEW" or fresh:
        return AlertDecision("ALERT", "new drop review or an event id that was not saved")
    return AlertDecision("NO_ALERT", "no new event and no drop review")


def guidance_delta(previous: Decimal | None, current: Decimal | None) -> Decimal | None:
    if previous is None or current is None:
        return None
    return current - previous


def customer_concentration(shares: tuple[tuple[str, Decimal], ...]) -> tuple[str, Decimal | None]:
    total = sum((amount for _, amount in shares), Decimal(0))
    if not shares or total <= 0:
        return "WAIT", None
    top_name, top_amount = max(shares, key=lambda item: item[1])
    ratio = top_amount / total
    if ratio >= _CUSTOMER_CONCENTRATION:
        return f"CONCENTRATED:{top_name}", ratio
    return "DISCLOSED", ratio


def datacenter_status(record: dict | None) -> dict[str, str]:
    """Track explicit data-center facts. Missing fields stay waiting and no score is created."""
    source = record or {}
    status: dict[str, str] = {}
    for field in _DATACENTER_FIELDS:
        value = source.get(field)
        status[field] = str(value) if isinstance(value, str) and value.strip() else "WAIT"
    return status


def bundled_jpx_calendar():
    """Return the official 2026 JPX holiday snapshot. It does not invent a quote."""
    from investment_stack.freshness.calendar import get_pinned_calendar

    return get_pinned_calendar("JPX")


def thirteen_f_trade_adoption(record: dict | None) -> str:
    """A stored flag cannot turn a 13F score into an order condition."""
    del record
    return "DISABLED"
