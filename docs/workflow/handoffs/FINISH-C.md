# FINISH-C handoff

- Branch/base: `codex/finish-c`, assigned base `1f38fe9`.
- Scope: R17 Korean report readability, R10–R11 briefing presentation/persistence, without changing decision generation or analysis mode execution.

## Changes

- Replaced English provider/freshness/conflict and review-code messages in user-facing report sections with concise Korean explanations. Kept report status, confidence, analysis as-of, source timestamps, and non-fresh market status visible.
- Moved evidence and calculation identifiers into a dedicated `상세 근거` section.
- Kept report identity and immutable briefing persistence with the mode runtime: `analysis_modes.py` already stores `final_briefing` and a manifest-derived `run-report:...sha256:...` reference. The report builder does not issue a competing random `report_ref` or duplicate briefing section. Its established `section:<name>` persistence remains compatible with the manifest collector.
- Added tests for a partial unresolved conflict report, identifier suppression from the main body, and leaving final report identity/briefing storage to the mode runtime.

## Validation

- Ran the report, fixed-mode, refresh, and integration regressions from this worktree using the root `.venv`: 36 passed.
- Tests use temporary synthetic run databases. No personal database, live data, or order path was used.
- Broader suite and live-source checks were not run.

## Remaining

- Integration with the assigned B/C and decision-layer work remains for the coordinator; this worktree intentionally does not modify `decisions/briefing.py` or `execution/analysis_modes.py`.
- Integration review verified that final `report_ref` identity and immutable `final_briefing` storage are owned by the mode runtime, while the generic builder retains its section persistence contract.
- Initial full `unittest discover -s tests -v` run before the reporting regression fixes executed 604 tests and found five failures: three report wording compatibility checks (STALE label, MISSING_CREDENTIAL label, and `계산 근거:` heading) and two packaging checks because this worktree had no built wheel/sdist. Fixed the three reporting regressions while retaining Korean explanations and detailed-only calculation IDs. The two packaging checks require build artifacts and are outside reporting ownership.
- Re-ran the affected acceptance, reporting, phase 8, equity/portfolio mode integration, and unit modules: 35 passed. Full-suite output captured in `FINISH-C-suite.log` for coordinator inspection.
- Follow-up review rendering now gives distinct Korean summaries for known material finding codes. Unknown codes retain severity/code/original text under 상세 근거; they are not emitted in the main summary. Added a synthetic unknown-code regression that verifies raw details remain available while internal IDs do not appear before the detailed section.
- Report sections now use content-addressed IDs (`section:<name>:<sha256>`) and `InvestmentReport.persisted_section_refs` returns the exact current-build references as `(section_name, section_id, content_reference)` tuples. Identical content reuses its section ID; changed content creates a new row and preserves the earlier row. Mode consumers must filter manifest sections by these IDs and verify name/reference before computing `report_ref`.
- `section_from_analysis_result` now labels risk and unavailable inputs in Korean (`위험:`, `확인 불가:`).
- Latest full suite after these changes: 605 tests, 2 packaging setup failures (worktree has no built wheel/sdist), 1 skipped. All other tests passed. The focused report/mode/refresh regression set ran 47 tests and passed.
- The coordinator will wire `analysis_modes.py` to consume `report.persisted_section_refs`, validate exact current-build section IDs/names/content references/status, then build the immutable report manifest and append the mode-owned `final_briefing` ref. C did not edit that A/root-owned file. Root will rebuild wheel/sdist and run the final full suite after integration.
