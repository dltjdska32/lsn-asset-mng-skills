# CLOSE-B handoff

## Scope

Requirements R10/R11 and decision D12; implementation limited to the personal-state policy adapter, its focused tests, and this handoff.

## Changes

- Added `runtime/investment_stack/decisions/policy_b_personal.py` with frozen typed host snapshot inputs and a read-only binder to the immutable `pinned_personal_state` record in the current run database.
- The binder checks the instance ID, state version, snapshot ID, and data-as-of value together. A mismatch or missing pin prevents binding.
- The existing personal ledger only stores `BOOK_ONLY` snapshots and has no trusted market valuation/FX, full unpriced-asset/liability coverage, emergency/planned-reserve evidence, pending-order reservation, fee schedule, or lot-rule evidence contract. The adapter therefore returns no D12 sizing values and lists each missing proof; caller-provided strings and flags cannot mark those prerequisites ready.
- Adapter is read-only and reports `orders_posted=False`.
- Added synthetic-only tests; no actual personal database is opened.

## Verification

`$env:PYTHONPATH='runtime'; python -m unittest tests.decisions.test_policy_b_personal -v` — 3 tests passed. Tests use a mocked run.db context and synthetic payloads only.

## Limits

This adapter binds identity and version only. It cannot validate that a host-supplied typed snapshot payload is an authentic decode of the referenced personal database row because no read-only snapshot-fetch API or content hash contract exists in the current ledger. Until that contract and the valuation/reserve/order/cost evidence are implemented, actionable holding value, portfolio denominator, and investable cash stay unavailable.
