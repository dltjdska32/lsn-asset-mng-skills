# investment-stack

`investment-stack` is a local-first, deterministic runtime for evidence-based
investment analysis. The canonical v1.3 architecture is frozen; implementation
is proceeding in bounded phases.

The current slice implements Phase 1 foundations, Phase 2 Storage Safety, and
Phase 3 Personal Ledger & Projection:

- exactly seven request modes;
- deterministic mode routing with an explicit mode override;
- one immutable fixed pipeline per mode;
- provider capability registration and ordered fallback;
- environment-only credential lookup;
- credential redaction for logs and diagnostics;
- exactly eight Codex skills with narrow responsibilities.
- OS-aware `personal.db` resolution outside the source repository;
- isolated `workspace/runs/<run-id>/run.db` evidence stores;
- centralized SQLite foreign-key, timeout, row, and transaction policy;
- independently versioned personal and run schemas;
- fail-closed personal startup and mutation guards;
- validated Online Backup API backups, retention, atomic migrations, and
  validated restore.
- typed transaction intents with deterministic confirmation policy;
- an append-only posted ledger with idempotency and exact Decimal storage;
- atomic posting, reversal, and reversal-plus-replacement correction bundles;
- monotonically increasing personal state versions;
- rebuildable position, cash, liability, and cashflow projections;
- weighted-average, user-provided, and unavailable cost-basis states;
- cash-only transfers, explicit FX and loan components, splits, and ticker
  aliases.

No server, generic DAG, outbox, research cache, web retrieval, market-price or
FX lookup, market valuation, tax-lot engine, or portfolio-performance engine is
introduced by this slice. Phase 3 records book state only; valuation and
research remain deferred.

## Run locally

The runtime has no third-party dependencies.

```powershell
$env:PYTHONPATH = "runtime"
python -m investment_stack route "FANUC 분석해" --json
python -m investment_stack plan PERSONAL_PORTFOLIO_ANALYSIS --json
python -m investment_stack check --project-root . --json
python -m unittest discover -s tests -v
```

For an editable install, run `python -m pip install -e .` in an isolated
environment.

## Safety boundary

The personal database defaults to the platform user-data directory:

- Windows: `%LOCALAPPDATA%\investment-stack\personal\personal.db`
- macOS: `~/Library/Application Support/investment-stack/personal/personal.db`
- Linux: `$XDG_DATA_HOME/investment-stack/personal/personal.db`, falling back
  to `~/.local/share`

Backups default to the same OS data root under `investment-stack/backups`.
Override paths are accepted only when absolute, validated, and outside a Git
repository. Every personal mutation entry point added in later phases must use
`PersonalDatabaseManager.guarded_write_transaction()` so path, schema, database
instance identity, opened-file identity, and writable state are checked before
the mutation transaction begins. Generic SQLite connection helpers are read-only;
writable connections are an internal manager-owned primitive.
Phase 3 posting is available only through `PersonalLedgerService`, which enters
the manager-owned guarded writer. Posted transactions and entries are protected
by append-only database triggers. Missing economic time, timezone, cash impact,
or entity resolution remains pending/confirmation-only and cannot affect the
confirmed projections. In-kind asset transfers are not supported. See
[ARCHITECTURE.md](ARCHITECTURE.md) for the frozen invariants.
