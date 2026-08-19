"""Free-first concrete provider adapters. Network execution stays injectable."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from urllib.parse import urlencode

from investment_stack.providers.credentials import EnvironmentCredentials
from investment_stack.providers.http import ProviderTransportError, Transport, fetch_json, urllib_transport
from investment_stack.providers.models import (
    ProviderObservation,
    ProviderRequest,
    ProviderResult,
    ProviderStatus,
)
from investment_stack.providers.registry import ProviderCapability


class ProviderAdapter(Protocol):
    name: str
    capabilities: frozenset[ProviderCapability]

    def fetch(self, request: ProviderRequest) -> ProviderResult: ...


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class OpenDartAdapter:
    credentials: EnvironmentCredentials
    transport: Transport = urllib_transport
    timeout: float = 15.0
    name: str = "opendart"
    capabilities: frozenset[ProviderCapability] = frozenset({ProviderCapability.FUNDAMENTALS})

    def fetch(self, request: ProviderRequest) -> ProviderResult:
        if request.capability not in self.capabilities:
            return ProviderResult(self.name, request.capability, ProviderStatus.UNAVAILABLE, reason="capability unsupported")
        key = self.credentials.get("OPENDART_API_KEY")
        if key is None:
            return ProviderResult(self.name, request.capability, ProviderStatus.MISSING_CREDENTIAL, reason="credential unavailable")
        corp_code = str(request.parameters.get("corp_code", "")).strip()
        year = str(request.parameters.get("business_year", "")).strip()
        report_code = str(request.parameters.get("report_code", "")).strip()
        fs_div = str(request.parameters.get("fs_div", "CFS")).strip() or "CFS"
        if not corp_code or not year or not report_code:
            return ProviderResult(self.name, request.capability, ProviderStatus.UNAVAILABLE, reason="corp_code, business_year and report_code are required")
        query = urlencode({"crtfc_key": key, "corp_code": corp_code, "bsns_year": year, "reprt_code": report_code, "fs_div": fs_div})
        public_url = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
        try:
            data = fetch_json(f"{public_url}?{query}", timeout=self.timeout, transport=self.transport)
        except ProviderTransportError as exc:
            return ProviderResult(self.name, request.capability, ProviderStatus.ERROR, reason=str(exc))
        if not isinstance(data, dict) or str(data.get("status", "")) not in {"000", ""}:
            return ProviderResult(self.name, request.capability, ProviderStatus.UNAVAILABLE, reason="OpenDART returned no usable filing data")
        rows = data.get("list")
        published_at = request.parameters.get("published_at")
        if not isinstance(rows, list) or not rows:
            return ProviderResult(self.name, request.capability, ProviderStatus.UNAVAILABLE, reason="OpenDART filing rows unavailable")
        observations: list[ProviderObservation] = []
        retrieved = _now()
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            metric = str(row.get("account_nm") or row.get("account_id") or f"account_{index}")
            value = row.get("thstrm_amount")
            observations.append(ProviderObservation(
                evidence_type="financial",
                source_name="OpenDART",
                source_url=public_url,
                source_tier=1,
                provider_id=self.name,
                value=value,
                unit="KRW",
                currency="KRW",
                instrument_id=request.instrument_id,
                metric=metric,
                retrieved_at=retrieved,
                published_at=None if published_at is None else str(published_at),
                metadata={"corp_code": corp_code, "business_year": year, "report_code": report_code, "fs_div": fs_div, "account_id": row.get("account_id"), "sj_div": row.get("sj_div"), "period_end": row.get("thstrm_dt")},
            ))
        return ProviderResult(self.name, request.capability, ProviderStatus.AVAILABLE, tuple(observations), metadata={"row_count": len(observations)})


@dataclass(slots=True)
class SecCompanyFactsAdapter:
    transport: Transport = urllib_transport
    timeout: float = 15.0
    user_agent: str = "investment-stack/0.1 local-research"
    name: str = "sec_companyfacts"
    capabilities: frozenset[ProviderCapability] = frozenset({ProviderCapability.FUNDAMENTALS})

    def fetch(self, request: ProviderRequest) -> ProviderResult:
        if request.capability not in self.capabilities:
            return ProviderResult(self.name, request.capability, ProviderStatus.UNAVAILABLE, reason="capability unsupported")
        cik_raw = str(request.parameters.get("cik", "")).strip()
        if not cik_raw.isdigit():
            return ProviderResult(self.name, request.capability, ProviderStatus.UNAVAILABLE, reason="numeric cik is required")
        cik = cik_raw.zfill(10)
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
        try:
            data = fetch_json(url, headers={"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"}, timeout=self.timeout, transport=self.transport)
        except ProviderTransportError as exc:
            return ProviderResult(self.name, request.capability, ProviderStatus.ERROR, reason=str(exc))
        facts = data.get("facts") if isinstance(data, dict) else None
        if not isinstance(facts, dict):
            return ProviderResult(self.name, request.capability, ProviderStatus.UNAVAILABLE, reason="SEC company facts unavailable")
        published_at = request.parameters.get("published_at")
        return ProviderResult(self.name, request.capability, ProviderStatus.AVAILABLE, (
            ProviderObservation(
                evidence_type="financial",
                source_name="SEC EDGAR Company Facts",
                source_url=url,
                source_tier=1,
                provider_id=self.name,
                value=facts,
                instrument_id=request.instrument_id,
                metric=request.metric or "company_facts",
                retrieved_at=_now(),
                published_at=None if published_at is None else str(published_at),
                metadata={"cik": cik},
            ),
        ))

@dataclass(slots=True)
class KrakenTickerAdapter:
    transport: Transport = urllib_transport
    timeout: float = 15.0
    name: str = "kraken_public"
    capabilities: frozenset[ProviderCapability] = frozenset({ProviderCapability.CURRENT_PRICE})

    def fetch(self, request: ProviderRequest) -> ProviderResult:
        if request.capability not in self.capabilities:
            return ProviderResult(self.name, request.capability, ProviderStatus.UNAVAILABLE, reason="capability unsupported")
        pair = str(request.parameters.get("pair", "")).strip()
        if not pair:
            return ProviderResult(self.name, request.capability, ProviderStatus.UNAVAILABLE, reason="venue pair is required")
        # Trades provides an actual venue trade timestamp; Ticker does not.
        url = "https://api.kraken.com/0/public/Trades?" + urlencode({"pair": pair, "count": 1})
        try:
            data = fetch_json(url, timeout=self.timeout, transport=self.transport)
        except ProviderTransportError as exc:
            return ProviderResult(self.name, request.capability, ProviderStatus.ERROR, reason=str(exc))
        if not isinstance(data, dict) or data.get("error"):
            return ProviderResult(self.name, request.capability, ProviderStatus.UNAVAILABLE, reason="Kraken trade quote unavailable")
        result = data.get("result")
        if not isinstance(result, dict) or not result:
            return ProviderResult(self.name, request.capability, ProviderStatus.UNAVAILABLE, reason="Kraken trade quote unavailable")
        venue_pair = next((key for key in result if key != "last"), None)
        trades = result.get(venue_pair) if venue_pair else None
        if not isinstance(trades, list) or not trades:
            return ProviderResult(self.name, request.capability, ProviderStatus.UNAVAILABLE, reason="Kraken trade quote malformed")
        try:
            last = trades[-1]
            price = last[0]
            trade_time = datetime.fromtimestamp(float(last[2]), tz=timezone.utc).isoformat()
        except (IndexError, TypeError, ValueError):
            return ProviderResult(self.name, request.capability, ProviderStatus.UNAVAILABLE, reason="Kraken trade quote malformed")
        return ProviderResult(self.name, request.capability, ProviderStatus.AVAILABLE, (
            ProviderObservation(
                evidence_type="market",
                source_name="Kraken Public Trades",
                source_url=url,
                source_tier=3,
                provider_id=self.name,
                value=price,
                currency=str(request.parameters.get("quote_currency", "USD")),
                instrument_id=request.instrument_id,
                metric=request.metric or "last_trade_price",
                retrieved_at=_now(),
                observed_at=trade_time,
                metadata={"venue": "Kraken", "pair": venue_pair, "timestamp_semantics": "venue_trade_time"},
            ),
        ))
