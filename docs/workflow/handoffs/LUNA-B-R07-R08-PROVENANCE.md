# B R07–08 verified OHLCV to technical lineage handoff

- Branch: `codex/luna-b-r07-r08-tls`
- Base: root integrated `83dfb2779f5afa2932f0f196adbe80f13ac89534`
- Implementation commit: `d2c5158fc0ace79081141e6e84df90d1d3370bec`
- Scope: B OHLCV parser and technical calculation path, focused fixtures, plus the requested TLS status text correction in `README.md` and `IMPLEMENTATION_STATUS.md`.

## Changes

- Added `OHLCVParseResult.analysis_eligible`, requiring adjustment and calendar attestations, a source URL, an as-of timestamp, nonempty expected sessions matching observed sessions, and no incomplete, discarded, or missing bars. Caller receipts remain attestations; this code does not validate corporate-action records or exchange-calendar provenance.
- Yahoo `adjclose` no longer marks raw OHLC as split-adjusted. Yahoo OHLCV only produces an adjusted `BarSet` when the caller supplies an explicit adjustment verification marker and receipt. Unequal quote-array lengths are rejected per bar.
- Added an explicit-parameter verified technical aggregation path. It returns bar/evidence/session aligned indicators, a bar fingerprint, a validation receipt identifier, and a trend only after the OHLCV gate passes. Trading signal status remains `UNAVAILABLE`; no breakout policy threshold was introduced.
- Updated root integration TLS wording: default scoped TLS and public HTTP 200 probes were confirmed at `83dfb27`; this does not validate freshness or OHLCV adjustment/session quality.

## Verification executed

```powershell
$VenvPython = (Resolve-Path .\.venv-install\Scripts\python.exe).Path
$env:PYTHONPATH='runtime'
$env:PYTHONDONTWRITEBYTECODE='1'
& $VenvPython -B -m unittest tests.unit.test_r06_r07_market_quotes_ohlcv tests.unit.test_r08_technical tests.providers.test_b_ohlcv
git diff --check
```

Result: **37 tests passed**. The new end-to-end fixture hand-checks SMA(2) = 107 for closes 106 and 108 and checks source URL, bar ID, evidence ID, and fingerprint lineage. Raw/unverified data, incomplete data, a missing expected session, and a future bar all return `UNAVAILABLE` with no points and no trend.

## Not executed / remaining

- No live provider requests were made for this B follow-up.
- Full root regression and integration verification were not run here.
- Receipts are caller-supplied markers, not independently verified evidence. The caller must supply a trustworthy calendar and adjustment receipt.
- Existing pure indicator functions still accept `Sequence[Bar]` for fixture/backward compatibility. Production consumers must use `calculate_verified_technical_analysis` with an `OHLCVParseResult`.
