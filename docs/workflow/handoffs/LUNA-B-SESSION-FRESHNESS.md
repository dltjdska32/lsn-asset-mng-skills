# Luna B — R06 session-aware last-close qualification

## Assignment and base

- Branch: `codex/luna-b-session-freshness`
- Base: `f0555469ce17430f68c3c4d7bb988e42177a55f6`
- Requirements: R06, with a focused schedule-aware `LAST_VALID_CLOSE` qualification correction.
- Scope: freshness calendar primitives/engine and market quote provider integration. No A-owned or C-owned files changed.

## Changes

- Added immutable pinned official schedule snapshots in `runtime/investment_stack/freshness/calendar.py` for NASDAQ and KRX, limited to Sep 2026 evidence windows. Dates beyond each snapshot fail closed; no weekday or holiday extrapolation is performed.
- NASDAQ snapshot covers Sep 24, 25, and 28, 2026, with a 1-second close timestamp tolerance to accept the verified Yahoo `regularMarketTime` at 16:00:01 ET. KRX snapshot covers Sep 22, 23, and 28, with zero tolerance at 15:30 KST. KRX Sep 24–27 are omitted as closed dates based on official KRX/MOIS/TRN notices.
- A schedule must be structurally identical to the immutable pinned registry entry. Merely supplying an official hostname does not make an incomplete or modified schedule trusted.
- Added `MarketQuoteProviderAdapter.fetch(ProviderRequest) -> ProviderResult` bridge for `CURRENT_PRICE`. It accepts explicit calendar mapping; without a calendar it cannot certify `LAST_VALID_CLOSE`. Its evaluator admits `FRESH` and calendar-verified `LAST_VALID_CLOSE`, and rejects `DELAYED` absent a separate approved policy.
- Naver `localTradedAt` is retained as evidence but not treated as the session close. For last-close responses the close time is derived from `stockExchangeType.endTime`; `closePriceSendTime` supplies the separate public-availability time. An as-of cutoff before that time fails closed.
- Yahoo `regularMarketTime` is recorded as the timestamp and public-availability evidence; absent delay metadata remains unknown and is not inferred from quote age.
- Freshness assessments distinguish a pre-open prior close from a weekend/holiday close.

## Verified source evidence

- Yahoo AAPL response evidence supplied and rechecked by the integrating task: `NMS/USD`, price `341.07`, `regularMarketTime=1790366401` (Sep 25, 2026 16:00:01 ET). Yahoo did not provide a delay field in this response.
- Naver Samsung response evidence supplied by the integrating task: `005930 KS/KRW`, `closePrice=286,500`, `localTradedAt=2026-09-23T20:20:21+09:00`, `endTime=1530`, `closePriceSendTime=1630`, `delay=0`. Thus the market-close timestamp is 15:30, while source-reported availability is 16:30.
- Calendar references: [Nasdaq Trader calendar](https://nasdaqtrader.com/Trader.aspx?id=Calendar), [Nasdaq Sep 2026 notice](https://www.nasdaqtrader.com/TraderNews.aspx?id=ECA2026-685), [KRX trading hours](https://global.krx.co.kr/contents/GLB/06/0602/0602010201/GLB0602010201T1.jsp), [KRX replay notice](https://trn.krx.co.kr/index.jsp), and [MOIS Chuseok notice](https://www.mois.go.kr/frt/bbs/type010/commonSelectBoardArticle.do?bbsId=BBSMSTR_000000000008&nttId=129490).

## Verification run

- `tests.unit.test_calendar_last_valid_close`
- `tests.unit.test_r06_last_valid_close_provider`
- `tests.unit.test_r06_r07_market_quotes_ohlcv`
- Result: 44 tests passed.
- `git diff --check`: passed.
- Root-wide test suite was not run by this task; the integrating owner is running root regression checks.

## Integration boundary requiring A follow-up

This B change does not make the seven-mode executor approve the close. At base `f055546`, A-owned `providers/execution.py::ProviderFallbackExecutor._is_eligible_for_purpose` accepts only `FreshnessStatus.FRESH` for `CURRENT_PRICE`; it rejects `LAST_VALID_CLOSE`. A-owned `providers/factory.py::build_default_provider_executor()` also does not register Yahoo/Naver market quote adapters (its current default set is OpenDART, SEC, and Kraken). The new B adapter satisfies the `ProviderAdapter` shape and returns selected `CURRENT_PRICE` provider results, but it must be explicitly registered by A and the purpose gate must deliberately admit this dated status with the appropriate freshness lineage. The tests assert this current rejection so this handoff does not overstate end-to-end report integration.

## Not completed

- No rolling or full-year exchange calendar loader; schedules are explicitly bounded to the cited September 2026 windows.
- No live HTTP request is executed by these deterministic unit tests; live Yahoo/Naver response values above are evidence supplied/rechecked by the integrating task.
- No changes to A's executor/factory, seven-mode dispatch, or C's briefing layer.
- No remote push or deployment.
