# investment-stack

`investment-stack` is a local-first, deterministic runtime for evidence-based
investment analysis. The canonical v1.3 architecture is frozen; implementation
is proceeding in bounded phases.

The current slice implements Phase 1 foundations:

- exactly seven request modes;
- deterministic mode routing with an explicit mode override;
- one immutable fixed pipeline per mode;
- provider capability registration and ordered fallback;
- environment-only credential lookup;
- credential redaction for logs and diagnostics;
- exactly eight Codex skills with narrow responsibilities.

No server, generic DAG, database, outbox, or research cache is introduced by
this slice. Personal ledger and run-evidence storage arrive in the storage and
ledger phases.

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

This phase does not mutate personal assets. Future posting code must enforce
the append-only ledger, confirmed `occurred_at`, cash-only transfer, always-
confirm bootstrap/repair transactions, and fail-closed storage rules recorded
in [ARCHITECTURE.md](ARCHITECTURE.md).

