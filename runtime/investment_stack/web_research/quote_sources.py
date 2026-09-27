"""Quote source candidate registries, fallback sequencing, and probe definitions.

Implements REQ-2026-09-23-v1 R06 source order and verification tracking.
Maintains market-by-market candidate sequences, records fallback attempts,
and distinguishes verified live fixtures/endpoints from unverified or unsupported paths.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Callable, Mapping, Sequence

from investment_stack.contracts.market import MarketQuote
from investment_stack.providers.market_quotes import (
    HttpTransport,
    EligibilityEvaluator,
    parse_coinbase_ticker,
    parse_investing_quote,
    parse_kraken_ticker,
    parse_kraken_trades,
    parse_naver_basic_quote,
    parse_yahoo_quote,
    quote_matches_requested_market,
)


class VerificationStatus(StrEnum):
    VERIFIED_LIVE_CAPTURED = "VERIFIED_LIVE_CAPTURED"
    VERIFIED_FIXTURE = "VERIFIED_FIXTURE"
    CANDIDATE_UNVERIFIED_LIVE = "CANDIDATE_UNVERIFIED_LIVE"
    UNSUPPORTED_OR_FIXTURE_ONLY = "UNSUPPORTED_OR_FIXTURE_ONLY"


class MarketCategory(StrEnum):
    KR_EQUITY = "KR_EQUITY"
    US_EQUITY = "US_EQUITY"
    JP_EQUITY = "JP_EQUITY"
    CRYPTO_BTC = "CRYPTO_BTC"
    METALS = "METALS"


@dataclass(frozen=True, slots=True)
class QuoteSourceSpec:
    """Specification of a candidate quote or OHLCV data source."""

    source_id: str
    name: str
    market: MarketCategory
    priority: int
    url_template: str
    verification_status: VerificationStatus
    capabilities: tuple[str, ...]
    notes: str = ""


# Canonical source order reflecting supervisor's live HTTP probe verification results
SOURCE_CANDIDATE_ORDER: dict[MarketCategory, tuple[QuoteSourceSpec, ...]] = {
    MarketCategory.KR_EQUITY: (
        QuoteSourceSpec(
            source_id="naver_pay",
            name="Naver Pay Securities Mobile Basic API",
            market=MarketCategory.KR_EQUITY,
            priority=1,
            url_template="https://m.stock.naver.com/api/stock/{code}/basic",
            verification_status=VerificationStatus.VERIFIED_LIVE_CAPTURED,
            capabilities=("CURRENT_PRICE", "OHLCV"),
            notes="Live HTTP 200 verified by supervisor via native TLS/truststore.",
        ),
        QuoteSourceSpec(
            source_id="krx_official",
            name="KRX Information Data System",
            market=MarketCategory.KR_EQUITY,
            priority=2,
            url_template="http://data.krx.co.kr/comm/bldAttPage/getBldDataList.cmd",
            verification_status=VerificationStatus.CANDIDATE_UNVERIFIED_LIVE,
            capabilities=("CURRENT_PRICE", "OHLCV"),
            notes="Requires dynamic session token or open API key; unverified live in current environment.",
        ),
        QuoteSourceSpec(
            source_id="investing_kr",
            name="Investing.com Korea",
            market=MarketCategory.KR_EQUITY,
            priority=3,
            url_template="https://kr.investing.com/equities/{slug}",
            verification_status=VerificationStatus.UNSUPPORTED_OR_FIXTURE_ONLY,
            capabilities=("CURRENT_PRICE",),
            notes="Direct HTTP returned 403 in live probe. Fixture-only.",
        ),
    ),
    MarketCategory.US_EQUITY: (
        QuoteSourceSpec(
            source_id="yahoo_finance",
            name="Yahoo Finance Chart / Quote API",
            market=MarketCategory.US_EQUITY,
            priority=1,
            url_template="https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1mo",
            verification_status=VerificationStatus.VERIFIED_LIVE_CAPTURED,
            capabilities=("CURRENT_PRICE", "OHLCV"),
            notes="Live HTTP 200 verified by supervisor (AAPL, 3,441 bytes, regularMarketPrice/meta/adjclose).",
        ),
        QuoteSourceSpec(
            source_id="sec_edgar",
            name="SEC EDGAR CompanyFacts / Submissions",
            market=MarketCategory.US_EQUITY,
            priority=2,
            url_template="https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json",
            verification_status=VerificationStatus.VERIFIED_LIVE_CAPTURED,
            capabilities=("FUNDAMENTALS",),
            notes="Live HTTP 200 verified by supervisor with User-Agent. Filings only, not real-time tick.",
        ),
        QuoteSourceSpec(
            source_id="investing_us",
            name="Investing.com US Equities",
            market=MarketCategory.US_EQUITY,
            priority=3,
            url_template="https://www.investing.com/equities/{slug}",
            verification_status=VerificationStatus.UNSUPPORTED_OR_FIXTURE_ONLY,
            capabilities=("CURRENT_PRICE",),
            notes="Direct HTTP returned 403 in live probe. Fixture-only.",
        ),
    ),
    MarketCategory.JP_EQUITY: (
        QuoteSourceSpec(
            source_id="jpx_official",
            name="Japan Exchange Group Official Feed",
            market=MarketCategory.JP_EQUITY,
            priority=1,
            url_template="https://www.jpx.co.jp/",
            verification_status=VerificationStatus.CANDIDATE_UNVERIFIED_LIVE,
            capabilities=("CURRENT_PRICE", "OHLCV"),
            notes="Candidate only. Unverified live.",
        ),
        QuoteSourceSpec(
            source_id="yahoo_finance_jp",
            name="Yahoo Finance Japan",
            market=MarketCategory.JP_EQUITY,
            priority=2,
            url_template="https://finance.yahoo.co.jp/quote/{code}.T",
            verification_status=VerificationStatus.CANDIDATE_UNVERIFIED_LIVE,
            capabilities=("CURRENT_PRICE",),
            notes="Candidate only. Unverified live.",
        ),
    ),
    MarketCategory.CRYPTO_BTC: (
        QuoteSourceSpec(
            source_id="coinbase_public",
            name="Coinbase Public Market API (BTC-USD)",
            market=MarketCategory.CRYPTO_BTC,
            priority=1,
            url_template="https://api.exchange.coinbase.com/products/BTC-USD/ticker",
            verification_status=VerificationStatus.VERIFIED_LIVE_CAPTURED,
            capabilities=("CURRENT_PRICE",),
            notes="Live HTTP 200 verified by supervisor (price, bid, ask, time). Venue-specific.",
        ),
        QuoteSourceSpec(
            source_id="kraken_trades",
            name="Kraken Public Recent Trades API (BTC-USD)",
            market=MarketCategory.CRYPTO_BTC,
            priority=2,
            url_template="https://api.kraken.com/0/public/Trades?pair=XBTUSD&count=1",
            verification_status=VerificationStatus.VERIFIED_LIVE_CAPTURED,
            capabilities=("CURRENT_PRICE",),
            notes="Live HTTP 200 verified by supervisor (price, volume, trade timestamp). Venue-specific.",
        ),
        QuoteSourceSpec(
            source_id="kraken_public",
            name="Kraken Public REST API",
            market=MarketCategory.CRYPTO_BTC,
            priority=3,
            url_template="https://api.kraken.com/0/public/Ticker?pair={pair}",
            verification_status=VerificationStatus.CANDIDATE_UNVERIFIED_LIVE,
            capabilities=("CURRENT_PRICE", "OHLCV"),
            notes="Schema verified, live probe pending.",
        ),
    ),
    MarketCategory.METALS: (
        QuoteSourceSpec(
            source_id="lbma_benchmark",
            name="LBMA Precious Metals Benchmark",
            market=MarketCategory.METALS,
            priority=1,
            url_template="https://www.lbma.org.uk/prices-and-data/precious-metal-prices",
            verification_status=VerificationStatus.CANDIDATE_UNVERIFIED_LIVE,
            capabilities=("CURRENT_PRICE",),
            notes="Physical gold/silver benchmark. Unverified live.",
        ),
    ),
}


@dataclass(frozen=True, slots=True)
class FallbackAttemptRecord:
    source_id: str
    priority: int
    url: str
    started_at: datetime
    finished_at: datetime
    success: bool
    status_code: int | None = None
    error_reason: str | None = None


@dataclass(frozen=True, slots=True)
class FallbackSequenceResult:
    instrument_id: str
    market: MarketCategory
    selected_quote: MarketQuote | None
    attempts: tuple[FallbackAttemptRecord, ...]
    status: str  # SUCCESS, CANDIDATES_EXHAUSTED, UNSUPPORTED_MARKET


def resolve_market_category(instrument_id: str) -> MarketCategory | None:
    """Infer MarketCategory from instrument prefix or format."""
    inst = instrument_id.upper().strip()
    if inst.startswith("KRX:") or inst.startswith("KOSDAQ:") or (inst.isdigit() and len(inst) == 6):
        return MarketCategory.KR_EQUITY
    if inst.startswith("NASDAQ:") or inst.startswith("NYSE:") or inst in {"AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"}:
        return MarketCategory.US_EQUITY
    if inst.startswith("TSE:") or inst.startswith("JPX:") or (inst.endswith(".T") and inst[:-2].isdigit()):
        return MarketCategory.JP_EQUITY
    if inst.startswith("CRYPTO:") and inst.split(":", 1)[1].replace(" ", "").split("/", 1)[0] in {"BTC", "XBT"}:
        return MarketCategory.CRYPTO_BTC
    if any(metal in inst for metal in {"GOLD", "SILVER", "XAU", "XAG"}):
        return MarketCategory.METALS
    return None


def execute_quote_fallback_sequence(
    instrument_id: str,
    *,
    transport: HttpTransport,
    analysis_as_of: datetime,
    prefer_extended_hours: bool = False,
    fixtures_by_source: Mapping[str, Any] | None = None,
    clock: Callable[[], datetime] | None = None,
    eligibility_evaluator: EligibilityEvaluator | None = None,
) -> FallbackSequenceResult:
    """Execute prioritized candidate fallback sequence for an instrument.

    Tries candidates in ascending priority order (1, 2, 3...).
    Logs every attempt with timestamps and outcome.
    Stops upon first valid, eligible quote.
    """
    market = resolve_market_category(instrument_id)
    if (
        market == MarketCategory.CRYPTO_BTC
        and instrument_id.upper().strip().split(":")[-1].replace(" ", "")
        not in {"BTC/USD", "XBT/USD", "BTCUSD", "XBTUSD"}
    ):
        return FallbackSequenceResult(instrument_id, market, None, (), "UNSUPPORTED_MARKET")
    if market is None:
        return FallbackSequenceResult(
            instrument_id=instrument_id,
            market=MarketCategory.US_EQUITY,
            selected_quote=None,
            attempts=(),
            status="UNSUPPORTED_MARKET",
        )
    if analysis_as_of.tzinfo is None:
        return FallbackSequenceResult(instrument_id, market, None, (), "INVALID_ANALYSIS_AS_OF")

    candidates = SOURCE_CANDIDATE_ORDER.get(market, ())
    attempts: list[FallbackAttemptRecord] = []
    fixtures = dict(fixtures_by_source or {})

    ticker = instrument_id.split(":")[-1]

    now = clock or (lambda: datetime.now(timezone.utc))
    for spec in candidates:
        if "CURRENT_PRICE" not in spec.capabilities:
            continue
        started = now()
        url = spec.url_template.replace("{code}", ticker)
        url = url.replace("{symbol}", ticker).replace("{pair}", "XBTUSD").replace("{slug}", ticker.lower())

        # Check if fixture injected for this source
        if spec.source_id in fixtures:
            payload = fixtures[spec.source_id]
            finished = now()
            if spec.source_id == "naver_pay":
                parse_res = parse_naver_basic_quote(
                    payload,
                    instrument_id=instrument_id,
                    retrieved_at=now(),
                    prefer_extended_hours=prefer_extended_hours,
                )
            elif spec.source_id == "yahoo_finance":
                parse_res = parse_yahoo_quote(
                    payload,
                    instrument_id=instrument_id,
                    retrieved_at=now(),
                )
            elif spec.source_id == "coinbase_public":
                parse_res = parse_coinbase_ticker(
                    payload,
                    instrument_id=instrument_id,
                    retrieved_at=now(),
                )
            elif spec.source_id in {"investing_us", "investing_kr"}:
                parse_res = parse_investing_quote(
                    payload,
                    instrument_id=instrument_id,
                    retrieved_at=now(),
                    prefer_extended_hours=prefer_extended_hours,
                )
            elif spec.source_id == "kraken_trades":
                parse_res = parse_kraken_trades(
                    payload,
                    instrument_id=instrument_id,
                    retrieved_at=now(),
                )
            elif spec.source_id == "kraken_public":
                parse_res = parse_kraken_ticker(
                    payload,
                    pair="XBTUSD",
                    instrument_id=instrument_id,
                    retrieved_at=now(),
                )
            else:
                parse_res = None

            if parse_res and parse_res.is_usable and parse_res.quote:
                quote = parse_res.quote
                identity_ok, identity_reason = quote_matches_requested_market(quote, instrument_id)
                if not identity_ok:
                    attempts.append(FallbackAttemptRecord(spec.source_id, spec.priority, url, started, finished, False, 200, identity_reason))
                    continue
                if quote.claimed_market_time is not None:
                    q_time = (
                        quote.claimed_market_time
                        if quote.claimed_market_time.tzinfo
                        else quote.claimed_market_time.replace(tzinfo=timezone.utc)
                    )
                    as_of = (
                        analysis_as_of
                        if analysis_as_of.tzinfo
                        else analysis_as_of.replace(tzinfo=timezone.utc)
                    )
                    if q_time > as_of:
                        attempts.append(
                            FallbackAttemptRecord(
                                source_id=spec.source_id,
                                priority=spec.priority,
                                url=url,
                                started_at=started,
                                finished_at=finished,
                                success=False,
                                status_code=200,
                                error_reason=f"FUTURE_PRICE: {q_time} > {as_of}",
                            )
                        )
                        continue

                if eligibility_evaluator is None:
                    attempts.append(FallbackAttemptRecord(spec.source_id, spec.priority, url, started, finished, False, 200, "FRESHNESS_EVALUATOR_NOT_CONFIGURED"))
                    continue
                try:
                    eligible, reason = eligibility_evaluator(quote, analysis_as_of)
                except Exception as exc:
                    attempts.append(FallbackAttemptRecord(spec.source_id, spec.priority, url, started, finished, False, 200, f"ELIGIBILITY_EVALUATOR_ERROR: {type(exc).__name__}"))
                    continue
                if not eligible:
                    attempts.append(FallbackAttemptRecord(spec.source_id, spec.priority, url, started, finished, False, 200, f"INELIGIBLE: {reason}"))
                    continue

                attempts.append(
                    FallbackAttemptRecord(
                        source_id=spec.source_id,
                        priority=spec.priority,
                        url=url,
                        started_at=started,
                        finished_at=finished,
                        success=True,
                        status_code=200,
                    )
                )
                return FallbackSequenceResult(
                    instrument_id=instrument_id,
                    market=market,
                    selected_quote=parse_res.quote,
                    attempts=tuple(attempts),
                    status="SUCCESS",
                )
            else:
                reasons = "; ".join(parse_res.error_reasons) if parse_res else "unsupported fixture parser"
                attempts.append(
                    FallbackAttemptRecord(
                        source_id=spec.source_id,
                        priority=spec.priority,
                        url=url,
                        started_at=started,
                        finished_at=finished,
                        success=False,
                        status_code=200,
                        error_reason=reasons,
                    )
                )
                continue

        # Try live transport
        try:
            status_code, body, _ = transport(url, None, 10.0)
            finished = now()
            if status_code != 200:
                attempts.append(
                    FallbackAttemptRecord(
                        source_id=spec.source_id,
                        priority=spec.priority,
                        url=url,
                        started_at=started,
                        finished_at=finished,
                        success=False,
                        status_code=status_code,
                        error_reason=f"HTTP_{status_code}",
                    )
                )
                continue

            if spec.source_id == "naver_pay":
                parse_res = parse_naver_basic_quote(
                    body,
                    instrument_id=instrument_id,
                    retrieved_at=now(),
                    prefer_extended_hours=prefer_extended_hours,
                )
            elif spec.source_id == "yahoo_finance":
                parse_res = parse_yahoo_quote(
                    body,
                    instrument_id=instrument_id,
                    retrieved_at=now(),
                )
            elif spec.source_id == "coinbase_public":
                parse_res = parse_coinbase_ticker(
                    body,
                    instrument_id=instrument_id,
                    retrieved_at=now(),
                )
            elif spec.source_id in {"investing_us", "investing_kr"}:
                parse_res = parse_investing_quote(
                    body,
                    instrument_id=instrument_id,
                    retrieved_at=now(),
                    prefer_extended_hours=prefer_extended_hours,
                )
            elif spec.source_id == "kraken_public":
                parse_res = parse_kraken_ticker(
                    body,
                    pair="XBTUSD",
                    instrument_id=instrument_id,
                    retrieved_at=now(),
                )
            else:
                parse_res = None

            if parse_res and parse_res.is_usable and parse_res.quote:
                identity_ok, identity_reason = quote_matches_requested_market(parse_res.quote, instrument_id)
                if not identity_ok:
                    attempts.append(FallbackAttemptRecord(spec.source_id, spec.priority, url, started, finished, False, status_code, identity_reason))
                    continue
                quote_time = parse_res.quote.claimed_market_time
                cutoff = analysis_as_of if analysis_as_of.tzinfo else analysis_as_of.replace(tzinfo=timezone.utc)
                if quote_time is not None:
                    quote_time = quote_time if quote_time.tzinfo else quote_time.replace(tzinfo=timezone.utc)
                    if quote_time > cutoff:
                        attempts.append(FallbackAttemptRecord(spec.source_id, spec.priority, url, started, finished, False, status_code, f"FUTURE_PRICE: {quote_time} > {cutoff}"))
                        continue
                if eligibility_evaluator is None:
                    attempts.append(FallbackAttemptRecord(spec.source_id, spec.priority, url, started, finished, False, status_code, "FRESHNESS_EVALUATOR_NOT_CONFIGURED"))
                    continue
                try:
                    eligible, reason = eligibility_evaluator(parse_res.quote, analysis_as_of)
                except Exception as exc:
                    attempts.append(FallbackAttemptRecord(spec.source_id, spec.priority, url, started, finished, False, status_code, f"ELIGIBILITY_EVALUATOR_ERROR: {type(exc).__name__}"))
                    continue
                if not eligible:
                    attempts.append(FallbackAttemptRecord(spec.source_id, spec.priority, url, started, finished, False, status_code, f"INELIGIBLE: {reason}"))
                    continue
                attempts.append(
                    FallbackAttemptRecord(
                        source_id=spec.source_id,
                        priority=spec.priority,
                        url=url,
                        started_at=started,
                        finished_at=finished,
                        success=True,
                        status_code=status_code,
                    )
                )
                return FallbackSequenceResult(
                    instrument_id=instrument_id,
                    market=market,
                    selected_quote=parse_res.quote,
                    attempts=tuple(attempts),
                    status="SUCCESS",
                )
            else:
                reasons = "; ".join(parse_res.error_reasons) if parse_res else "unsupported live parser"
                attempts.append(
                    FallbackAttemptRecord(
                        source_id=spec.source_id,
                        priority=spec.priority,
                        url=url,
                        started_at=started,
                        finished_at=finished,
                        success=False,
                        status_code=status_code,
                        error_reason=reasons,
                    )
                )

        except Exception as exc:
            finished = now()
            attempts.append(
                FallbackAttemptRecord(
                    source_id=spec.source_id,
                    priority=spec.priority,
                    url=url,
                    started_at=started,
                    finished_at=finished,
                    success=False,
                    status_code=None,
                    error_reason=str(exc),
                )
            )

    unqualified = any(a.error_reason == "FRESHNESS_EVALUATOR_NOT_CONFIGURED" for a in attempts)
    return FallbackSequenceResult(
        instrument_id=instrument_id,
        market=market,
        selected_quote=None,
        attempts=tuple(attempts),
        status="FRESHNESS_EVALUATOR_REQUIRED" if unqualified else "CANDIDATES_EXHAUSTED",
    )
