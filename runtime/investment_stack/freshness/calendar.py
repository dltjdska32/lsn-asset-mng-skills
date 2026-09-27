"""Explicit, provenance-carrying exchange session schedules.

Schedules are supplied by an approved official calendar adapter or a pinned
fixture. Source hostnames alone do not prove session completeness; LAST_VALID_CLOSE
requires exact equality with the immutable pinned schedule registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from types import MappingProxyType
from typing import Mapping
from urllib.parse import urlparse
from zoneinfo import ZoneInfo


_OFFICIAL_HOSTS = {
    "NASDAQ": {"nasdaqtrader.com", "www.nasdaq.com"},
    "NYSE": {"www.nyse.com", "tv.nyse.com"},
    "KRX": {"global.krx.co.kr", "trn.krx.co.kr", "www.mois.go.kr"},
}


@dataclass(frozen=True, slots=True)
class ExchangeSession:
    session_date: date
    opens_at: datetime
    closes_at: datetime


@dataclass(frozen=True, slots=True)
class ExchangeCalendarSchedule:
    exchange: str
    currency: str
    timezone: str
    schedule_id: str
    source_urls: tuple[str, ...]
    coverage_start: date
    coverage_end: date
    sessions: tuple[ExchangeSession, ...]
    close_timestamp_tolerance: timedelta = timedelta(seconds=1)

    def __post_init__(self) -> None:
        exchange = self.exchange.upper()
        if exchange not in _OFFICIAL_HOSTS:
            raise ValueError(f"Unsupported exchange calendar: {self.exchange}")
        if not self.schedule_id or not self.source_urls or not self.currency:
            raise ValueError("schedule_id, currency, and official source_urls are required")
        if self.coverage_start > self.coverage_end or self.close_timestamp_tolerance < timedelta(0):
            raise ValueError("invalid calendar coverage or close tolerance")
        ZoneInfo(self.timezone)
        hosts = {urlparse(url).hostname for url in self.source_urls if urlparse(url).scheme == "https"}
        if not hosts or not hosts.issubset(_OFFICIAL_HOSTS[exchange]):
            raise ValueError(f"Calendar source is not approved for {exchange}")
        previous: date | None = None
        for session in self.sessions:
            if not self.coverage_start <= session.session_date <= self.coverage_end:
                raise ValueError("session outside declared coverage")
            if previous is not None and session.session_date <= previous:
                raise ValueError("calendar sessions must be unique and chronological")
            if session.opens_at.tzinfo is None or session.closes_at.tzinfo is None:
                raise ValueError("session open and close timestamps must be timezone-aware")
            local_open = session.opens_at.astimezone(ZoneInfo(self.timezone))
            local_close = session.closes_at.astimezone(ZoneInfo(self.timezone))
            if local_open.date() != session.session_date or local_close.date() != session.session_date:
                raise ValueError("session timestamp dates do not match session_date")
            if local_open >= local_close:
                raise ValueError("session open must precede session close")
            previous = session.session_date

    def covers(self, start: date, end: date) -> bool:
        return self.coverage_start <= start <= end <= self.coverage_end

    def session_for_date(self, value: date) -> ExchangeSession | None:
        return next((session for session in self.sessions if session.session_date == value), None)

    def latest_completed_session(self, cutoff: datetime) -> ExchangeSession | None:
        local_cutoff = cutoff.astimezone(ZoneInfo(self.timezone))
        if not self.coverage_start <= local_cutoff.date() <= self.coverage_end:
            return None
        return next((session for session in reversed(self.sessions) if session.closes_at <= cutoff), None)

    def is_regular_session_open(self, cutoff: datetime) -> bool:
        local_cutoff = cutoff.astimezone(ZoneInfo(self.timezone))
        session = self.session_for_date(local_cutoff.date())
        return bool(session and session.opens_at <= cutoff < session.closes_at)

    @property
    def is_pinned(self) -> bool:
        return PINNED_CALENDARS.get((self.exchange.upper(), self.schedule_id)) == self


def _session(day: str, timezone: str, opens: str, closes: str) -> ExchangeSession:
    local = ZoneInfo(timezone)
    return ExchangeSession(
        date.fromisoformat(day),
        datetime.fromisoformat(f"{day}T{opens}").replace(tzinfo=local),
        datetime.fromisoformat(f"{day}T{closes}").replace(tzinfo=local),
    )


# Bounded, pinned snapshots used by the Sep 2026 qualification path. Any date
# outside these windows needs a new officially sourced/pinned schedule release.
_nasdaq_sources = ("https://nasdaqtrader.com/Trader.aspx?id=Calendar",)
_krx_sources = (
    "https://global.krx.co.kr/contents/GLB/06/0602/0602010201/GLB0602010201T1.jsp",
    "https://www.mois.go.kr/frt/bbs/type010/commonSelectBoardArticle.do?bbsId=BBSMSTR_000000000008&nttId=129490",
    "https://trn.krx.co.kr/index.jsp",
)
PINNED_CALENDARS: Mapping[tuple[str, str], ExchangeCalendarSchedule] = MappingProxyType({
    ("NASDAQ", "nasdaq-2026-09-official-snapshot-v1"): ExchangeCalendarSchedule(
        "NASDAQ", "USD", "America/New_York", "nasdaq-2026-09-official-snapshot-v1", _nasdaq_sources,
        date(2026, 9, 24), date(2026, 9, 28),
        (_session("2026-09-24", "America/New_York", "09:30:00", "16:00:00"),
         _session("2026-09-25", "America/New_York", "09:30:00", "16:00:00"),
         _session("2026-09-28", "America/New_York", "09:30:00", "16:00:00")),
        timedelta(seconds=1),
    ),
    ("KRX", "krx-2026-chuseok-official-snapshot-v1"): ExchangeCalendarSchedule(
        "KRX", "KRW", "Asia/Seoul", "krx-2026-chuseok-official-snapshot-v1", _krx_sources,
        date(2026, 9, 22), date(2026, 9, 28),
        (_session("2026-09-22", "Asia/Seoul", "09:00:00", "15:30:00"),
         _session("2026-09-23", "Asia/Seoul", "09:00:00", "15:30:00"),
         _session("2026-09-28", "Asia/Seoul", "09:00:00", "15:30:00")),
        timedelta(seconds=0),
    ),
})


def get_pinned_calendar(exchange: str) -> ExchangeCalendarSchedule | None:
    """Return the bounded official snapshot bundled with this runtime, if any."""
    return next((value for (key, _), value in PINNED_CALENDARS.items() if key == exchange.upper()), None)
