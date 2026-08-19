# investment-stack

The eight skill definitions under `skills/` are authoritative. Codex repository-local discovery uses byte-identical mirrors under `.agents/skills/`; after changing a skill, run `py scripts/sync_agent_skills.py`. The architecture invariant rejects drift.

`investment-stack` is a local-first, deterministic runtime for evidence-based
investment analysis. The canonical v1.3 architecture is frozen; implementation
is proceeding in bounded phases.

The current slice implements Phase 1 foundations, Phase 2 Storage Safety,
Phase 3 Personal Ledger & Projection, Phase 4 Evidence & Research, Phase 5 Asset Analysis, Phase 6 Report & Review, Phase 7 Acceptance, and the Phase 8 final integration/hardening handoff:

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
  aliases;
- free-first provider adapters for OpenDART, SEC Company Facts, and timestamped
  Kraken public trades;
- injected Web Research fallback for latest/current data and latest relevant
  news without a separate Skill, Agent, or database;
- immutable `analysis_as_of` / timezone pinning, freshness assessment, provider
  states, source conflicts, observation selection, and calculation lineage in
  `run.db`;
- explicit partial/unavailable behavior when credentials, timestamps, or
  provider coverage are missing;
- deterministic equity fundamentals and asset-appropriate equity valuation with
  explicit assumptions only;
- ETF/fund NAV, cost, concentration, tracking, liquidity, and dated look-through
  analysis;
- Bitcoin, gold, and silver analysis with price/risk and asset-specific context,
  never corporate DCF/EPS valuation;
- a materiality gate that precedes portfolio deep research, plus cross-asset
  allocation and aligned historical risk/contribution calculations;
- partial-aware as-of reports with explicit Analysis/Market/Financial/Macro/Portfolio
  data timestamps, confidence, unknowns, evidence identifiers, and calculation lineage;
- deterministic conditional review for materiality, low confidence, conflicts,
  stale/unknown critical inputs, unsupported requests/models, material news/rumor,
  and strategy-impact triggers; an independent reviewer callback remains optional.

- final MVP acceptance regression spanning unit/integration/adversarial seams;
- executable frozen-architecture invariants plus validated backup/restore drill;
- cross-phase checks that research/report flows cannot mutate `personal.db` and future observations cannot become current-value claims.
- final fixed-pipeline coverage for all seven Request Modes and explicit non-posting scenario boundaries;
- end-to-end Provider → Evidence → Asset Analysis → Calculation Lineage → Report/Review validation;
- live selected-equity bridge from Provider/Web Research through financial observations into fundamental/valuation calculations, with a structured Codex web-hit bundle adapter;
- release hardening that rejects repo-local runtime databases, SQLite sidecars, non-example `.env` files, and secret artifacts.

No server, generic DAG, outbox, research cache, advanced tax-lot engine,
portfolio-performance attribution engine, MCP layer, or mandatory independent reviewer
is introduced by this slice. Web Research remains an adapter boundary and reports are
run-local derived outputs rather than a personal Source of Truth.

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
environment. `OPENDART_API_KEY` is optional; when absent the provider reports
`MISSING_CREDENTIAL` and the research flow can continue with public/keyless or
Web Research fallback paths.

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


Current implementation handoff: [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md).
Phase 7 acceptance record: [docs/PHASE7_ACCEPTANCE.md](docs/PHASE7_ACCEPTANCE.md).
Final hardening record: [docs/PHASE8_FINAL_HARDENING.md](docs/PHASE8_FINAL_HARDENING.md).

Live deep-research bridge: [docs/LIVE_DEEP_RESEARCH.md](docs/LIVE_DEEP_RESEARCH.md).
