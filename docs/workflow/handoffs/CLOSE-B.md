# CLOSE-B handoff

## Scope

R10/R11 and D12. Files owned for this follow-up: personal ledger/projection read API, the dedicated D12 personal binder, its focused tests, and this handoff.

## Changes

- Added `PersonalLedgerService.get_verified_portfolio_snapshot_projection`. It opens the configured personal database read-only, validates its instance identity, selects the exact pinned `portfolio_snapshots` row, checks `snapshot_id`, `state_version`, and `as_of`, and computes the posted-entry projection at that exact state version within the same SQLite read transaction.
- The returned record includes snapshot metadata but never parses or trusts `data_json` or `BOOK_ONLY`/valuation labels as marked-value proof.
- The D12 binder now joins the run.db pin to the personal DB row and projection. It exposes instrument units, per-account/per-currency cash balances, and liability principal components derived from posted ledger entries. It leaves holding value, portfolio denominator, and investable cash unavailable and keeps sizing disabled.
- Failure to read a pin, find the row, validate the database identity, or match the version/as-of fails closed. No write path is called.
- Added temporary-database tests with synthetic USD deposit/buy/snapshot rows, wrong instance/version/as-of cases, missing-row behavior, and tampered-row rejection. The test uses bogus snapshot JSON values to verify they do not leak into derived fields.

## Verification

`$env:PYTHONPATH='runtime'; python -m unittest tests.decisions.test_policy_b_personal -v` — 4 focused tests pass. `git diff --check` passes. Tests use only temporary synthetic personal databases.

## Remaining input contract for actionable sizing

The current schema needs a future typed, read-only evidence contract providing: (1) a mark for every asset with instrument identity, price, price currency, unit, source/evidence reference, and market as-of; (2) verified FX rates with source, direction, and as-of for each conversion to the selected evaluation currency; (3) complete asset/liability coverage and an explicit unpriced-item count so the denominator can be certified; (4) emergency and planned-spending reserves by account/currency with source and effective time; (5) pending open-order cash and sellable-quantity reservations at the pinned state; and (6) instrument fee schedule and lot/tick rules with effective dates and source. Until these are persisted and validated against the same pin, the binder must keep D12 price value, denominator, cash budget, and quantity proposals unavailable. A reference string or a `BOOK_ONLY` status alone is not evidence for these fields.
