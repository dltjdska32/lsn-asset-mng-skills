# Investment Stack — Implementation Status

Last updated: 2026-09-28

## CLOSE-R11 D12 data binding — independently reviewed code `9fa62bd`

The B policy now has a read-only adapter for the pinned personal ledger projection and a read-only market/DCF adapter. Portfolio analysis renders a five-part D12 section. Independent review found and returned stale/fake close labels, divergent instrument/time/provider/unit records, self-authored DCF/quote source strings, and fake reference flags releasing action numbers. The fixes reassess bounded NASDAQ/KRX sessions and timestamps, keep source-content-unproven DCF and D12 quote values unavailable, and withhold entry prices, budgets, and quantities in the public report. Pure lot/fee arithmetic is labeled `ARITHMETIC_ONLY` and cannot release a report action. The ordinary Phase 4 → 5 Sunday prior-session close path remains tested.

Two GPT-6 Luna Medium implementation sessions worked in separate `codex/close-a` and `codex/close-b` branches/worktrees; the coordinator owned integration/report files. At code source `9fa62bd30fc5214b2ee275748e28515babe8f15f`, a fresh wheel/sdist build, 67 focused tests, and **698 full tests OK (1 skipped)** passed. A separate Codex reviewer re-ran the adversarial probes and 63 focused tests and found no remaining P1/P2 in the implemented safety boundary. A different Codex final verifier is still pending, so this is not final sign-off. See [review](docs/workflow/reviews/CLOSE-R11-REVIEW-01.md), [handoff](docs/workflow/handoffs/CLOSE-R11.md), and [task memory](docs/workflow/tasks.md).

This does **not** complete live R11 investment recommendations. Authenticated market and DCF source-content receipts, marked personal holdings/FX, emergency and planned-spending reserves, pending-order reservations, and verified fee/lot rules have no complete production binding. User-specific add/reduce prices, budgets, and quantities remain `WAIT`; no real personal DB or order was used. Calendar coverage is limited to the pinned September 2026 sessions and the default CLI still needs host injection.

## D12 B selected policy — independently verified exact source `61fd2eb`

The user selected B: three equal-budget entry tiers at 80%/75%/70% of a verified base fair value, an 8% individual-equity cap, a 10% investable-cash floor after separate reserves, concentration reduction review strictly above 10% toward 8%, review of a one-third reduction at or above 1.2 times verified optimistic fair value, and a stop/review on thesis impairment. A pure non-posting policy evaluator implements these rules. It returns no numeric entry tiers or add budget without complete typed values and trusted-host readiness attestations. The generic equity report records that B was selected but leaves actionable entry prices, amounts, and quantity at WAIT; DCF scenario values alone cannot clear its provenance gate. No order or ledger post is performed.

The separate Luna Medium implementation used `codex/d12-b`/`workspace/cache/d12-b`; source `c473915`, corrections `dcbd6aa`, `afe7156`, `386296d` were integrated as `ba3ef0a`, `10bf46d`, `dd0e793`, `61fd2eb`. An independent Codex review found one P1 numeric-entry leakage and two P2 arithmetic/reduction issues at `91adaa2`; after fixes it re-reviewed exact `61fd2eb`, passed focused **39/39**, and found no new P1/P2. The coordinator rebuilt wheel/sdist and passed the full **671 OK (1 skipped)** at that source. A different Codex session then verified the same exact source in an isolated temporary archive: 512/512 tracked blobs, fresh wheel/sdist, full **671 OK (1 skipped)**, installed-wheel policy boundary probes, and DCF-only WAIT reporting, with no order or ledger write. See [review](docs/workflow/reviews/D12-B-REVIEW-01.md), [separate final verification](docs/workflow/reviews/D12-B-VERIFY-01.md), [task memory](docs/workflow/tasks.md), and [handoff](docs/workflow/handoffs/D12-B.md).

The readiness bundle contains trusted-host attestations but cannot prove persisted personal records by itself. There is no production host currently binding personal state, reserve exclusions, current quote, valuation assumptions, FX, fees, and trade units to it; user-specific entry/reduction amounts and quantities remain WAIT. The earlier sections below are historical checkpoints, not the current D12 decision state.

## ANALYSIS-FIRST integration — independently verified source `9e781ec`

Three GPT-6 Luna Medium implementation agents worked in separate branches/worktrees and handed off A/B/C changes. The integrated equity single/comparison modes now check Phase 5 result content against same-run persisted calculations, expose conditional valuation findings and a WAIT briefing, and render a registered/recomputed technical section with its formula version and periods in the actual report. The portfolio materiality-selected equity adapter executes Phase 4 → 5 and displays only complete persisted results, with Korean metric labels. Dated weekend closes remain explicitly `LAST_VALID_CLOSE`, not intraday quotes. No personal DB or automatic order was used.

