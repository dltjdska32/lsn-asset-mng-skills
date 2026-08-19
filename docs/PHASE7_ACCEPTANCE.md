# Phase 7 — MVP Acceptance Record

Status: **IMPLEMENTED — READY FOR INDEPENDENT PRE-COMMIT REVIEW**

Canonical scope: `ARCHITECTURE.md` v1.3, Phase 7 (`Unit/Integration/Adversarial Regression`, `Backup/Restore Drill`, `Architecture Invariant` validation).

## Acceptance coverage

- Frozen structure: exactly 8 Skills, exactly 7 Request Modes, one fixed pipeline per mode.
- Forbidden architecture: no generic DAG, server/API/scheduler/microservice/MCP runtime layer, outbox, or `research-cache.db`.
- Personal/run separation and external personal-data path remain covered by Phase 2 storage tests.
- Ledger acceptance covers append-only transactions/entries, state version, cash-only transfer, unsupported in-kind transfer, event-time confirmation, always-confirm bootstrap/adjustment transactions, and correction as atomic REVERSAL + complete replacement.
- Research acceptance covers latest-as-of cutoff, provider fallback/partial behavior, conflict-without-averaging, Web Research/news staying inside the existing adapter/evidence boundary, and research isolation from `personal.db`.
- Asset acceptance covers Equity/Fund/Alternative routing, materiality before deep research, and corporate valuation prohibition for Bitcoin/gold/silver paths.
- Report/review acceptance covers partial/unknown output, as-of semantics, stale/current-value protection, and optional independent review.
- Backup/restore drill creates a validated online backup, mutates the live ledger, restores the candidate, revalidates the active DB, and confirms ledger/projection/state-version recovery.
- Cross-phase failure tests verify that research/report flows do not mutate the personal Source of Truth and that future market data cannot become a current-value claim.

## Phase 7 files

- `runtime/investment_stack/invariants.py`
- `tests/acceptance/test_phase7_mvp_acceptance.py`
- `tests/integration/test_phase7_backup_restore_drill.py`
- `tests/adversarial/test_phase7_cross_phase_failures.py`

## Validation baseline

Validation host: Linux.

- Phase 7 focused tests: **16/16 PASS**
- Full source unittest: **262/262 PASS**, 2 platform-conditional skips
- Installed-wheel unittest: **262/262 PASS**, same 2 platform-conditional skips
- Architecture invariant command: **PASS**
- `git diff --check`: **PASS**
- Runtime DB/build artifacts are excluded from the deliverable ZIP.

The two skips are existing platform-conditional Windows path/reparse tests and are not Phase 7 failures.

## Commit gate

Phase 7 implementation is complete, but this record does not substitute for an independent pre-commit review on the user's real Git working tree. Commit only after that review reports no Critical/High blockers.
