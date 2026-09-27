# LUNA-A-R14-01 handoff

- Assignment: `LUNA-A-R14-01`; requirements `REQ-2026-09-23-v1` R14/R16; design `DESIGN-2026-09-23-v0.1` §7–8.
- Base commit: `83dfb2779f5afa2932f0f196adbe80f13ac89534`.
- Branch: `codex/luna-a-r14`.
- Implementation commit: `0eba86dfe8c479e0d1182dc970494b3bead99b67` (`Implement fail-closed fixed mode dispatcher`).

## Delivered

- Added a typed fixed-mode dispatcher which executes only `FixedPipelinePlanner` steps, requires an explicitly registered handler per step, records status/reference-only task state when a run DB is supplied, and reports missing handlers as `UNSUPPORTED`.
- Added strict `ASSET_UPDATE` handlers using the existing personal ledger: typed intent extraction, event/time validation, explicit confirmation/idempotency checks, ledger posting, and projection/version verification. Only the posting step can return a mutation receipt. An identical retry returns `ALREADY_POSTED` without another ledger version; draft/unconfirmed input does not post.
- Added routing intent classification so completed historical transaction facts, buy questions, negations, hypotheticals, and order commands are distinguished. A mode hint cannot convert a question, negation, hypothetical, or analysis into `ASSET_UPDATE`.
- Added preflight and runtime guards against report-refresh replay, refresh recursion, missing refresh lineage, scenario/refresh mutation receipts, and success without a report reference.
- Fixed composite sequencing: an unconfirmed optional update is marked excluded from analysis; a required update waits for confirmation; a post-commit projection/version/logging failure preserves its posted receipt and blocks downstream analysis.
- Added `execute` CLI surface with JSON stdin and injectable `RuntimeServices`. With no host services configured, execution fails closed as unsupported.
- Portfolio analysis now reports selected assets whose deep analyzer callback is missing rather than silently omitting them.

## Mode-by-mode execution evidence and status

- `ASSET_UPDATE`: actual vertical slice exercised against a temporary synthetic personal DB through `asset_update_services`; confirmed posting, identical idempotent retry, unchanged version on unconfirmed input, and projection/version checks passed.
- `PERSONAL_PORTFOLIO_ANALYSIS`, `SINGLE_ASSET_ANALYSIS`, `ASSET_COMPARISON`, `PORTFOLIO_SCENARIO`, `THESIS_REVIEW`, `REPORT_REFRESH`: dispatcher step order, partial-report contract, and mutation guards are covered with synthetic handlers. The runtime does not yet provide concrete mode handler bundles for these six modes; absent explicit handlers they correctly return `UNSUPPORTED`. The synthetic handler tests are dispatcher contract tests, not evidence that these six product pipelines are implemented.
- `PORTFOLIO_SCENARIO` and `REPORT_REFRESH`: non-posting was tested by injecting deliberately malicious synthetic handlers; dispatcher rejects a mutation receipt. No live scenario or refresh report was generated.
- Composite `UPDATE_THEN_ANALYSIS`: synthetic handler tests cover confirmation gating, excluding pending updates, and blocking analysis after a posted update whose later projection/log operation fails. The real-ledger test covers its ASSET_UPDATE subflow; a product-level analysis bundle is not connected yet.

## Verification

Interpreter: `C:\Users\lsn\lsn-asset-mng-skills\.venv\Scripts\python.exe`, `PYTHONPATH=runtime`.

- `python -m unittest discover -s tests/unit` — 313 passed.
- `python -m unittest discover -s tests/acceptance` — 46 passed.
- `python -m unittest discover -s tests/integration` — 92 passed.
- `python -m unittest discover -s tests/adversarial` — 44 passed.
- Focused dispatcher/router suite — 18 passed at final focused run before suite aggregation; all its tests are included in the 313 unit tests.
- `git diff --check` — passed before implementation commit.
- Whole-root `python -m unittest discover -s tests` — 508 run, one skipped, one failure: `tests/test_packaging.py::TestPackaging::test_built_artifacts_contain_skills` requires a prebuilt `dist/` directory, which was absent. No package build was run.

No provider-backed/live test was run. All personal DB verification used a temporary synthetic database. No remote push, deployment, live account access, or order execution occurred.

## Remaining work

Wire concrete service bundles for the six analysis/report modes and add per-mode vertical tests that produce real run-local report/result artifacts. Then independently verify the integrated commit as specified by the coordinator workflow. Current branch is clean after the implementation commit; no merge or push was performed.