An independent Codex reviewer found forged selected-asset findings (P1) and dated-close, technical-detail, and body-label regressions (P2); after fixes, its second pass found that the technical detail was only in metadata and a selected-market mismatch was possible. These were returned to B/A and fixed. A different Codex final verifier found a future selected-asset close accepted on `3214f6a`; C fixed that on `9e781ecf92288b1d95731837dec50e12bc81755d`. The coordinator rebuilt wheel/sdist and ran **648 tests OK, 1 skipped** plus **47/47 focused** on this exact source. The different Codex verifier repeated an isolated fresh build and full **648 OK, 1 skipped** after checking 507/507 tracked blobs, and passed the forged/future/valid close, technical markdown, DCF, and WAIT probes with no new P1/P2 in the changed scope. See [review](docs/workflow/reviews/ANALYSIS-FIRST-REVIEW-01.md), [independent final verification](docs/workflow/reviews/ANALYSIS-FIRST-VERIFY-01.md), and [task memory](docs/workflow/tasks.md).

At this historical checkpoint D12 policy candidates had been presented but none was chosen. Provider authenticity, broad calendar coverage, 13F out-of-sample adoption, and default CLI host setup retain their documented limits.

## FINISH Integration — Independently Re-reviewed Source `53b6be0`

Three GPT-6 Luna Medium implementation agents used separate branches/worktrees. Their integrated additions cover a fail-closed persisted-numeric equality helper, a provenance-checked technical briefing context, and clearer Korean report/review text with immutable content-addressed report sections. The coordinator rebuilt wheel/sdist and ran the full suite at source `53b6be01f45ad5b57e8d0718b270f4a14fe01649`: **622 OK, 1 skipped**. A separate Codex review reproduced a pinned-cutoff bypass, forged technical-parameter exception, obscured review reasons, and old-manifest section collisions. Fixes were re-reviewed on the exact final source; focused **44/44**, full **622 OK, 1 skipped**, and no new P1/P2 in the changed scope. See [FINISH-REVIEW-01](docs/workflow/reviews/FINISH-REVIEW-01.md). A different Codex agent independently verified the exact source via 496/496 archive blob matches, a fresh wheel/sdist build, full **622 OK, 1 skipped**, and cutoff, forgery, immutable-section, equity-manifest, and CLI-boundary probes. See [FINISH-VERIFY-01](docs/workflow/reviews/FINISH-VERIFY-01.md).

These helpers are not yet called by the fixed analysis modes. The final equity briefing still passes `eligibility_decisions=None` and `has_policy=False`, so it does not expose unbound numeric claims or authorize an investment size. R08 chart and 13F context are not bound into that briefing, and R13 out-of-sample validation plus user-approved D12 safety-margin/risk/sizing policy remain open. The September 2026 NASDAQ/KRX pinned calendar, vendor coverage, and default CLI host wiring retain the limits described below. This integration is not completion of all R01–R17 requirements.

## Independently Reviewed Integration — `4e55a56` (2026-09-28)

An independent Codex review directly checked commit `4e55a560b4245ad5fb63cf4de8a2ce9813a2752a` in a separate worktree and passed the implemented code scope. Root and reviewer each rebuilt wheel/sdist and ran the full suite: **600 tests OK, 1 skipped**. The reviewer also passed 20/20 preserved independent probes, 10/10 refresh-manifest boundary checks, two briefing roundtrip/refresh checks, and 11/11 clean installed-wheel packaging checks. See [the review](docs/workflow/reviews/REVIEW-CODE-01.md).

A **different Codex task** then directly verified exact checkout `2a078da91ddfd761a1785ee482f3cd23eb1acaf7` (no runtime changes after `4e55a56`) and passed the documented implementation scope. It rebuilt wheel/sdist, ran source **600 OK/skip1** and clean installed-wheel **600 OK/skip0**, plus independent 20/20, manifest 10/10, briefing roundtrip 2/2, clean R15 11/11, unpacked sdist 11 OK/skip1, and fresh synthetic ledger/dated-close probes. See [VERIFY-01](docs/workflow/reviews/VERIFY-01.md). This does not certify the unfinished policy, sizing, general calendar, provider, or default CLI host wiring described below.

A second separate Codex task independently repeated the exact-SHA build in an isolated Git clone, source and installed-wheel full suites (**600 OK/skip1** and **600 OK/skip0**), the preserved 20/20 + 10/10 + 2/2 checks, packaging/skills and artifact byte comparison. See [VERIFY-02](docs/workflow/reviews/VERIFY-02.md). It used the fixed 2026-09-27 market-data fixtures rather than making a new live public-quote claim.

