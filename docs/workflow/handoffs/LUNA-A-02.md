# LUNA-A-02 — A domain transfer handoff

## Assignment and checkpoint

- Assignment: A-domain continuation from `GPT6-LUNA-TRANSFER-02.md`.
- Design: `DESIGN-2026-09-23-v0.1`; requirements: `REQ-2026-09-23-v1`.
- Starting checkpoint: `codex/gemini31-a` / `1d5d8fb0a5e63e95d0fbff1a29e800312a8208f3`.
- Isolated branch: `codex/luna-a-transfer-02`.
- Latest implementation HEAD: `6b9689bbc033d4bbe550c5c515b14a822b947aa8`; handoff update HEAD: `3d38323aba4ff46a3a51899b68422f57d8ab0928`.
- Commits: `b0548e4` (Evidence tests/Decimal persistence), `c2a480d` (selected finance consumption, DCF, HTTP), `6b9689b` (DCF validation and scenario coverage).

## Changes

- Repaired the Evidence WIP tests for the current `RunDatabaseManager(workspace_root, run_id)` lifecycle, current `ProviderResult` constructor, and run database table/API names. Persisted exact Decimal text in financial observation metadata because SQLite `NUMERIC` affinity converts Decimal strings to floating-point values in the numeric projection.
- Added selected per-metric observations to `SelectedEvidence`. `deep_research` now normalizes only those selected facts and chooses one latest compatible period/reporting-basis group. Flow metrics with different start dates are excluded from a shared period group. Invalid/duplicate/non-finite/non-positive explicit unit scales are rejected; share-count and per-share metrics require share units, and total monetary metrics reject per-share units.
- Added explicit `DcfScenario` inputs and assumption evidence references, two-axis caller-provided sensitivity points, formulas containing the used assumptions, and strict Decimal/domain validation. The bridge accepts scenarios only when their evidence references belong to selected evidence for the instrument in this run. Missing any of `conservative`, `base`, or `optimistic` leaves the valuation `PARTIAL`.
- JSON fractional tokens now decode as `Decimal`. Windows HTTP requests use a per-request truststore `SSLContext` when `truststore` is installed, with Python's verified default SSL context as fallback. No global SSL monkey-patch is used.
- Updated the obsolete empty-SEC-facts test: an empty supported-fact set is `UNAVAILABLE`, consistent with R04's rule against treating an empty calculation set as successful retrieval.

## Verification performed

Using `C:/Users/lsn/lsn-asset-mng-skills/.venv/Scripts/python.exe` and this worktree's `runtime` via `PYTHONPATH=runtime`:

- Initial Evidence tests: reproduced the missing `run_id` errors; after the corrections, R04 Decimal persistence and R05 ineligible-price retention/reselection passed.
- Targeted financial, DCF, transport/TLS, SEC parser, structured fallback, and deep-research integration tests: **33 passed**.
- Full worktree suite: `python -m unittest discover -s tests` — **416 passed**.
- `git diff --check` passed before the final commits.
- Live default-provider transport check using the Windows `.venv` and actual `urllib_transport`/`fetch_json` returned valid Naver quote, Yahoo chart, and Coinbase ticker JSON. A second check using the same scoped `truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)` observed HTTP **200** from all three endpoints, with `verify_mode == CERT_REQUIRED` and `check_hostname == True`. The Yahoo JSON preserved 120 fractional numeric tokens as `Decimal`.
- Tests use temporary synthetic run databases only. No personal database or credentials were used.

## Not run / remaining work

- The deterministic TLS unit test mocks truststore and the opener; the additional live verification above was a one-time local check, not a repeatable network test. `truststore` is not currently listed in `pyproject.toml` at the B checkpoint inspected, so installed distributions without it take the verified `ssl.create_default_context()` fallback. Adding/packaging truststore is B-owned and was not changed here.
- No test of a production/default service wiring or CLI `execute` was made. R14's actual seven-mode dispatcher and R16 cross-requirement integration remain for a separate assignment, per the coordinator's follow-up.
- The new period grouping is fixture-verified but not validated against a broad real-world cross-company filing corpus. Financial periods with missing or ambiguous basis metadata may be excluded or grouped conservatively.
- DCF scenario assumptions require evidence IDs from selected evidence for the same instrument/run. No automatic market-derived assumptions or valuation policy defaults are supplied; callers must provide the three named scenarios and sensitivity points.
- The full test count reflects the `1d5d8fb` source checkpoint plus this A-domain worktree; it does not replace verification of the coordinator's newer integrated HEAD.
