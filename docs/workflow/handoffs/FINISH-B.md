# FINISH-B handoff

Base: `1f38fe90ccfc0462f99b530310aafc7907e2d77f`  
Branch: `codex/finish-b`  
Scope: R08 verified technical result context for later non-posting briefings.

## Changes

- Added `investment_stack.decisions.technical_context.TechnicalBriefingContext` and `build_technical_briefing_context(parse_result, analysis)`.
- The builder accepts only `OHLCVParseResult` plus `TechnicalAnalysisResult`; it checks the parser's strict eligibility gate, cutoff, each bar's close time and public availability, source URL, recomputed input fingerprint and receipt, and one-to-one bar/evidence/session mapping.
- Technical parameters are now retained on the calculation result so the context builder can recompute and reject forged indicator values. Context reports last session, evidence IDs, source/receipt/fingerprint, latest SMA/EMA/RSI/MACD/volume/volatility/ATR and explicit PARTIAL/UNAVAILABLE reasons. Signals remain `UNAVAILABLE`.
- Added focused tests for verified lineage and values, unverified-source rejection, future-bar rejection, fingerprint mismatch, and forged indicator rejection.

## Integration API for A

Call `build_technical_briefing_context(parse_result, technical_result)` from `investment_stack.decisions.technical_context`. Render/use only when `context.status` is `AVAILABLE` or `PARTIAL`; use `context.indicator(name)` for values and preserve `context.reasons`, `last_session_date`, and source provenance. `UNAVAILABLE` has no evidence IDs or values. `signal_status` is always `UNAVAILABLE`; this API cannot propose a trade. This module is independent and does not modify A-owned briefing or execution files.

## Verification

- `PYTHONPATH=runtime python -m unittest tests.decisions.test_b_technical_context tests.calculations.test_b_technical -v`: 9 passed.
- `git diff --check`: passed.
- Broader `tests.unit.test_r08_technical` was attempted; the pre-existing `test_verified_barset_to_indicator_keeps_lineage_and_hand_value` could not initialize `ZoneInfo("Asia/Seoul")` because `tzdata` is absent in this Python environment. Other tests in that module passed. No dependency was installed.

## Limits

- Provider receipt values remain caller attestations per the existing OHLCV parser contract; this implementation binds them to the parse and bars but does not verify exchange calendar or corporate-action records externally.
- Technical parameter policy and any signal thresholds remain unapproved. No live data, personal database, or order path was used.
