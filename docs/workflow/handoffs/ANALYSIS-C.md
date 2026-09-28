# ANALYSIS-C Handoff

- Task: ANALYSIS-C; requirements: R14/R16 selected-asset execution and evidence binding.
- Design: DESIGN-2026-09-23-v0.1 plus the task-specific assignment from the coordinator.
- Base: `46306d23b29eed81eea349c777d186bc00cf4fab`.
- Branch: `codex/analysis-c`.

## Changes

- Added `LiveSelectedAssetResearch`, a callable adapter from an approved materiality selection and explicit `instrument_id -> EquityResearchSpec` mapping to the existing `LiveDeepResearchRuntime` Phase 4/5 path.
- The adapter requires the request, Phase 4 evidence store, Phase 5 analyzer, and pinned run clock to agree. Missing resolved specs/data return partial results; mismatched run, clock, or spec identity returns unsupported. The adapter does not open personal.db or place orders.
- Selected asset report sections carry evidence and calculation references produced by Phase 4/5. `SelectedAssetResearchResult` can now carry explicit unsupported reasons so the fixed portfolio mode preserves fail-closed state.
- Added integration coverage for an end-to-end synthetic provider/web research bundle, report section inclusion, reference binding, missing data/spec, and wrong run/clock/spec identity.

## Verification

- `python -m unittest discover -s tests/integration -p test_analysis_c_selected_asset_research.py -v` — 5 passed.
- `python -m unittest discover -s tests/integration -p test_r14_portfolio_thesis_mode_bundles.py -v` — 3 passed.
- Tests used only synthetic run.db fixtures. The initial system Python lacked `tzdata`; it was installed into a temporary workspace-local `.testdeps` directory for the test run, then removed before commit.

## Limitations

- The host still supplies the approved materiality selector and resolved equity specs when constructing `portfolio_thesis_services`; automatic instrument resolution and personal.db access remain outside this adapter.
- Provider availability and real-source completeness were not live-tested. Unsupported asset classes need their own typed analysis service and remain outside this equity-only implementation.

## Coordinator review follow-up

- Removed the misleading status-as-price line. The adapter now renders a numeric valuation metric only when its evidence belongs to the selected instrument and the same-run Phase 5 calculation has the same subject/evidence lineage and an exactly matching persisted `result_json` metric (name, value, unit, status, and evidence IDs). An evidence or content mismatch hides the value and marks the section PARTIAL with a missing-input reason. DCF output is labeled as a conditional value under explicit assumptions and explicitly not a buy price.
- The adapter now rejects every mode except `PERSONAL_PORTFOLIO_ANALYSIS` before running research. `REPORT_REFRESH` remains outside this callback boundary.
- Added regression cases for valid persisted DCF display, a fabricated DCF metric that reuses another calculation ID, a nonexistent calculation ID, and invocation from another fixed mode.
- Verification rerun: selected-asset integration tests 9 passed; existing portfolio thesis bundle tests 3 passed; `git diff --check` clean.
- Verification environment: system `python` 3.14; `tzdata` installed temporarily to workspace-local `.testdeps` for Windows `zoneinfo`, then `.testdeps` removed. No dependency was added to the repository or committed.

## Independent review follow-up

- Fundamental and valuation `AnalysisResult` values are now rendered only when the full result (subject, analysis type, status, findings, risks, unknowns, metadata, and every metric field) matches the selected run.db calculation's `result_json`. Calculation input subject and complete evidence set must also match, and each evidence row must bind to the selected instrument.
- Added a regression that mutates findings and unknowns while reusing the original calculation ID; the altered text and value remain hidden and the section becomes PARTIAL. Persisted DCF labels use Korean descriptions in the user section; internal metric keys are not shown there.
- Verification: selected-asset tests 10 passed; portfolio thesis bundle tests 3 passed; `git diff --check` clean.
- Environment for this rerun remained system Python 3.14 with temporary workspace-local `.testdeps/tzdata`; `.testdeps` was removed afterward and is not staged.

## P1/P2 independent review follow-up

- Full saved-result equivalence now covers both fundamental and valuation results. Findings, risks, unknowns, metadata, status, and every metric field must match their calculation's `result_json`; subject and the complete evidence set must match the calculation inputs and same-instrument run.db rows. Any mismatch suppresses that analysis block and marks the section PARTIAL.
- The post-calculation LAST_VALID_CLOSE explanation is treated as a separate provenance note only when the selected quote, same-run market observation, and persisted freshness assessment agree on instrument, currency, value, unit, observation, session date, quote kind, calendar, and publication time. Exactly one derived note may be separated from the returned findings for the stored-result comparison; arbitrary additional findings remain rejected. Covered by a synthetic adapter regression and existing weekend E2E tests.
- User-facing metric names are Korean labels; internal metric keys are omitted from selected-asset body lines. DCF values retain the conditional-assumption / not-a-buy-price wording.
- Verification: selected-asset tests 11 passed; weekend-price E2E tests 4 passed; portfolio thesis bundle tests 3 passed; `git diff --check` clean.
- Verification used system Python 3.14 and workspace-local temporary `.testdeps/tzdata` because the runtime lacks Windows timezone data. Remove `.testdeps` before staging; do not commit it.
