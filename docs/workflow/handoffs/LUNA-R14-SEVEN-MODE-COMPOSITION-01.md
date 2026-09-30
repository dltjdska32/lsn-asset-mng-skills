# LUNA R14 Seven Mode Composition Handoff

## Assignment

- Task ID: `LUNA-R14-SEVEN-MODE-COMPOSITION-01`.
- Base root: `eab91c3940dda252cf1ae9988f6fc921f78b4c02`.
- Branch: `codex/r14-seven-mode-composition`.
- Owned files: `runtime/investment_stack/execution/service_composition.py`, `runtime/investment_stack/execution/__init__.py`, `tests/integration/test_r14_seven_mode_composition.py`, this handoff.
- Dependencies: existing A `equity_analysis_services`, C `portfolio_thesis_services`, existing `asset_update_services`, `RunDatabaseManager`, and explicitly injected `PersonalLedgerService`.
- C-owned `portfolio_thesis_modes.py` was not modified.

## Host composition and call boundary

```python
equity = equity_analysis_services(
    deep_research=deep_research, phase6=phase6, run_db=run_db,
)
portfolio = portfolio_thesis_services(
    run_db=run_db,
    base_services=equity,
    # Inject the required typed loaders, collectors, and refresh resolver here.
)
services = compose_seven_mode_services(
    run_db=run_db,
    ledger=personal_ledger,  # caller opened/configured it explicitly
    equity_services=equity,
    portfolio_thesis_services=portfolio,
)
result = execute_mode(ModeRequest(run_db.run_id, selected_mode, payload), services)
```

The caller must create/pin the run database and personal ledger, provide providers and typed callbacks, and construct both A/C service bundles before composition. The factory does not select a request mode, create/open either database, or infer the personal DB location. It requires the exact same run database instance in both bundles, checks all fixed plan handlers are present, and rejects attempts to include ledger steps in the portfolio/thesis bundle. It adds ledger handlers only for the six ASSET_UPDATE steps. Every composed handler also checks that the request run ID equals the bound run DB. Per-mode personal-state and replay pin checks remain enforced by the existing mode handlers. Scenario, report refresh, thesis, equity, and portfolio plans do not include ledger writer steps and return no mutation receipt.

Composition does not imply every request can run with an arbitrary run metadata mode or without required pinned state. Create the run with the correct immutable request mode/clock/state and provide all mode-required typed inputs. The C portfolio/thesis bundle must have been constructed with this same equity bundle as `base_services` so fixed-step delegation is active.

## CLI boundary

The existing CLI `main(argv, runtime_services=None)` calls `execute_mode(request, runtime_services or RuntimeServices())`. The default `RuntimeServices()` has no handlers, so `investment_stack execute ...` without application-supplied runtime services returns `UNSUPPORTED`; the CLI does not discover or build a configured host. An embedding application can import the composition factory and pass the returned `RuntimeServices` to `main(..., runtime_services=services)`. This task does not add default service construction to the CLI because it would require application-specific provider credentials, run DB selection, personal DB selection, and explicit confirmation policy.

## Verification and limits

- Dedicated integration verifies all seven planner plans have handlers, six synthetic non-update plans return partial without a receipt or ledger version change, explicit ASSET_UPDATE posts and returns a receipt, wrong run IDs fail closed, and mixed run DB bundles are rejected. It also composes real `equity_analysis_services()` with real `portfolio_thesis_services(base_services=equity)` and runs both a synthetic SINGLE_ASSET_ANALYSIS E2E and a typed synthetic THESIS_REVIEW E2E through the composed bundle.
- Test storage is temporary and synthetic. No external personal DB was opened.
- The six-mode handler coverage assertions use synthetic service results; only the real equity and thesis modes above exercise their complete concrete pipelines here. This task does not certify provider behavior or all C portfolio/thesis inputs. Existing focused service-bundle tests remain separate.
- Do not use this as authorization for automatic ledger creation or order posting. Ledger mutation still requires a caller-provided ledger and the existing explicit confirmed transaction intent.
