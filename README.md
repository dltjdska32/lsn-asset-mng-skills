# investment-stack

The eight skill definitions under `skills/` are authoritative. Codex repository-local discovery uses byte-identical mirrors under `.agents/skills/`; after changing a skill, run `py scripts/sync_agent_skills.py`. The architecture invariant rejects drift.

`investment-stack` is a local-first, deterministic runtime for evidence-based
investment analysis. The canonical v1.3 architecture is frozen; v1.3.1 hardens current-quote fallback and Korean user-facing status rendering; implementation
is proceeding in bounded phases.

The `v1.3` label identifies the architecture, while the Python distribution currently uses package version `0.1.0`; no release mapping between these labels is defined.

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

The declared runtime dependencies include `tzdata` (for Windows time zones) and `truststore>=0.9.1` (for Windows certificate-store TLS support). The current default transport in `providers/http.py` does not yet create a scoped `truststore` context, so the dependency declaration alone does not enable that behavior; the Windows public-provider path remains dependent on the A-owned transport integration.

For an isolated environment, use the following Windows PowerShell commands to create a virtual environment, activate it, install the package in editable mode, and run the validations using the same virtual environment interpreter:

```powershell
# 1. Create a virtual environment and pin the interpreter path for every later command
python -m venv .venv
$VenvPython = (Resolve-Path .\.venv\Scripts\python.exe).Path

# 2. Install the project and dependencies through that interpreter
& $VenvPython -m pip install -e .

# 3. Run validations through the same interpreter
& $VenvPython -m unittest discover -s tests -q

# 4. Verify byte-equality of the 8 skills
& $VenvPython scripts/sync_agent_skills.py --check
```

## Market data and chart limits

`MarketQuoteProvider` validates source identity, price fields, currency, and source timestamps, then records every attempted source. An `AVAILABLE` result means the source response parsed; it does not establish that the quote passes a freshness policy. Callers must provide the R01 eligibility evaluator before using a quote in current-price calculations. No universal delay or age threshold is configured here.

The Naver daily-price endpoint returns a top-level list without an echoed ticker. Its response can be associated with an instrument only when the request uses the matching canonical Naver `/api/stock/{code}/price` route. The provider withholds a validated `BarSet` unless both a strict verification flag and an adjustment receipt are supplied, while preserving raw bars in diagnostics. The receipt is currently a caller-provided marker; corporate-action receipt authenticity is not checked by this adapter. Passing those raw bars manually as a `Sequence[Bar]` bypasses source provenance and is not safe for production analysis. Yahoo daily bars are parsed separately from current quotes. Technical indicator functions are deterministic calculations over completed bars; they do not authorize buy or sell actions, and the signal gate remains disabled until a verified policy registry exists.

Indicator conventions are explicit in the calculation API: SMA uses the trailing period of closes; EMA uses alpha `2 / (period + 1)` and an initial SMA seed; Wilder RSI seeds average gains/losses over `period` price changes and then uses Wilder smoothing; MACD is fast EMA minus slow EMA with the signal EMA seeded from the first signal-period MACD values; ATR uses true range and Wilder smoothing; relative volume compares the current bar with the preceding lookback volumes; volatility is sample standard deviation of log returns (`ddof=1`) with optional annualization. Trend, pivot, and breakout periods/thresholds are caller inputs. `Sequence[Bar]` supports deterministic calculations but does not carry a source-validation receipt, so production analysis must pass only a series validated by its caller.

**Skills and Packaging:**
The authoritative skill instructions are in the `skills/` source directory, while Codex repository-local discovery uses byte-identical mirrors under `.agents/skills/`. The `sync_agent_skills.py --check` command enforces exact byte equality between the source and the mirror. 

When building for distribution (wheel/sdist), the artifact allowlists the 8 expected skills, specifically `SKILL.md` and `agents/openai.yaml` from both the source and mirror paths. It excludes known local database, log, environment, and run-data paths. The package tests inspect built artifacts; they do not prove that every possible sensitive file name is excluded. Repository-local Codex sessions discover the 8 skills in the Available skills list, while automatic UI discovery in other environments after wheel installation remains unverified.

`OPENDART_API_KEY` is optional; when absent the provider reports `MISSING_CREDENTIAL` and the research flow can continue with public/keyless or Web Research fallback paths.

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
