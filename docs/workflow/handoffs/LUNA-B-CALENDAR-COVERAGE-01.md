# Luna B — Official calendar coverage investigation

## Assignment and baseline

- Branch: `codex/luna-b-calendar-coverage-01`
- Base: root integrated `27d95e4` (`Add non-posting thesis review and report refresh services`)
- Scope: investigate safe expansion of `freshness/calendar.py` and its dedicated tests. A-owned files and the adapter API were not changed.
- Outcome: no calendar code expansion. Available official material did not establish a complete, current list of exchange sessions over a broader continuous coverage window without deriving sessions from weekdays or assuming there were no temporary exchange closures.

## Current trusted coverage

`get_pinned_calendar(exchange)` remains API-compatible and returns the existing immutable snapshots:

- NASDAQ: Sep 24–28, 2026; explicit sessions Sep 24, 25, and 28.
- KRX: Sep 22–28, 2026; explicit sessions Sep 22, 23, and 28.

Dates outside these windows remain unavailable for schedule-based last-close qualification. These snapshots and their regression tests were already present at the assigned base; this task did not edit them.

## Source review and limits

### Nasdaq

- The official [Nasdaq Trader 2026 holiday schedule](https://nasdaqtrader.com/Trader.aspx?id=Calendar) lists full closures Jan 1, Jan 19, Feb 16, Apr 3, May 25, Jun 19, Jul 3, Sep 7, Nov 26, and Dec 25; it lists early closes Nov 27 and Dec 24 at 1:00 p.m. ET. It says Nasdaq will issue Trader Alerts for full early-close details and operating times.
- The official [2026 Trading Calendar PDF](https://www.nasdaq.com/trading-calendar) is a month-grid with a legend for full closures and 1 p.m. closes. The text extraction exposes the dates but not the per-date graphical markers as an explicit session roster. The holiday table plus ordinary weekday convention is not an explicit list of every open session, and Nasdaq itself points to Trader Alerts for full operating details. No generated weekday list was added.
- The official [2026 regular-day trading hours specification](https://www.nasdaqtrader.com/content/technicalsupport/specifications/TradingProducts/fixactspec.pdf) says market hours are 9:30 a.m.–4:00 p.m. ET. The official [Aug 17, 2026 trading-hours alert](https://www.nasdaqtrader.com/TraderNews.aspx?id=ETA2026-46) introduces a 9 p.m.–4 a.m. ET session effective Dec 6, 2026. The existing regular session remains in place, but a future all-session calendar must version this regime change and must distinguish regular-session closes from overnight trade dates.
- The holiday calendar alone does not verify that no market-wide temporary close, emergency halt, or later alert affects every date in a broad current/future interval. It supports the enumerated holiday and early-close dates, not an unattended claim of continuous complete session coverage.

### KRX

- The official [KRX KOSPI holiday rules](https://global.krx.co.kr/contents/GLB/06/0602/0602010201/GLB0602010201T1.jsp) state weekday trading, regular hours 09:00–15:30 KST, and closures for public holidays, Labor Day, Saturdays, Dec 31 (or the closest prior business day when applicable), plus other dates KRX deems necessary for market conditions. The final discretionary clause prevents deriving a complete actual calendar from weekday and public-holiday rules alone.
- KRX’s official [trading hours and exchange holidays](https://global.krx.co.kr/contents/GLB/06/0602/0602020204/GLB0602020204T1.jsp) repeats the discretionary-closure allowance.
- The official 2026 [KIND long-holiday notice](https://kind.krx.co.kr/external/dst/notice/11637/%5B%ED%95%9C%EA%B5%AD%EA%B1%B0%EB%9E%98%EC%86%8C%5D%202026%EB%85%84%20%EC%98%AC%EB%B9%BC%EB%AF%B8%EA%B3%B5%EC%8B%9C%20%EC%95%88%EB%82%B4.pdf) identifies specific last trading dates before Lunar New Year (Feb 13), Labor Day (Apr 30), Buddha’s Birthday (May 22), Liberation Day (Aug 14), Chuseok (Sep 23), National Foundation Day (Oct 2), Hangul Day (Oct 8), Christmas (Dec 24), and year-end (Dec 30). This is useful for those exact holiday boundaries, but it is not a complete list of every intervening trading session.
- KRX [TRN replay notices](https://trn.krx.co.kr/index.jsp) concern the derivatives mock/replay system; they are not a KRX cash-equity trading calendar and are not used to infer additional equity sessions. The Sep 24–27 Chuseok notice continues to support the existing bounded snapshot only.
- No official 2026 KRX cash-equity full-year session roster or feed with completeness semantics was found in this investigation. Because the rules explicitly reserve discretionary closures, a year calendar made by subtracting statutory holidays from weekdays would still be an unverified interpolation.

## Decision and future acceptance criteria

Do not expand either pinned snapshot from these sources alone. Keep unsupported dates fail-closed. A future safe expansion needs a dated official session roster (including open, close, early-close and explicit closed dates), its publication/version and coverage, and a way to establish that temporary exchange-wide closures through the requested cutoff were checked. The calendar should preserve separate session regimes where rules change, including Nasdaq’s Dec 6, 2026 overnight-session start, without silently reassigning regular close timestamps.

## Verification

- Read-only official-source investigation completed; no runtime/test code changed.
- No tests run because this handoff-only result adds no executable changes.
- No remote push or deployment.