Refresh now carries the replay's stored PARTIAL state and missing inputs through internal and external fixed runners. Multi-manager 13F direction uses validated per-manager period chains. Equity reports render a five-part Korean **WAIT** briefing, persist both its rendered and typed forms under an immutable content reference, and include its fingerprint in the report reference and refresh delta. No buy/sell quantity or automatic order is authorized. Verified chart/13F evidence is not yet bound into the complete action briefing; the approval policy, sizing criteria, general market-calendar coverage, live vendor breadth, and default CLI host wiring remain outside this checked scope.

## R15 PACKAGE-01 — 2026-09-27 checkpoint

- Work is isolated on `codex/luna-r15-package-01` from root base `fd4355e5d4ed13f4aeacd34eacb7e40e74431342`.
- The authoritative source tree and `.agents/skills` mirror contain exactly the same eight skill names and the same two allowlisted files (`SKILL.md`, `agents/openai.yaml`) byte-for-byte. `review` is unchanged; D08 remains unresolved.
- Distribution/runtime `0.1.0` is distinct from architecture `v1.3`, contract `0.2`, personal/run schema migration numbers `3`/`2`, and per-file config versions. No version mapping or schema upgrade is implied.
- Python metadata allows `>=3.11`; this task verified Windows Python 3.14.6 only. Using an existing build venv (`build==1.6.1`, `setuptools==84.0.0`), wheel and sdist built with `--no-isolation`. A fresh target venv reused the locally installed `tzdata==2026.4` and `truststore==0.10.4` payloads without downloads, then installed the wheel offline through its own `Scripts/python.exe`; `pip check`, both IANA zone loads, and `investment_stack.__version__ == 0.1.0` passed.
- The same target interpreter ran **10/10** R15 packaging/sync tests, `investment-stack check` (11 invariants), a `THESIS_REVIEW` plan smoke, a synthetic `REPORT_REFRESH` execute preflight smoke, config loads from `sys.prefix/config`, and `scripts/sync_agent_skills.py --check`. No full repository suite, live provider call, account credential, personal DB, or Codex UI auto-discovery from the venv prefix was tested.
- The exact deployment path allowlist is `docs/workflow/deployment-allowlist.md`. The installed wheel's skill payload is verified under `sys.prefix/skills` and `sys.prefix/.agents/skills`; automatic Codex UI discovery from an arbitrary virtual-environment prefix is not established.

## Current Integrated Checkpoint (`a1a41b0`)

As of **2026-09-27**, the integration includes the A/C changes and B's R15 source-distribution repair. These figures and results are an integration checkpoint before the final independent review and any subsequent verification or fixes; they are not a release sign-off.

- **Tests and review:** root unittest reported **595 OK, 1 skip**. The independent fixed review reported **13/13 PASS**. These totals do not replace final independent review or later checks.
- **R02–05 / R09:** the SEC facts and period-aware evidence-consumption slices are integrated; they are no longer waiting on initial A integration. Provider coverage remains bounded by the registered adapters and their live verification.
- **Seven request modes:** all seven fixed plans have configured service handlers through [`compose_seven_mode_services`](runtime/investment_stack/execution/service_composition.py), including the Phase 4 → Phase 5 selected-equity path and the portfolio/thesis bundles. See the [composition handoff](docs/workflow/handoffs/LUNA-R14-SEVEN-MODE-COMPOSITION-01.md). Composition requires a host to inject a valid pinned `run.db`, a `PersonalLedgerService`, equity and portfolio/thesis services, credentials/providers, and typed personal-state loaders/callbacks. It does not create or select those dependencies.
- **Configured-mode E2E scope:** PASS confirms the exercised fixed service compositions and mode flows under injected dependencies. It does not certify R10/R11/R17 as complete or mean that a final investment judgment or completed five-section briefing is wired end-to-end.
- **Briefing integration gap:** [`analysis_modes.render_report`](runtime/investment_stack/execution/analysis_modes.py) currently passes fundamentals, valuation, comparison, and review sections to Phase 6; it does not pass `NonPostingBriefing` to [`InvestmentReportBuilder`](runtime/investment_stack/reporting/builder.py). R08 chart evidence and 13F context are not yet bound into the five-section briefing. A is working on the safe WAIT-briefing connection; C's RC10-R1/RC11 work is in progress. Treat this as current/in-progress, not complete.
- **CLI boundary:** [`investment-stack execute`](runtime/investment_stack/cli.py) has no configured runtime handlers by default. Without `runtime_services`, it executes against empty `RuntimeServices()` and returns `UNSUPPORTED`; the CLI does not bootstrap providers, credentials, databases, or personal loaders.
- **Market close qualification:** the [default provider factory](runtime/investment_stack/providers/factory.py) wires pinned calendars for NASDAQ and KRX (see [calendar registry](runtime/investment_stack/freshness/calendar.py)) and can select a verified dated close as `LAST_VALID_CLOSE`. The bundled snapshots cover only their explicitly pinned September 2026 sessions. They do not provide general weekend or exchange-calendar coverage; unsupported exchanges/dates fail closed for stale-close qualification. A `LAST_VALID_CLOSE` remains a dated close, not an intraday/current live quote.
- **Live evidence limits:** a 2026-09-27 public-source integration query carried Yahoo's 2026-09-25 close and Naver's 2026-09-23 close through Phase 4 evidence persistence into Phase 5 valuation, labeled `LAST_VALID_CLOSE` (see [R01 integration handoff](docs/workflow/handoffs/R01-WEEKEND-PRICE-01.md)). This verifies that path for those requests at that time, not ongoing vendor availability or broad provider coverage. Investing.com direct page requests returned HTTP 403 in the recorded probe. OpenDART credentialed access requires the host to supply `OPENDART_API_KEY` through the credential interface.
- **Data and packaging boundaries:** the service host must inject the personal loader/ledger; integration checks used synthetic or temporary run data, not the user's personal DB. Wheel payload paths are verified, but Codex automatic skill UI discovery from an arbitrary venv prefix remains unconfirmed.
- **Still pending:** R10/R11/R17 completion, safe WAIT-briefing/report integration including R08 chart and 13F context binding, final independent review, another final verification pass, any resulting fixes, and reassessment of counts at the resulting root commit. R17 number-combination logic remains open.

