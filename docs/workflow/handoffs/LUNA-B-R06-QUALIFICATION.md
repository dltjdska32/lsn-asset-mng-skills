# B R06 quote qualification handoff

- Branch: `codex/luna-b-r06-qualification`
- Base: root integration `a7cac1d` (`a7cac1d` is the requested integrated baseline)
- Owner scope: `providers/market_quotes.py`, `web_research/quote_sources.py`, and B quote fixtures.
- A-owned HTTP/R05 and C reporting files were not edited.

## Implemented

- Added a shared post-parse market identity check for instrument, exchange, and currency. Naver now rejects missing/unrecognized exchange metadata and KRX/KOSDAQ cross-list mismatches. Yahoo no longer invents USD/NASDAQ defaults and rejects missing or request-mismatched exchange/currency fields.
- Yahoo delay is taken only from the source's `exchangeDataDelayedBy` field. Missing delay is represented as unknown and the quote is conservatively marked `DELAYED`; provider-reported zero remains `REGULAR`. Coinbase/Kraken do not claim `delay_minutes=0` without source evidence.
- Both `MarketQuoteProvider.fetch_current` and `execute_quote_fallback_sequence` reject future observations, record identity/freshness failures, and continue to later candidates. Evaluator exceptions are recorded and do not abort the candidate sequence.
- Without an injected freshness evaluator, parsed candidates are never returned as selected or `AVAILABLE`. The provider returns `UNAVAILABLE` with reason `FRESHNESS_EVALUATOR_NOT_CONFIGURED`; the standalone fallback helper returns `FRESHNESS_EVALUATOR_REQUIRED`. No quote is exposed in the calculation contract for those paths.
- Analysis cutoffs must be timezone-aware. The SEC fundamentals candidate remains excluded from current-price collection. HTTP 403 responses remain failed attempts and cannot be parsed/promoted as quotes.

## Verification

Synthetic focused tests:

```powershell
$VenvPython = (Resolve-Path .\.venv-install\Scripts\python.exe).Path
$env:PYTHONPATH='runtime'
$env:PYTHONDONTWRITEBYTECODE='1'
& $VenvPython -B -m unittest tests.unit.test_r06_r07_market_quotes_ohlcv tests.providers.test_b_ohlcv
git diff --check
```

Result: **31 tests passed**. Fixtures cover stale primary → eligible alternate, no evaluator → no selected quote, evaluator exceptions, all candidates returning 403, future timestamps rejected even if the evaluator says eligible, Yahoo exchange mismatch, unknown versus reported delay, BTC/EUR rejection, and the exclusion of SEC fundamentals from quote candidates.

Public live checks used the default Windows `urllib_transport`/scoped TLS path, without credentials:

- Yahoo Finance AAPL chart: HTTP 200 and parsed as `NASDAQ:AAPL`, NMS/NASDAQ, USD, observed timestamp `2026-09-25T16:00:01-04:00`; reported delay was absent/unknown.
- Naver Samsung basic quote: HTTP 200 and parsed as `KRX:005930`, KRX, KRW, observed timestamp `2026-09-23T15:30:00+09:00`, reported delay 0.

These are live access and schema observations, not freshness-evaluator approval. Both observations were older than the 2026-09-27 retrieval date and must not be represented as current prices. The R06 runtime returns no calculation-approved quote unless the configured evaluator accepts it.

## Remaining limitations

- No live validation was performed for JPX/Japanese listings, gold/silver product types, or KRX official/Investing fallback adapters. Those registry entries remain candidates or fixture-only and do not establish R06 completion.
- The freshness evaluator and its production thresholds are supplied outside these B-owned modules; no evaluator was invented here.
- The full root regression is being run by the total owner and was not duplicated in this branch.
