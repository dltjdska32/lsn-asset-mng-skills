# Automatic capital ranking implementation — 2026-10-05

Implemented in the v7 remediation workspace. No GitHub push or main merge was performed for this change.

- The existing portfolio allocation stage derives CapitalCompetitionPolicyInputs from selected same-run EQUITY_FUNDAMENTAL/EQUITY_VALUATION or FUND calculations and research evidence. It processes every held identity without a fixed six-asset limit. Explicit caller overrides retain the original approval checks; automatic provenance never fabricates approvals.
- Research score observations require an assessment rationale. Numeric fallback uses documented within-cohort midranks for revenue growth, earnings yield, ROE, industry growth and inverse leverage. Business-quality/industry evidence is mandatory; absent or conflicting inputs stay unranked. Relative scores do not imply absolute moat quality or assign reduction/concentration categories.
- Research ranking is independent of missing forecast scenarios. Missing CAGR/rotation inputs keep the report partial, and no forecast assumptions are invented.
- Source calculation IDs and normalization peer evidence/cohort are persisted. Current-price evidence remains independently verified. Observed/publication timestamps are cutoff-bound; legitimate later retrieval of already-published observations is permitted.
- Removed Policy B's 8% position cap, its concentration-only stop and 10%-to-8% reduction trigger, including report wording. Its existing cash floor and evidenced valuation/thesis checks remain. Without a verified allocation budget, transaction quantities remain withheld.
- Updated skill instructions/policy references and synchronized the eight .agents skill mirrors.

Validation:
- Real seven-stage PERSONAL_PORTFOLIO_ANALYSIS execution using synthetic selected research and actual Phase5 fundamental/valuation calculations: six and eight holdings all ranked without capital_competition_policy_inputs injection. Stale/unselected evidence withheld. No live personal portfolio or external provider run was performed.
- Final related regression run: 72 tests passed (workspace/capital-ranking-targeted.log).
- Broader regression run: 918 tests, one skipped, four failures against legacy allocation-budget expectations. Those expectations/fixtures were updated and all four failing cases passed in the final related regression. The entire 918-test run was not repeated after the final fixes.
- Verified wheel/sdist build: 158 runtime payload files match source (workspace/capital-ranking-build.log).
- Skill synchronization --check passed.