## Historical B Follow-up Verification — 2026-09-27

The B-only statements below describe the earlier provider-integration stage. Later R01 integration superseded the earlier conclusions that freshness evaluation was unwired and that Naver could not qualify for a current-price calculation. Current behavior and bounded calendar coverage are summarized in the integrated checkpoint above.

This update belongs to `codex/luna-b-transfer-02`, based on `0ed93d8e100494a350f5ecde160c72ffafaf26a1`. It is a B-scope check, not root integration or full-stack verification.

- The B quote, OHLCV, and technical fixture suite passes **45 tests** in a Windows venv containing the declared `truststore` and `tzdata` dependencies. These are synthetic fixture tests, not live-source evidence.
- Root integration at `83dfb27` connected a scoped `truststore.SSLContext` to the default `providers/http.py` transport. Public probes through that default transport returned HTTP 200 for the Naver Samsung quote and daily-price APIs, the Naver stock page, Yahoo Finance AAPL chart API, and Coinbase BTC-USD ticker API. The B adapters parsed Naver, Yahoo, and Coinbase quote responses; Yahoo daily OHLCV produced 22 parsed bars. This confirms connectivity and parsing only, not data freshness, adjustment validity, or session completeness.
- The earlier B-only probe observed the Naver close at **2026-09-23 15:30 KST** when retrieved on 2026-09-27. At that stage the provider result was only `AVAILABLE` because the R01 evaluator was not supplied. Later root integration wired the evaluator and pinned KRX schedule through the default factory; the same dated close can then be qualified as `LAST_VALID_CLOSE`, not as an intraday quote.
- Naver's `/price` endpoint returned a top-level list with no ticker field and comma-grouped numeric strings. The parser now binds the payload to the matching canonical Naver request route, parses grouped numbers, preserves five raw bars in the live probe, and returns `UNAVAILABLE` without adjustment verification. Route binding is request provenance, not an identity echoed in the response.
- Direct Investing.com US and Korea page requests returned HTTP 403. Those entries remain fixture-only and are not used as live quote sources.
- Historical note: before the A integration at `83dfb27`, the default `providers/http.py` transport failed TLS verification in this Windows environment (`CERTIFICATE_VERIFY_FAILED`). That issue was resolved by the scoped TLS integration; this B follow-up does not edit the A-owned transport.
- The adjustment receipt remains a caller-supplied marker rather than a validated corporate-action record. No split-adjusted Naver OHLCV result is claimed from the live probe. The later R01 work adds bounded pinned-schedule close qualification; it does not create general calendar coverage. R08's pure functions also accept `Sequence[Bar]`, which carries no source provenance; callers must not feed raw diagnostics into production calculations.
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

## Earlier Phase-Specific Test Records

- Phase 4 targeted tests: 26/26 PASS
- Phase 5 targeted tests: 35/35 PASS
- Phase 6 targeted tests: 25/25 PASS
- Phase 7 focused acceptance/integration/adversarial tests: 16/16 PASS
- Phase 8 focused final-integration/hardening tests: 10/10 PASS
- These phase-specific totals and older 272-test full-suite runs are historical and are superseded by the `a1a41b0` root checkpoint above (595 OK, 1 skip).
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

Complete the final independent review and other verification against the then-current integrated root, address any findings, and update this checkpoint's counts. The current checkpoint does not certify broad vendor live coverage or default CLI bootstrapping. AWS/MCP/web/mobile connectivity remains post-v1.3.
