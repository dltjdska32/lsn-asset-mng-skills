# Investment Stack — Implementation Status

Last updated: 2026-08-14

## Architecture

- Version: v1.3
- Status: ARCHITECTURE FROZEN
- Authoritative document: `ARCHITECTURE.md`
- Do not redesign the architecture without an explicit approved change decision.

## Current Status

- Phase 1 — Repository / Skeleton: COMPLETE
- Phase 2 — Storage Safety: COMPLETE
- Phase 3 — Ledger & Projection: COMPLETE
- Phase 4 — Evidence & Research: IMPLEMENTED
- Phase 5 — Asset Analysis: IMPLEMENTED
- Phase 6 — Report & Review: IMPLEMENTED
- Phase 7 — Acceptance: COMPLETE
- Phase 8 — Final Integration / Hardening: IMPLEMENTED, READY FOR FINAL PRE-COMMIT REVIEW

## Phase 4 Implemented

- Free-first provider contracts and deterministic fallback execution.
- Optional OpenDART credential via `OPENDART_API_KEY`; missing credentials become `MISSING_CREDENTIAL` rather than a run-wide failure.
- Keyless SEC Company Facts adapter and timestamped Kraken public trade adapter.
- Existing Web Research adapter boundary for latest/current fallback and `LATEST_RELEVANT_NEWS`; no separate news Skill, Agent, table, or database.
- Immutable `analysis_as_of` / `analysis_timezone` run context and pinned personal `state_version` support.
- Freshness states: `FRESH`, `DELAYED`, `LAST_VALID_CLOSE`, `STALE`, `UNKNOWN`, `UNAVAILABLE`.
- Retrieval time is never promoted to observation time.
- Evidence, provider state, market/financial/macro observation, freshness, selection, conflict, and calculation lineage in `run.db`.
- Conflicting comparable source values are recorded and never averaged.
- Financial numbers reported only by news are persisted as `NEWS_REPORTED` but are not approved/selected as calculation inputs.
- Research data remains isolated from `personal.db`.


## Phase 5 Implemented

- Three-axis instrument resolution: economic underlying, wrapper, and custody/account context.
- Equity fundamental calculations for growth, margins, free cash flow, leverage/liquidity, ROE, and ROIC when inputs exist.
- Asset-appropriate equity valuation model selection with explicit-only DCF assumptions, multiples, financial P/B/ROE/dividend, SOTP, and NAV paths.
- ETF/fund NAV premium-discount, costs, AUM/liquidity, tracking difference, concentration, dated holdings, look-through exposure, and overlap.
- Bitcoin venue/custody-aware return, volatility, drawdown, liquidity/supply/network context without corporate valuation.
- Gold real-rate/USD/physical-premium context and silver industrial-demand/physical-premium context without corporate valuation.
- Portfolio materiality gate with automatic pass for directly requested assets and uncertainty pass for confirmed unvalued positions.
- Cross-asset allocation across account, asset class, country, currency, sector, region, liquidity, custody, look-through, leverage, with unvalued positions preserved.
- Aligned historical volatility, drawdown, correlation, and position-level risk contribution; unaligned series stay partial instead of being forward-filled.
- Phase 5 calculation and materiality lineage is persisted only to `run.db`; `personal.db` is not mutated.


## Phase 6 Implemented

- Partial-aware derived report builder persisted only in `run.db.report_sections`.
- Report headers expose pinned `Analysis As Of`, `Market Data As Of`, `Financial Data As Of`, `Macro Data As Of`, and `Portfolio Data As Of`; missing values remain `UNKNOWN`.
- Current-value claims require selected, timestamped, non-stale market evidence; `retrieved_at` is never substituted for market observation time.
- Report sections carry explicit `AVAILABLE` / `PARTIAL` / `UNAVAILABLE` status, evidence IDs, calculation lineage, unknowns, and confidence.
- Rumor/unverified evidence cannot change a base case; material `NEWS_REPORTED` evidence downgrades the section and triggers review.
- Deterministic conditional review covers source conflicts, stale/unknown critical data, materiality, lineage failures, unsupported models/requests, large impact, material news/rumor, and strong strategy changes.
- Optional independent reviewer callbacks run only when the conditional gate triggers; their failure does not suppress deterministic partial reports.
- Review findings and report sections are derived run-local outputs and never mutate `personal.db`.
- Report text applies credential-shaped redaction before persistence/rendering.

## Critical Runtime Invariants

- `personal.db` is the long-term personal Source of Truth.
- `run.db` is per-analysis evidence only.
- Personal mutation uses `PersonalDatabaseManager.guarded_write_transaction()`.
- Posted ledger rows are append-only.
- Correction is atomic `REVERSAL + complete replacement`; there is no `CORRECTION` transaction type.
- Projections are rebuildable from the ledger.
- `analysis_as_of` is pinned once per run and cannot move forward during the run.
- `retrieved_at` does not substitute for `observed_at`, `published_at`, or market/event time.
- Future observations (`observation_time > analysis_as_of`) cannot be selected.
- Search snippets, undated pages, old articles, blogs, and analyst reports are not accepted as current-price observations.
- Provider failures and missing credentials fail soft to fallback/partial/unavailable states.
- Research/evidence never writes to `personal.db`.
- Web Research remains an adapter, not a separate Skill/Agent/DB/Pipeline/Request Mode.
- Materiality decisions are completed before portfolio deep-analysis callbacks run.
- Bitcoin, gold, and silver never use corporate DCF/EPS valuation paths.
- Fund look-through without a dated holdings set is Partial/Unknown rather than current.
- Historical portfolio risk requires aligned series; no blind forward-fill is introduced.

