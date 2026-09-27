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


@dataclass(frozen=True)
class SecTagDef:
    canonical: str
    kind: str  # "money", "per_share", "shares"
    is_duration: bool

_SEC_SUPPORTED_TAGS = {
    "Revenues": SecTagDef("revenue", "money", True),
    "SalesRevenueNet": SecTagDef("revenue", "money", True),
    "OperatingIncomeLoss": SecTagDef("operating_income", "money", True),
    "NetIncomeLoss": SecTagDef("net_income", "money", True),
    "NetCashProvidedByUsedInOperatingActivities": SecTagDef("cash_from_operations", "money", True),
    "PaymentsToAcquirePropertyPlantAndEquipment": SecTagDef("capex", "money", True),
    "CashAndCashEquivalentsAtCarryingValue": SecTagDef("cash", "money", False),
    "StockholdersEquity": SecTagDef("equity", "money", False),
    "AssetsCurrent": SecTagDef("current_assets", "money", False),
    "LiabilitiesCurrent": SecTagDef("current_liabilities", "money", False),
    "EarningsPerShareBasic": SecTagDef("eps", "per_share", True),
    "CommonStockSharesOutstanding": SecTagDef("shares_outstanding", "shares", False),
}

_DEI_SUPPORTED_TAGS = {
    "EntityCommonStockSharesOutstanding": SecTagDef("shares_outstanding", "shares", False),
}

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
            analysis_as_of = datetime.fromisoformat(request.analysis_as_of.replace("Z", "+00:00"))
            if analysis_as_of.tzinfo is None:
                analysis_as_of = analysis_as_of.replace(tzinfo=timezone.utc)
        except ValueError:
            return ProviderResult(self.name, request.capability, ProviderStatus.ERROR, reason="invalid analysis_as_of format")
            
        try:
            data = fetch_json(url, headers={"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"}, timeout=self.timeout, transport=self.transport)
        except ProviderTransportError as exc:
            return ProviderResult(self.name, request.capability, ProviderStatus.ERROR, reason=str(exc))
            
        facts = data.get("facts") if isinstance(data, dict) else None
        if not isinstance(facts, dict) or not facts:
            return ProviderResult(self.name, request.capability, ProviderStatus.UNAVAILABLE, reason="SEC company facts unavailable")
            
        us_gaap = facts.get("us-gaap", {})
        dei = facts.get("dei", {})
        
        observations: list[ProviderObservation] = []
        eligible_count = 0
        
        for namespace, ns_facts in [("us-gaap", us_gaap), ("dei", dei)]:
            if not isinstance(ns_facts, dict):
                continue
            for tag in ns_facts.keys():
                tag_def = None
                if namespace == "us-gaap":
                    tag_def = _SEC_SUPPORTED_TAGS.get(tag)
                elif namespace == "dei":
                    tag_def = _DEI_SUPPORTED_TAGS.get(tag)
                
                if not tag_def:
                    continue
                    
                tag_info = ns_facts[tag]
                if not isinstance(tag_info, dict):
                    continue
                units = tag_info.get("units", {})
                if not isinstance(units, dict):
                    continue
                    
                for unit_key, fact_list in units.items():
                    if not isinstance(unit_key, str) or not isinstance(fact_list, list):
                        continue
                        
                    # Validate unit strictly matches tag kind
                    if tag_def.kind == "shares" and unit_key != "shares":
                        continue
                    if tag_def.kind == "per_share" and unit_key != "USD/shares":
                        continue
                    if tag_def.kind == "money" and unit_key != "USD":
                        continue
                        
                    for fact in fact_list:
                        if not isinstance(fact, dict):
                            continue
                            
                        val = fact.get("val")
                        if isinstance(val, (list, dict)) or val is None or val is True or val is False:
                            continue
                        if str(val) in {"NaN", "Infinity", "-Infinity"}:
                            continue
                        try:
                            from decimal import Decimal, InvalidOperation
                            dec_val = Decimal(str(val))
                        except (ValueError, TypeError, InvalidOperation):
                            continue
                        if not dec_val.is_finite():
                            continue

                        start = fact.get("start")
                        end = fact.get("end")
                        form = fact.get("form")
                        filed = fact.get("filed")
                        
                        approved = True
                        reason = None
                        
                        if not end or not form or not filed:
                            approved = False
                            reason = "Missing required fields (end, form, or filed)"
                        elif form not in {"10-K", "10-K/A", "10-Q", "10-Q/A"}:
                            approved = False
                            reason = f"Unsupported form: {form}"
                        else:
                            try:
                                end_dt = datetime.strptime(str(end), "%Y-%m-%d")
                                if tag_def.is_duration:
                                    if not start:
                                        approved = False
                                        reason = "Duration metric missing start date"
                                    else:
                                        start_dt = datetime.strptime(str(start), "%Y-%m-%d")
                                        if start_dt > end_dt:
                                            approved = False
                                            reason = "start date after end date"
                            except ValueError:
                                approved = False
                                reason = "Invalid start/end date format"
                        
                        filed_dt_iso = None
                        if approved:
                            try:
                                filed_dt = datetime.strptime(str(filed), "%Y-%m-%d").replace(
                                    hour=23, minute=59, second=59, tzinfo=timezone.utc
                                )
                                if filed_dt > analysis_as_of:
                                    continue
                                filed_dt_iso = filed_dt.isoformat()
                            except ValueError:
                                approved = False
                                reason = "Invalid filed date format"
                        
                        currency = unit_key.split("/")[0] if tag_def.kind in ("money", "per_share") else None
                        
                        obs = ProviderObservation(
                            evidence_type="financial",
                            source_name="SEC EDGAR Company Facts",
                            source_url=url,
                            source_tier=1,
                            provider_id=self.name,
                            value=dec_val,
                            unit=unit_key,
                            currency=currency,
                            instrument_id=request.instrument_id,
                            metric=tag_def.canonical,
                            retrieved_at=_now(),
                            published_at=filed_dt_iso,
                            relevance_reason=reason,
                            metadata={
                                "cik": cik,
                                "namespace": namespace,
                                "tag": tag,
                                "start": start,
                                "end": end,
                                "fy": fact.get("fy"),
                                "fp": fact.get("fp"),
                                "form": form,
                                "accn": fact.get("accn"),
                                "filed": filed,
                                "frame": fact.get("frame"),
                                "period_end": end,
                                "calculation_input_approved": approved,
                                "canonical_metric": tag_def.canonical,
                            },
                        )
                        observations.append(obs)
                        if approved:
                            eligible_count += 1

        # Sort observations to ensure deterministic order regardless of input dict ordering
        # Using str() or "" to prevent TypeError when comparing None and str
        # Using o.value directly preserves Decimal precision
        observations.sort(key=lambda o: (
            str(o.metadata.get("namespace") or ""),
            str(o.metadata.get("tag") or ""),
            str(o.unit or ""),
            str(o.metadata.get("period_end") or ""),
            str(o.metadata.get("start") or ""),
            str(o.metadata.get("accn") or ""),
            str(o.metadata.get("filed") or ""),
            o.value if o.value is not None else Decimal(0)
        ))

        status = ProviderStatus.AVAILABLE
        result_reason = None
        if eligible_count == 0:
            if len(observations) > 0:
                status = ProviderStatus.PARTIAL
                result_reason = "SEC facts collected but none were eligible"
            else:
                status = ProviderStatus.UNAVAILABLE
                result_reason = "No eligible SEC facts found"

        return ProviderResult(
            self.name, 
            request.capability, 
            status, 
            tuple(observations), 
            reason=result_reason,
            metadata={"total_parsed_facts": len(observations), "eligible_facts": eligible_count, "cik": cik}
        )

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
