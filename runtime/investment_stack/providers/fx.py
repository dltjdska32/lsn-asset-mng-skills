"""Timestamped public FX quotes and auditable cross-rate sanity checks."""
from dataclasses import replace
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import json
from investment_stack.providers.models import ProviderObservation, ProviderResult, ProviderStatus
from investment_stack.providers.registry import ProviderCapability
from investment_stack.providers.http import urllib_transport

PAIRS = {"USD/KRW": ("KRW=X", "KRW"), "JPY/KRW": ("JPYKRW=X", "KRW"), "USD/JPY": ("JPY=X", "JPY")}

def parse_fx(payload, pair, *, analysis_as_of, retrieved_at, source_url):
    if pair not in PAIRS:
        raise ValueError("unsupported pair")
    data = json.loads(payload, parse_float=Decimal) if isinstance(payload, (str, bytes)) else payload
    meta = data["chart"]["result"][0]["meta"]
    symbol, currency = PAIRS[pair]
    if meta.get("symbol") != symbol or meta.get("currency") != currency or meta.get("instrumentType") != "CURRENCY":
        raise ValueError("FX identity/currency/type mismatch")
    raw = meta["regularMarketPrice"]
    if isinstance(raw, (bool, float)):
        raise ValueError("FX must use exact Decimal/string")
    rate = Decimal(raw)
    if not rate.is_finite() or rate <= 0:
        raise ValueError("FX rate must be finite and positive")
    stamp = meta["regularMarketTime"]
    if isinstance(stamp, bool) or Decimal(str(stamp)) != Decimal(int(stamp)):
        raise ValueError("invalid FX time")
    timestamp = datetime.fromtimestamp(int(stamp), timezone.utc)
    cutoff = datetime.fromisoformat(analysis_as_of.replace("Z", "+00:00"))
    retrieval = datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
    if cutoff.tzinfo is None or retrieval.tzinfo is None:
        raise ValueError("timezone required")
    age = cutoff - timestamp
    if age < timedelta(0) or age > timedelta(minutes=15) or timestamp > retrieval:
        raise ValueError("FX future/stale quote")
    return ProviderObservation("market", "yahoo_finance_fx", source_url, 2, "fx_quotes",
        value=rate, unit=pair, currency=currency, instrument_id=pair, metric="fx_rate",
        retrieved_at=retrieved_at, observed_at=timestamp.isoformat(), published_at=timestamp.isoformat(),
        claimed_market_time=timestamp.isoformat(), official_confirmation_status="PROVIDER_REPORTED",
        metadata={"pair":pair, "from_currency":pair.split("/")[0], "to_currency":currency,
                  "rate_type":"direct", "freshness":"FRESH", "delay_status":"UNKNOWN",
                  "exact_value_decimal":str(rate), "calculation_input_approved":True})

def cross_fx(usd_krw, jpy_krw, direct=None, *, tolerance=Decimal("0.01"), max_skew_seconds=300):
    if usd_krw.instrument_id != "USD/KRW" or jpy_krw.instrument_id != "JPY/KRW":
        raise ValueError("cross input pair mismatch")
    times = [datetime.fromisoformat(o.observed_at) for o in (usd_krw,jpy_krw)]
    if abs((times[0]-times[1]).total_seconds()) > max_skew_seconds:
        raise ValueError("cross input timestamps not comparable")
    rate = Decimal(str(usd_krw.value))/Decimal(str(jpy_krw.value))
    deviation = None
    if direct is not None:
        if direct.instrument_id != "USD/JPY": raise ValueError("sanity input pair mismatch")
        third = datetime.fromisoformat(direct.observed_at)
        if max(abs((third-t).total_seconds()) for t in times) > max_skew_seconds:
            raise ValueError("direct/cross timestamps not comparable")
        deviation = abs(rate/Decimal(str(direct.value))-1)
        if deviation > tolerance: raise ValueError("FX direct/cross sanity check failed")
    time = min(times).isoformat()
    return replace(usd_krw, source_name="calculated_fx_cross", provider_id="fx_cross", source_url=None, instrument_id="USD/JPY", value=rate, unit="USD/JPY",currency="JPY",
        observed_at=time, published_at=time, claimed_market_time=time,
        metadata={**usd_krw.metadata,"pair":"USD/JPY","from_currency":"USD","to_currency":"JPY",
            "rate_type":"cross","formula":"USD/KRW / JPY/KRW", "exact_value_decimal":str(rate),
            "input_pairs":["USD/KRW","JPY/KRW"], "input_timestamps":[t.isoformat() for t in times],
            "sanity_relative_difference":None if deviation is None else str(deviation),
            "sanity_tolerance":str(tolerance)})

class FXProvider:
    name = "fx_quotes"
    capabilities = frozenset({ProviderCapability.FX})
    def __init__(self, transport=urllib_transport, clock=None):
        self.transport=transport; self.clock=clock or (lambda:datetime.now(timezone.utc))
    def fetch(self, request):
        pair=request.instrument_id
        if pair not in PAIRS:
            return ProviderResult(self.name,request.capability,ProviderStatus.UNAVAILABLE,reason="unsupported FX pair")
        attempts=[]
        for host in ("query1.finance.yahoo.com","query2.finance.yahoo.com"):
            url=f"https://{host}/v8/finance/chart/{PAIRS[pair][0]}?interval=1d&range=5d"
            try:
                raw=self.transport(url,{"User-Agent":"Mozilla/5.0"},10)
                obs=parse_fx(raw,pair,analysis_as_of=request.analysis_as_of,retrieved_at=self.transport.retrieved_at_for(url) if hasattr(self.transport,"retrieved_at_for") else self.clock().isoformat(),source_url=url)
                return ProviderResult(self.name,request.capability,ProviderStatus.AVAILABLE,(obs,),metadata={"attempts":attempts})
            except Exception as exc:
                attempts.append({"source":host,"reason":str(exc) if isinstance(exc,ValueError) else type(exc).__name__})
        return ProviderResult(self.name,request.capability,ProviderStatus.UNAVAILABLE,reason="FX candidates exhausted",metadata={"attempts":attempts})
