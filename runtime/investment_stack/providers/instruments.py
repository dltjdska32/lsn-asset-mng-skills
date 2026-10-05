"""Generic, fail-closed instrument resolution from DB identifiers or live metadata.

No personal holdings, issuer names, ticker suffix guesses or price guesses live
in this module. Legacy DBs can supply an explicit external identity registry.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from urllib.parse import quote

from investment_stack.calculations import BusinessType
from investment_stack.deep_research import EquityResearchSpec

MARKETS = {"KRX": ("KOREA", "KRW"), "JPX": ("JAPAN", "JPY"),
           "NASDAQ": ("USA", "USD"), "NYSE": ("USA", "USD")}
ALIASES = {"NYQ": "NYSE", "NASDAQGS": "NASDAQ", "NMS": "NASDAQ", "NGM": "NASDAQ", "NCM": "NASDAQ",
           "TSE": "JPX", "TYO": "JPX", "KOSPI": "KRX", "KOSDAQ": "KRX"}


@dataclass(frozen=True)
class ResolvedInstrument:
    instrument_id: str
    name: str
    ticker: str
    exchange: str
    currency: str
    asset_class: str
    identifiers: dict
    provenance: dict

    @property
    def listing_id(self):
        return f"{self.exchange}:{self.ticker}"

    def equity_spec(self):
        if self.asset_class != "EQUITY":
            raise ValueError("funds and alternatives cannot use an equity research spec")
        business = self.identifiers.get("business_type", "STABLE_CASH_FLOW")
        return EquityResearchSpec(self.instrument_id, self.name, MARKETS[self.exchange][0],
            self.currency, BusinessType(business), ticker=self.ticker,
            market_parameters={"exchange": self.exchange},
            fundamentals_parameters={**({"ticker":self.ticker,"exchange":self.exchange} if self.exchange in {"NASDAQ","NYSE"} else {}),
                **{k: self.identifiers[k] for k in ("cik", "corp_code") if k in self.identifiers}},
            news_query=f"{self.instrument_id} recent material events")


class InstrumentResolver:
    def __init__(self, rows=(), *, registry=None, transport=None):
        self.rows = {str(r["instrument_id"]): dict(r) for r in rows}
        self.transport = transport
        self.registry = dict(registry or {})
        self.resolved = {}
        self.failures = {}

    @classmethod
    def from_database(cls, database_path, *, registry_path=None, transport=None):
        with closing(sqlite3.connect(database_path)) as c:
            c.row_factory = sqlite3.Row
            rows = [dict(r) for r in c.execute("select * from instruments")]
        registry = {}
        if registry_path is None:
            from pathlib import Path
            sibling = Path(database_path).parent / 'instrument-registry.json'
            if sibling.is_file():
                registry_path = sibling
        if registry_path is not None:
            payload = json.loads(registry_path.read_text())
            if payload.get("schema_version") != 1 or not isinstance(payload.get("instruments"), dict):
                raise ValueError("invalid instrument registry")
            registry = payload["instruments"]
        return cls(rows, registry=registry, transport=transport)

    def resolve(self, instrument_id, explicit=None):
        if explicit is None and instrument_id in self.resolved:
            return self.resolved[instrument_id]
        row = self.rows.get(instrument_id, {})
        ids = json.loads(row.get("identifiers_json") or "{}")
        if not isinstance(ids, dict):
            raise ValueError("instrument identifiers must be an object")
        origin = "personal.db identifiers"
        if not ids and instrument_id in self.registry:
            ids = dict(self.registry[instrument_id]); origin = "explicit external registry"
        supplied = dict(explicit or {})
        for key in ("listing_id", "exchange", "ticker", "cik", "corp_code", "business_type"):
            if key in supplied:
                if key in ids and str(ids[key]).upper() != str(supplied[key]).upper():
                    raise ValueError(f"conflicting instrument {key}")
                ids[key] = supplied[key]
        asset = str(row.get("asset_class") or supplied.get("asset_class") or "").upper()
        currency = str(row.get("currency") or supplied.get("currency") or "").upper()
        if row and any(supplied.get(k) and str(supplied[k]).upper() != str(row.get(k) or "").upper()
                       for k in ("currency", "asset_class")):
            raise ValueError("request conflicts with registered instrument")
        name = str(row.get("canonical_name") or supplied.get("display_name") or instrument_id)
        listing = ids.get("listing_id")
        if listing is None and ":" in instrument_id:
            listing = instrument_id
        if listing is not None:
            parts = str(listing).split(":")
            if len(parts) != 2:
                raise ValueError("listing requires EXCHANGE:TICKER")
            exchange, ticker = parts
            if ids.get("exchange") and ALIASES.get(str(ids["exchange"]).upper(), str(ids["exchange"]).upper()) != exchange.upper():
                raise ValueError("listing/exchange conflict")
            if ids.get("ticker") and str(ids["ticker"]).upper() != ticker.upper():
                raise ValueError("listing/ticker conflict")
        else:
            exchange, ticker = ids.get("exchange"), ids.get("ticker")
        provenance = {"identity_source": origin}
        if not exchange or not ticker:
            # A bare explicit ticker may be resolved from provider identity metadata.
            # A company name or internal slug is never silently treated as a ticker.
            token = str(ticker or instrument_id).upper()
            if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", token) or self.transport is None:
                raise ValueError("listing metadata required; ambiguous name/internal identifier")
            exchange, ticker, meta_ccy, meta_asset, provenance = self._live_identity(token)
            if currency and currency != meta_ccy:
                raise ValueError("provider currency conflicts with registered currency")
            if asset and asset != meta_asset:
                raise ValueError("provider asset type conflicts with registered type")
            currency = currency or meta_ccy; asset = asset or meta_asset
        exchange = ALIASES.get(str(exchange).upper(), str(exchange).upper())
        ticker = str(ticker).upper()
        if exchange not in MARKETS:
            raise ValueError(f"unsupported exchange: {exchange}")
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9.-]{0,19}", ticker):
            raise ValueError("invalid ticker")
        if exchange == "KRX" and not re.fullmatch(r"[0-9A-Z]{6}", ticker):
            raise ValueError("KRX code must contain six characters")
        if exchange == "JPX" and not re.fullmatch(r"[0-9A-Z]{4}", ticker):
            raise ValueError("JPX local code required; provider suffix is not a local code")
        if currency != MARKETS[exchange][1]:
            raise ValueError("exchange/currency identity conflict or missing currency")
        if asset not in {"EQUITY", "FUND"}:
            raise ValueError(f"unsupported or missing asset class: {asset}")
        for key, length in (("cik", 10), ("corp_code", 8)):
            if key in ids and (isinstance(ids[key], bool) or not str(ids[key]).isdigit() or
                               len(str(ids[key])) > length or int(ids[key]) <= 0):
                raise ValueError(f"invalid {key} identity")
        if ids.get("business_type") is not None:
            BusinessType(ids["business_type"])
        result = ResolvedInstrument(instrument_id, name, ticker, exchange, currency, asset, ids, provenance)
        self.resolved[instrument_id] = result
        return result

    def _live_identity(self, token):
        errors = []
        for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
            url = f"https://{host}/v8/finance/chart/{quote(token, safe='')}?interval=1d&range=1mo"
            try:
                raw = self.transport(url, {"User-Agent": "Mozilla/5.0"}, 10)
                meta = json.loads(raw)["chart"]["result"][0]["meta"]
                if str(meta.get("symbol", "")).upper() != token:
                    raise ValueError("live symbol identity mismatch")
                exchange = ALIASES.get(meta.get("exchangeName"), meta.get("exchangeName"))
                asset = {"EQUITY": "EQUITY", "ETF": "FUND", "MUTUALFUND": "FUND"}.get(meta.get("instrumentType"))
                if exchange not in {"NASDAQ", "NYSE"} or asset is None:
                    raise ValueError("unqualified ticker is not an identified supported US equity/fund")
                retrieved = self.transport.retrieved_at_for(url) if hasattr(self.transport, "retrieved_at_for") else datetime.now(timezone.utc).isoformat()
                return exchange, token, str(meta.get("currency", "")).upper(), asset, {
                    "identity_source": "provider metadata; quote not yet approved", "source_uri": url,
                    "retrieved_at": retrieved, "content_sha256": hashlib.sha256(raw).hexdigest()}
            except Exception as exc:
                errors.append(type(exc).__name__ + ": " + str(exc))
        raise ValueError("live identity resolution unavailable: " + "; ".join(errors))

    def portfolio(self, held_ids):
        for iid in held_ids:
            try:
                self.resolve(iid)
            except ValueError as exc:
                self.failures[iid] = str(exc)
        return {iid: self.resolved[iid] for iid in held_ids if iid in self.resolved}

    def request_specs(self, request):
        assets = request.payload.get("assets")
        if assets is None:
            ids = request.payload.get("instrument_ids") or ([request.payload["instrument_id"]] if request.payload.get("instrument_id") else [])
            assets = [{"instrument_id": iid} for iid in ids]
        if not isinstance(assets, (list, tuple)):
            raise ValueError("assets must be a list")
        specs = []
        for asset in assets:
            if not isinstance(asset, dict) or not asset.get("instrument_id"):
                raise ValueError("each asset requires an explicit instrument_id")
            specs.append(self.resolve(str(asset["instrument_id"]), asset).equity_spec())
        return tuple(specs)
