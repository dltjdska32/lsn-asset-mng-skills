# Phase 8 — Final Integration / Hardening Record

Status: **IMPLEMENTED — READY FOR FINAL PRE-COMMIT REVIEW**

Phase 8 is the final implementation-roadmap hardening layer agreed for this repository. It does **not** change the frozen canonical v1.3 architecture or add a new Request Mode, Skill, server, MCP layer, or generic DAG. The canonical `ARCHITECTURE.md` implementation-phase numbering ends at its Acceptance phase; this record names the repository handoff/final-integration step as Phase 8 so the implementation roadmap remains unambiguous.

## Final integration coverage

- All seven Request Modes route deterministically and retain exactly one fixed pipeline each.
- Hypothetical portfolio/trade scenarios remain non-posting; only `ASSET_UPDATE` contains the posting-decision step.
- A full-stack integration path now verifies Provider → Freshness/Evidence → Asset Analysis → Calculation Lineage → Report/Review on one pinned run.
- Phase 5 persisted asset-analysis calculations now propagate their `calculation_id` into report-section lineage automatically.
- The integration path confirms research, analysis, and reporting do not mutate `personal.db` and preserve the pinned personal `state_version`.
- Same normalized inputs produce the same semantic financial calculation results across independent runs; run-local lineage identifiers may differ.
- Unexpected provider exceptions fail soft and can fall through to a healthy provider.
- OpenDART credential values are not persisted into `run.db` when the transport fails, even when a transport exception contains the credential-bearing URL.
- Optional independent-reviewer failure remains non-fatal and produces a deterministic partial finding.
- Runtime invariant checks now reject repo-local secret/runtime artifacts such as non-example `.env` files, SQLite databases/sidecars, backup DB artifacts, and secret files.
- Existing Phase 2–7 regression coverage remains the release gate for backup/restore, append-only ledger safety, latest-as-of cutoffs, source conflicts, stale/current-value protection, materiality-before-deep-research, alternative-asset valuation boundaries, partial reports, and run/personal isolation.

## Phase 8 files

- `runtime/investment_stack/invariants.py`
- `runtime/investment_stack/asset_analysis.py`
- `runtime/investment_stack/reporting/runtime.py`
- `tests/acceptance/test_phase8_request_modes.py`
- `tests/unit/test_phase8_determinism.py`
- `tests/integration/test_phase8_full_stack.py`
- `tests/adversarial/test_phase8_hardening.py`

## Release gate

Run only after targeted Phase 8 tests pass:

```bash
PYTHONPATH=runtime python -m compileall -q runtime tests
PYTHONPATH=runtime python -m unittest discover -s tests -v
PYTHONPATH=runtime python -m investment_stack check --project-root . --json
python -m build --wheel --outdir <isolated-wheel-dir>
# install the wheel into a clean venv and run the full suite again

git diff --check
```

The final user Git working tree must also pass its Git-specific ignore checks. Deliverable archives must exclude `.git`, runtime DBs/sidecars, credentials, build outputs, and temporary test state.

## Validation result

- Phase 8 focused tests: **10/10 PASS**
- Full source unittest: **272/272 PASS**, 2 platform-conditional skips
- Clean installed-wheel unittest: **272/272 PASS**, same 2 platform-conditional skips
- Architecture invariants: **9/9 PASS**
- Phase 8 delta whitespace check against the Phase 7 archive: **PASS**
- Final self-review: **Critical 0 / High 0**

The two skips are the existing platform-conditional Windows path/reparse tests. The final user Git working tree still needs its own `git diff --check`/pre-commit review because the handoff ZIP intentionally excludes `.git`.

## Final boundary

After Phase 8 there is no additional v1.3 MVP implementation phase in this repository roadmap. AWS/MCP/web/mobile connectivity remains a post-v1.3 extension and is intentionally not introduced here.
# Portfolio reconciliation and materiality configuration

Portfolio totals derived from screenshots or broker exports must be reconciled
before they become a denominator. Reported stock and cash group totals are
compared with their components using `config/reconciliation.yaml`. Cash or FX
components are never added on top of a cash group total. When reconciliation is
`UNRESOLVED`, absolute observed components may be reported, but total-based
weights and scenario percentages remain `PARTIAL`.

Materiality thresholds are explicit in `config/materiality.yaml` and loaded
strictly. Missing, unknown, or invalid values fail closed; the runtime has no
silent hard-coded fallback. The configured version is persisted with every
materiality decision rationale.