## Important Phase 4 Files

- `runtime/investment_stack/providers/models.py`
- `runtime/investment_stack/providers/http.py`
- `runtime/investment_stack/providers/adapters.py`
- `runtime/investment_stack/providers/execution.py`
- `runtime/investment_stack/providers/factory.py`
- `runtime/investment_stack/freshness/models.py`
- `runtime/investment_stack/freshness/engine.py`
- `runtime/investment_stack/web_research/models.py`
- `runtime/investment_stack/web_research/adapter.py`
- `runtime/investment_stack/evidence/manager.py`
- `runtime/investment_stack/evidence/research.py`
- `runtime/investment_stack/research.py`
- `runtime/investment_stack/migrations/run/v0002_phase4_evidence.py`
- `tests/unit/test_phase4_providers.py`
- `tests/unit/test_phase4_freshness_web.py`
- `tests/integration/test_phase4_evidence_research.py`
- `tests/acceptance/test_phase4_research_flow.py`


## Important Phase 5 Files

- `runtime/investment_stack/asset_analysis.py`
- `runtime/investment_stack/calculations/common.py`
- `runtime/investment_stack/calculations/instruments.py`
- `runtime/investment_stack/calculations/equity.py`
- `runtime/investment_stack/calculations/valuation.py`
- `runtime/investment_stack/calculations/fund.py`
- `runtime/investment_stack/calculations/alternative.py`
- `runtime/investment_stack/calculations/allocation.py`
- `runtime/investment_stack/calculations/risk.py`
- `runtime/investment_stack/materiality/engine.py`
- `tests/unit/test_phase5_equity_valuation.py`
- `tests/unit/test_phase5_fund_alternative.py`
- `tests/unit/test_phase5_materiality_allocation_risk.py`
- `tests/integration/test_phase5_asset_runtime.py`
- `tests/acceptance/test_phase5_asset_analysis.py`

## Live Deep Research Integration

- `runtime/investment_stack/deep_research.py` now bridges selected equity assets from Phase 4 Provider/Web Research into Phase 5 fundamental and valuation analyzers.
- Multi-metric financial evidence selects one latest-as-of winner per metric instead of collapsing an entire filing to one selected row.
- `WebResearchBundleBackend` lets Codex-supplied official web facts enter the runtime without bypassing freshness/evidence lineage.
- `scripts/run_live_equity_research.py` provides a reproducible runtime entry point for structured external research.
- Screenshot prices remain non-authoritative portfolio snapshot evidence.

## Current Test Baseline

- Phase 4 targeted tests: 26/26 PASS
- Phase 5 targeted tests: 35/35 PASS
- Phase 6 targeted tests: 25/25 PASS
- Phase 7 focused acceptance/integration/adversarial tests: 16/16 PASS
- Phase 8 focused final-integration/hardening tests: 10/10 PASS
- Final full unittest: 272/272 PASS on this Linux validation host (2 platform-conditional skips)
- Installed-wheel unittest: 272/272 PASS (same 2 platform-conditional skips)
- Architecture invariant: 9/9 PASS
- Phase 8 delta whitespace check: PASS; run `git diff --check` once more in the real user Git working tree

## Validation Commands

```bash
PYTHONPATH=runtime python -m compileall -q runtime tests
PYTHONPATH=runtime python -m unittest discover -s tests -v
PYTHONPATH=runtime python -m investment_stack check --project-root . --json
git diff --check
```

The wheel should also be built and installed into a clean virtual environment before commit approval.

## Important Phase 6 Files

- `runtime/investment_stack/reporting/models.py`
- `runtime/investment_stack/reporting/builder.py`
- `runtime/investment_stack/reporting/runtime.py`
- `runtime/investment_stack/review/models.py`
- `runtime/investment_stack/review/engine.py`
- `runtime/investment_stack/evidence/manager.py`
- `tests/unit/test_phase6_report_review.py`
- `tests/integration/test_phase6_report_runtime.py`
- `tests/acceptance/test_phase6_report_review.py`
- `tests/adversarial/test_phase6_report_failures.py`

## Phase 7 Implemented

- Expanded executable structural invariants for the frozen v1.3 boundary.
- MVP acceptance regression across ledger, research, asset analysis, report/review, and cross-phase isolation.
- Validated backup/restore drill that confirms ledger, projection, and state-version recovery.
- Final cross-phase failure tests for personal Source-of-Truth isolation and future-data/current-value separation.
- Detailed acceptance record: `docs/PHASE7_ACCEPTANCE.md`.

## Phase 8 Implemented

- Final implementation-roadmap integration/hardening without changing canonical v1.3 architecture.
- All seven Request Modes and fixed-pipeline boundaries are revalidated, including non-posting hypothetical scenarios.
- Full-stack Provider → Evidence → Asset Analysis → Calculation Lineage → Report/Review integration.
- Persisted Phase 5 `calculation_id` is propagated into report-section lineage.
- Cross-phase personal Source-of-Truth isolation and pinned `state_version` preservation.
- Deterministic semantic calculation regression across independent runs.
- Failure injection for unexpected provider timeout, credential-bearing transport failure, and optional reviewer failure.
- Release invariant rejecting repo-local secret/runtime DB artifacts.
- Detailed record: `docs/PHASE8_FINAL_HARDENING.md`.

## Next

Run the final Phase 8 release gate, then perform one independent pre-commit review on the real Git working tree. If Critical/High remain 0, commit/tag the v1.3 MVP. AWS/MCP/web/mobile connectivity remains post-v1.3.
