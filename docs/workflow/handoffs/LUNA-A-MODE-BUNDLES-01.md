# LUNA-A-MODE-BUNDLES-01 handoff

- Assignment: concrete default handler bundles for `SINGLE_ASSET_ANALYSIS` and `ASSET_COMPARISON`; REQ R14/R16, design §7.
- Start commit: `ec92ad702ba583e76703c5654d9474494c83898b`.
- Branch: `codex/luna-a-mode-bundles-01` in the new `luna-a-mode-bundles-01` worktree.
- Implementation commit: `13a0e64d2e109a50a50648ce61cb0baaca6f120a` (`Wire concrete equity analysis mode bundles`).
- Owned changes: `runtime/investment_stack/execution/analysis_modes.py`, the export in `execution/__init__.py`, and `tests/integration/test_r14_equity_mode_bundles.py`.

## Implementation

`equity_analysis_services(...)` returns a real `RuntimeServices` bundle for the two requested equity modes. It binds the mode's existing fixed pipeline steps to `LiveDeepResearchRuntime` (Phase4 research/evidence + Phase5 analyzers), `ConditionalReviewEngine`, and the Phase6 partial-aware report builder. The injected Phase4/5/6 components must share one run DB and pinned analysis clock, and each request mode must match run metadata. No personal DB writer is present.

Resolved `EquityResearchSpec` input is mandatory; single-asset requests require exactly one unique spec and comparisons require at least two. Missing provider configuration with no usable evidence returns `UNSUPPORTED`. Insufficient analysis data remains `PARTIAL` and still produces a report when Phase6 inputs permit.

Each report section is persisted through the existing builder. The bundle reads back section content references, creates a stable SHA-256 report manifest reference, and persists that reference plus section refs in run-local task state. The dispatcher result returns the same report ref alongside actual evidence and calculation refs.

Comparison execution persists a pairwise matrix for financial period, currency, and `BusinessType`. It calculates compatible normalized financial metrics and available Phase5 valuation ratios side by side with deltas against the first requested asset only when all compatibility dimensions match. It never emits a total ranking. Incompatible or missing period/currency/type and incomplete asset analyses yield `PARTIAL`; incompatible dimensions suppress comparative metrics.

## Actual mode runs

- `SINGLE_ASSET_ANALYSIS`: ran the fixed four-step pipeline with one synthetic FANUC `EquityResearchSpec`. Phase4 selected timestamped synthetic quote and financial evidence; Phase5 persisted fundamental and valuation calculations; Phase6 persisted fundamental, valuation, review, and data-quality report sections. The run returned evidence refs, two calculation refs, and a `run-report:<run_id>:sha256:...` ref whose manifest is stored in `task_states`. Final status was `PARTIAL`, as expected with synthetic incomplete fundamentals and unconfigured credential-backed providers.
- `ASSET_COMPARISON`: ran the fixed five-step pipeline with two synthetic equity specs. Evidence and per-asset Phase5 calculations were persisted, plus an `asset_comparison` calculation and report section. Same-period/same-currency/same-business-type matrix was dimension-compatible; asset analyses themselves remained partial. Final status was `PARTIAL`; `ranking_emitted=false` in calculation and report metadata.
- Comparison counterexamples: different financial periods, currencies, and business types each returned `PARTIAL`, emitted no comparative metric rows and no total ranking. A one-asset comparison returned `UNSUPPORTED` before collecting evidence. An empty provider bundle returned `UNSUPPORTED` rather than claiming a data result.
- Synthetic fixtures only (`*.test` source URLs); no live network/source validation, personal DB, credentials, order, or real investment values were used.

## Verification

Interpreter: `C:\Users\lsn\lsn-asset-mng-skills\.venv\Scripts\python.exe`, `PYTHONPATH=runtime`.

- `python -m unittest tests.integration.test_r14_equity_mode_bundles -v` — 5 passed.
- `python -m unittest discover -s tests/unit` — 320 passed.
- `python -m unittest discover -s tests/acceptance` — 46 passed.
- `python -m unittest discover -s tests/integration` — 97 passed (includes the 5 new mode-bundle tests).
- `python -m unittest discover -s tests/adversarial` — 44 passed.
- `git diff --check` — passed.
- `compileall` was attempted but could not create `__pycache__` in the managed worktree (Windows `PermissionError`); modules imported and executed in the passing suites.

## Boundaries and follow-up

- This implements only `SINGLE_ASSET_ANALYSIS` and `ASSET_COMPARISON`. `PERSONAL_PORTFOLIO_ANALYSIS`, `PORTFOLIO_SCENARIO`, `THESIS_REVIEW`, and `REPORT_REFRESH` remain without concrete mode bundles. No completion claim is made for them.
- Requires a host to construct and inject Phase4/5/6 runtimes, a run DB, and resolved specs; no provider credentials are embedded. Live access and native provider availability were not verified.
- The user's 2026-09-27 Sunday/holiday close requirement remains pending B's official-calendar `LAST_VALID_CLOSE` implementation. After B's source change is integrated, A follow-up must connect one purpose-aware CURRENT_PRICE eligibility policy through `providers/factory.py`, `providers/execution.py`, `research.py`/`evidence/research.py`, `deep_research.py::_current_price`, and relevant web-research fallback. Those files were not changed in this bundle slice. Until that follow-up, `providers/execution.py` and `_current_price` accept only `FRESH`; a B-produced `LAST_VALID_CLOSE` cannot reach calculations. Avoid editing B's calendar/quote-schedule files or C-owned files before their handoff/ownership is released.
- No push, merge, live-provider test, or independent final verification was performed.

Implementation commit SHA and final handoff commit SHA are recorded in Git after commit; this handoff records the requested run outcomes and pending dependencies.
