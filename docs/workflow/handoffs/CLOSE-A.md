# CLOSE-A handoff

- Scope: R01/R09/R11/D12 market-input adapter, based on design baseline `abceb4ca7218f166d92b65e677655d1f8f84d807`.
- Owned files: `runtime/investment_stack/decisions/policy_b_market.py`, `tests/decisions/test_policy_b_market.py`, this handoff.
- Implementation: the adapter opens run.db through the read-only SQLite helper and derives quote Money only from one selected same-run market evidence row, matching market observation, run-pinned as-of, and one matching persisted freshness assessment. It checks identity, currency, unit, positive finite value equality, freshness state, and timestamps. `LAST_VALID_CLOSE` additionally requires persisted calendar/session fields and matching session date.
- Fail-closed cases return no quote with explicit reasons. Base and optimistic fair values always remain unavailable: existing Phase 5 DCF scenario IDs/results do not prove complete assumption-value provenance. Caller booleans/IDs are never accepted as valuation proof.
- Synthetic tests cover a valid quote, stale quote, future publication, mismatched persisted value, valid calendar-backed last close, unproven last close, and DCF-only fair-value rejection.
- Validation: `$env:PYTHONPATH='runtime'; python -m unittest tests.decisions.test_policy_b_market -v` passed (7 tests); `git diff --check` passed.
- Limitations: adapter currently accepts FRESH, DELAYED, and proven LAST_VALID_CLOSE statuses; it does not itself reconstruct or independently validate the exchange calendar's source, only checks persisted assessment bindings. It does not bind personal portfolio state, FX, reserves, costs, risk budget, or units and therefore cannot alone authorize a non-WAIT D12 result.
