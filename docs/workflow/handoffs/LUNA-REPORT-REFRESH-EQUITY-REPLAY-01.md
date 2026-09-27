# LUNA REPORT_REFRESH Equity Replay A Handoff

## Scope and ownership

- Base: `979cc5efb5d8bbb54e198ed9cb02ec891444c7de`.
- A-owned implementation: `runtime/investment_stack/execution/analysis_modes.py` and its dedicated integration regression.
- `portfolio_thesis_modes.py` and `execution/__init__.py` were not changed.
- No personal database was opened; tests use a temporary run database and synthetic state pins.

## Implemented validation

`equity_analysis_services()` accepts a request whose run metadata mode is `REPORT_REFRESH` only when all of these hold:

1. `refresh_replay=True`.
2. Request mode is exactly `SINGLE_ASSET_ANALYSIS` or `ASSET_COMPARISON`.
3. Request run ID equals the injected run database ID and replay context run ID.
4. Replay context clock and timezone equal both immutable run metadata and the configured Phase 4/5 clock.
5. A personal state pin exists, and replay context state version and snapshot reference exactly match it.

Normal analysis mode matching remains unchanged. Missing or mismatched replay context fails closed with `UNSUPPORTED`. The dispatcher continues to reject replay for `ASSET_UPDATE` and `REPORT_REFRESH` itself.

## Required C-owned connection before end-to-end REPORT_REFRESH

In `runtime/investment_stack/execution/portfolio_thesis_modes.py`, function `rerun_fixed_mode(replay)` currently obtains the payload from `refresh_payload_resolver(replay)` and immediately constructs a `ModeRequest`. The resolver payload must be augmented with the trusted, already verified context from the `FixedModeReplay`:

```python
payload["refresh_context"] = replay.context
```

This must happen after converting the resolver result to a mutable dict and before constructing `ModeRequest`. Do not let the host resolver supply or override this value; the replay context comes from `refresh_report()` after `verify_pinned_run()` succeeds. Its fields are `run_id`, `analysis_as_of`, `analysis_timezone`, `state_version`, and `pinned_state_ref`.

Expected integration behavior after that C-owned connection lands:

- Resolver returns the typed `research_specs` appropriate to `replay.mode`.
- `SINGLE_ASSET_ANALYSIS` and `ASSET_COMPARISON` execute through the already injected `base_services`, sharing the same run database/Phase 4/5/6 runtime as the report refresh.
- The analysis mode handler accepts the run only if its trusted replay context still matches the immutable run clock and personal state pin.
- Tests should exercise both allowlisted equity modes end-to-end through `REPORT_REFRESH`, and reject absent/altered `refresh_context`, false replay flag, and non-allowlisted modes.
- `execution/__init__.py` exports are not required for this composition: hosts can import both service factories from their module paths and compose `equity_analysis_services(...)` as `base_services` to `portfolio_thesis_services(...)`.

Until the C-owned connection is added, the A validation and its direct regression are complete, but the existing REPORT_REFRESH orchestrator does not yet pass the required replay context, so equity replay from that orchestrator is expected to fail closed.

## Verification

- `tests.integration.test_r14_equity_mode_bundles` is the focused integration target; it includes successful single asset replay with an exact synthetic pin plus mismatch and missing-flag rejection.
- No personal database, external service, or network was used.
