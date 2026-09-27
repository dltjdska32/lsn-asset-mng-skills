# Investment Stack — Implementation Status

Last updated: 2026-09-27

## R15 PACKAGE-01 — 2026-09-27 checkpoint

- Work is isolated on `codex/luna-r15-package-01` from root base `fd4355e5d4ed13f4aeacd34eacb7e40e74431342`.
- The authoritative source tree and `.agents/skills` mirror contain exactly the same eight skill names and the same two allowlisted files (`SKILL.md`, `agents/openai.yaml`) byte-for-byte. `review` is unchanged; D08 remains unresolved.
- Distribution/runtime `0.1.0` is distinct from architecture `v1.3`, contract `0.2`, personal/run schema migration numbers `3`/`2`, and per-file config versions. No version mapping or schema upgrade is implied.
- Python metadata allows `>=3.11`; this task verified Windows Python 3.14.6 only. Using an existing build venv (`build==1.6.1`, `setuptools==84.0.0`), wheel and sdist built with `--no-isolation`. A fresh target venv reused the locally installed `tzdata==2026.4` and `truststore==0.10.4` payloads without downloads, then installed the wheel offline through its own `Scripts/python.exe`; `pip check`, both IANA zone loads, and `investment_stack.__version__ == 0.1.0` passed.
- The same target interpreter ran **10/10** R15 packaging/sync tests, `investment-stack check` (11 invariants), a `THESIS_REVIEW` plan smoke, a synthetic `REPORT_REFRESH` execute preflight smoke, config loads from `sys.prefix/config`, and `scripts/sync_agent_skills.py --check`. No full repository suite, live provider call, account credential, personal DB, or Codex UI auto-discovery from the venv prefix was tested.
- The exact deployment path allowlist is `docs/workflow/deployment-allowlist.md`. The installed wheel's skill payload is verified under `sys.prefix/skills` and `sys.prefix/.agents/skills`; automatic Codex UI discovery from an arbitrary virtual-environment prefix is not established.

## Current Status (Integration Checkpoints `a861b6b`, `5d094a5`)

As of **2026-09-27**, the system is undergoing a final multi-agent integration. The following milestones represent the current merged state:

- **Completed in this checkpoint (`a861b6b`):**
  - Agent A: Price safety precursors and contracts.
  - Agent B: R06–08 quote/bar parsing and deterministic technical-calculation components, fail-closed signal gates, and 8-skill package layout. See the dated B follow-up below for live verification limits.
  - Agent C: 13F filing structure, 5-section briefing formats, and WAIT action arithmetic precursors.
- **Current Test Baseline:** 
  - Root unittest: 470 OK, 1 skip at `a861b6b`; 475 OK, 1 skip after SEC parser integration at `5d094a5` plus the corrected empty-tag test.
  - Isolated venv wheel installation & package tests: 5 PASS (verified at prior commit `571101af`).
- **Skill Discovery:** Repo-local 8 skills were successfully discovered in the current Codex Available skills list.

### Pending / Incomplete

- Agent A: R02–05 / R09 (SEC fact parser is integrated as a bounded slice; period-coherent consumption and provider fallback remain incomplete).
- Agent C: Formal R10–11 integration.
- Runtime Execution: Actual execution of the 7 request modes.
- R17 Number Combination logic.
- Full independent review and final verification session (to be scheduled after all agents merge).

## B Follow-up Verification — 2026-09-27

This update belongs to `codex/luna-b-transfer-02`, based on `0ed93d8e100494a350f5ecde160c72ffafaf26a1`. It is a B-scope check, not root integration or full-stack verification.

- The B quote, OHLCV, and technical fixture suite passes **45 tests** in a Windows venv containing the declared `truststore` and `tzdata` dependencies. These are synthetic fixture tests, not live-source evidence.
- Root integration at `83dfb27` connected a scoped `truststore.SSLContext` to the default `providers/http.py` transport. Public probes through that default transport returned HTTP 200 for the Naver Samsung quote and daily-price APIs, the Naver stock page, Yahoo Finance AAPL chart API, and Coinbase BTC-USD ticker API. The B adapters parsed Naver, Yahoo, and Coinbase quote responses; Yahoo daily OHLCV produced 22 parsed bars. This confirms connectivity and parsing only, not data freshness, adjustment validity, or session completeness.
- The Naver quote response parsed as `LAST_VALID_CLOSE` with an observation time of **2026-09-23 15:30 KST**, although retrieved on 2026-09-27. Its provider result was `AVAILABLE` because the R01 eligibility evaluator was not supplied. This is stale data and does not establish a current KRX price.
- Naver's `/price` endpoint returned a top-level list with no ticker field and comma-grouped numeric strings. The parser now binds the payload to the matching canonical Naver request route, parses grouped numbers, preserves five raw bars in the live probe, and returns `UNAVAILABLE` without adjustment verification. Route binding is request provenance, not an identity echoed in the response.
- Direct Investing.com US and Korea page requests returned HTTP 403. Those entries remain fixture-only and are not used as live quote sources.
- Historical note: before the A integration at `83dfb27`, the default `providers/http.py` transport failed TLS verification in this Windows environment (`CERTIFICATE_VERIFY_FAILED`). That issue was resolved by the scoped TLS integration; this B follow-up does not edit the A-owned transport.
- The adjustment receipt is still a caller-supplied marker rather than a validated corporate-action record. No split-adjusted Naver OHLCV result is claimed from the live probe. R01 freshness policy wiring, an accepted corporate-action receipt verifier, market-session coverage checks, and R08-to-briefing calculation binding remain integration work. R08's pure functions also accept `Sequence[Bar]`, which carries no source provenance; callers must not feed raw diagnostics into production calculations.
- The wheel-installed Codex UI auto-discovery path was not proven by repo-local skill discovery. Current build/install checks must be read as package file-layout checks only.

---

## Architecture

- Version: v1.3
- Status: ARCHITECTURE FROZEN
- Authoritative document: `ARCHITECTURE.md`
- Do not redesign the architecture without an explicit approved change decision.

## Historical Status (As of 2026-08-14)

- Phase 1 — Repository / Skeleton: COMPLETE
- Phase 2 — Storage Safety: COMPLETE
- Phase 3 — Ledger & Projection: COMPLETE
- Phase 4 — Evidence & Research: IMPLEMENTED
- Phase 5 — Asset Analysis: IMPLEMENTED
- Phase 6 — Report & Review: IMPLEMENTED
- Phase 7 — Acceptance: COMPLETE
- Phase 8 — Final Integration / Hardening: *(Historically marked as READY FOR FINAL PRE-COMMIT REVIEW; currently superseded by the 2026-09-27 integration effort above)*

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
