# LUNA-C-R14-R17-PORTFOLIO-THESIS-01 Handoff

## Assignment and source

- Requirements: REQ-2026-09-23-v1, R14 and R17; implementation design: DESIGN-2026-09-23-v0.1, §7 and §6.
- Worktree: `C:/Users/lsn/.codex/worktrees/luna-r14-r17-portfolio-thesis/lsn-asset-mng-skills`.
- Branch: `codex/luna-r14-r17-portfolio-thesis`.
- Base root/source SHA: `c5ed40c8af73fe8874f01a0725d070128d340851`.
- Owned files: new `runtime/investment_stack/execution/portfolio_thesis_modes.py`, new `tests/integration/test_r14_portfolio_thesis_mode_bundles.py`, this handoff only.
- No personal database, credentials, external provider, or transaction/order writer was used.

## Implementation

- Added `portfolio_thesis_services(...)`, a fixed-step `RuntimeServices` bundle for `PERSONAL_PORTFOLIO_ANALYSIS`, `PORTFOLIO_SCENARIO`, `THESIS_REVIEW`, and `REPORT_REFRESH`. It can delegate other modes to an existing same-run-db bundle via `base_services`; no planner, dispatcher, or `analysis_modes.py` edits were made.
- Portfolio analysis requires a typed `PortfolioAnalysisRequest` that matches run.db's immutable clock and pinned state. Materiality selection and selected-asset Phase 4/5 work are injected host callbacks; missing callbacks/data remain `PARTIAL` and do not synthesize policy or observations.
- Portfolio allocation/risk calculations persist in run.db with used point-in-time FX/risk evidence references, evaluation currency, policy, approval, validation, and period-policy provenance. Missing run-local evidence lowers the result to partial.
- Scenario handling calls `simulate_portfolio_scenario` behind the injected registry verifier, persists its explicit assumptions/calculation, and retains `posting_enabled=false`. The dispatcher independently rejects all mutation receipts outside `ASSET_UPDATE`.
- Thesis handling accepts only user-authored typed claims and typed current evidence. Evidence is cutoff-filtered by the existing review service, persisted in run.db, and the assessment calculation records current evidence refs and user claim IDs. Missing/contradictory data remains WAIT/PARTIAL.
- Refresh resolves prior report references from run.db manifests, verifies a later clock and matching new pinned state, and replays only the original fixed non-posting mode. The bundle can replay its personal portfolio and scenario handlers. A host can inject additional fixed runners through `ReportRefreshServices`; refresh remains non-recursive and cannot replay `ASSET_UPDATE`.
- Phase 6 report sections and report manifest references are persisted into run.db for each of the four modes. The dispatcher result returns those report refs.

## Verification

Interpreter: `C:/Users/lsn/lsn-asset-mng-skills/.venv/Scripts/python.exe`; `PYTHONPATH=runtime`.

```powershell
$env:PYTHONPATH='runtime'
C:/Users/lsn/lsn-asset-mng-skills/.venv/Scripts/python.exe -m unittest tests.integration.test_r14_portfolio_thesis_mode_bundles tests.unit.test_r14_portfolio_modes tests.unit.test_r14_thesis_refresh tests.unit.test_execution_dispatcher tests.unit.test_phase6_report_review tests.integration.test_phase6_report_runtime
```

Result: **42 tests passed**. The new synthetic integration test executes all four fixed modes through `execute_mode()`, checks Phase 6 report references and run.db calculations/evidence, verifies FX and risk provenance, confirms non-posting scenario state, and confirms refresh's new run clock/state pin. It also confirms no `personal.db` was created.

`git diff --check`: passed.

Not run: full repository suite, live/provider access, real personal state or risk-policy registry, independent review, and final verification.

## Required integration boundaries for A/root

1. Import `portfolio_thesis_services` directly and compose it with the existing `equity_analysis_services` using the same `RunDatabaseManager` via `base_services`; the new module is intentionally not exported through `execution/__init__.py` because that file is outside C ownership.
2. The bundle's default refresh replay covers personal portfolio and portfolio scenario. Single-asset/comparison refresh requires an injected fixed runner and input resolver, no-poster/refresh flags, and a fresh verified run context.
3. Current `analysis_modes.py` validates `run_metadata.request_mode == request.mode.value`; a refresh replay in a run whose original mode is `REPORT_REFRESH` therefore needs an A-owned boundary update to permit only `refresh_replay=True` under the fixed allowlist, while retaining the same run ID, immutable new clock, pinned state, and non-posting dispatcher checks. This branch does not edit that A-owned file.
4. Before calling `execute_mode` for `REPORT_REFRESH`, the host must create/open the new run.db and persist its later clock and pinned state. The bundle verifies that pin; it does not read personal.db or create a personal-state snapshot.
5. For delegated analysis reports to be refreshable, provide explicit stable `target` and `assumptions` in the original report request. The bundle adds those values to an enriched run-local report manifest; reports without them should not be treated as replayable.

This is a C implementation handoff, not a claim that all seven request modes or the overall R14/R17 requirements are complete.
