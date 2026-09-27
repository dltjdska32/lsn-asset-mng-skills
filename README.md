# investment-stack

The eight skill definitions under `skills/` are authoritative. Codex repository-local discovery uses byte-identical mirrors under `.agents/skills/`; after changing a skill, run `py scripts/sync_agent_skills.py`. The architecture invariant rejects drift.

`investment-stack` is a local-first, deterministic runtime for evidence-based
investment analysis. The canonical v1.3 architecture is frozen; v1.3.1 hardens current-quote fallback and Korean user-facing status rendering; implementation
is proceeding in bounded phases.

Version labels have separate meanings: canonical architecture `v1.3`, the README's `v1.3.1` hardening description, and Python distribution/runtime `0.1.0` are not mapped release numbers. Contract envelopes (`0.2`), personal/run database schemas (latest migrations `3`/`2`), and config-file versions evolve independently. See [the distribution allowlist and version meanings](docs/workflow/deployment-allowlist.md).

The repository contains implementation slices across Phases 1–8. At independently reviewed code checkpoint `4e55a56`, the runtime has fixed-pipeline service bundles for the seven request modes and a host composition helper. [`analysis_modes.render_report`](runtime/investment_stack/execution/analysis_modes.py) now connects a five-part safe **WAIT** briefing to [`InvestmentReportBuilder`](runtime/investment_stack/reporting/builder.py) and stores a content-bound briefing reference. The configured-mode E2E pass verifies those service paths under injected dependencies. The default CLI still has no configured host services, and approved action policy, R08 chart/13F briefing evidence, and automatic sizing are not complete. A separate Codex final verification remains pending. See [implementation status](IMPLEMENTATION_STATUS.md) for evidence and limits. Implemented capabilities include:

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

The runtime declares `tzdata` and `truststore>=0.9.1`. The default `providers/http.py` transport uses a scoped `truststore` SSL context on Windows. Public Naver, Yahoo Finance, and Coinbase endpoints have been queried successfully in bounded integration checks. This is evidence for those requests at that time, not a guarantee of current availability or broad vendor coverage.

For source development, create a virtual environment and keep installation, checks, and tests on that interpreter:

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

To verify a non-editable wheel in a clean Windows venv, build from the source checkout using an existing build environment, then use the target venv's Python for wheel installation, dependency checks, timezone verification, and tests. This sequence uses no `py` launcher and does not install into or alter the build environment:

```powershell
# Build step (use an existing Python environment with the `build` package)
$BuildPython = 'C:\path\to\existing-build-venv\Scripts\python.exe'
& $BuildPython -m build --wheel --sdist --no-isolation

# Clean target environment; select the required Python executable explicitly
python -m venv .venv-wheel-check
$VenvPython = (Resolve-Path .\.venv-wheel-check\Scripts\python.exe).Path
$Wheel = (Resolve-Path .\dist\investment_stack-0.1.0-py3-none-any.whl).Path

# The same interpreter installs the wheel and runs all checks
& $VenvPython -m pip install $Wheel
& $VenvPython -m pip check
& $VenvPython -c "import sys, zoneinfo, investment_stack; print(sys.executable); print(investment_stack.__version__); zoneinfo.ZoneInfo('America/New_York'); zoneinfo.ZoneInfo('Asia/Seoul')"
& $VenvPython -m unittest discover -s tests -q
& $VenvPython scripts\sync_agent_skills.py --check
```

If dependency installation cannot use the existing package cache, stop and report the missing wheel/package before attempting a broad download. `pyproject.toml` permits Python 3.11 and later, but the Windows install verification in this task is specific to the interpreter version recorded in `IMPLEMENTATION_STATUS.md`; other versions need their own run.

## Market data and chart limits

`MarketQuoteProvider` validates source identity, price fields, currency, and source timestamps, then records every attempted source. The [default provider factory](runtime/investment_stack/providers/factory.py) wires the R01 eligibility evaluator and the [bounded pinned calendar snapshots](runtime/investment_stack/freshness/calendar.py) currently available for NASDAQ and KRX. It can qualify an eligible close as `LAST_VALID_CLOSE`; reports must preserve that dated-close label, since it is not an intraday quote. The snapshots cover only their explicitly listed September 2026 dates. There is no general dynamic exchange-calendar service or universal delay/age threshold. Other exchanges and dates without a matching pinned schedule fail closed for stale-close qualification.

The configured seven-mode composition is an embedding-host API, not automatic CLI wiring. The host must create and pin `run.db`, provide the personal-ledger service and typed personal-state loaders, inject credentials/providers and required callbacks, build the equity and portfolio/thesis bundles, then call `compose_seven_mode_services` ([composition code](runtime/investment_stack/execution/service_composition.py), [integration handoff](docs/workflow/handoffs/LUNA-R14-SEVEN-MODE-COMPOSITION-01.md)). `investment-stack execute` with the [default CLI](runtime/investment_stack/cli.py) has no configured handlers and returns `UNSUPPORTED`; it does not open personal data or discover credentials/providers automatically.

The default Phase 4 → Phase 5 equity path performs live provider retrieval when configured, persists selected evidence to `run.db`, and passes an eligible market observation into deterministic valuation. A verified integration pull on 2026-09-27 used Yahoo's 2026-09-25 close and Naver's 2026-09-23 close, both labeled `LAST_VALID_CLOSE`; neither is a live intraday price ([R01 integration handoff](docs/workflow/handoffs/R01-WEEKEND-PRICE-01.md)). This one-time public-source check does not establish continuous API availability or comprehensive external-vendor coverage. Investing.com direct page requests returned HTTP 403 in the recorded check; no live claim is made for that source. OpenDART requires an injected `OPENDART_API_KEY` for credentialed use.

The Naver daily-price endpoint returns a top-level list without an echoed ticker. Its response can be associated with an instrument only when the request uses the matching canonical Naver `/api/stock/{code}/price` route. The provider withholds a validated `BarSet` unless both a strict verification flag and an adjustment receipt are supplied, while preserving raw bars in diagnostics. The receipt is currently a caller-provided marker; corporate-action receipt authenticity is not checked by this adapter. Passing those raw bars manually as a `Sequence[Bar]` bypasses source provenance and is not safe for production analysis. Yahoo daily bars are parsed separately from current quotes. Technical indicator functions are deterministic calculations over completed bars; they do not authorize buy or sell actions, and the signal gate remains disabled until a verified policy registry exists.

Indicator conventions are explicit in the calculation API: SMA uses the trailing period of closes; EMA uses alpha `2 / (period + 1)` and an initial SMA seed; Wilder RSI seeds average gains/losses over `period` price changes and then uses Wilder smoothing; MACD is fast EMA minus slow EMA with the signal EMA seeded from the first signal-period MACD values; ATR uses true range and Wilder smoothing; relative volume compares the current bar with the preceding lookback volumes; volatility is sample standard deviation of log returns (`ddof=1`) with optional annualization. Trend, pivot, and breakout periods/thresholds are caller inputs. `Sequence[Bar]` supports deterministic calculations but does not carry a source-validation receipt, so production analysis must pass only a series validated by its caller.

**Skills and Packaging:**
The authoritative skill instructions are in the `skills/` source directory, while Codex repository-local discovery uses byte-identical mirrors under `.agents/skills/`. The `sync_agent_skills.py --check` command enforces exact byte equality between the source and the mirror. 

Wheel and source-distribution file paths are checked against the exact [distribution allowlist](docs/workflow/deployment-allowlist.md), including five explicitly named config inputs and all eight skill definitions/UI metadata files. The wheel places config inputs under `sys.prefix/config`, and skills beneath `sys.prefix/skills` and `sys.prefix/.agents/skills`. Config files are explicit inputs; the CLI does not automatically load them as global defaults. This verifies the installed discovery payload by path, not automatic Codex UI discovery from an arbitrary virtual-environment path. Repository-local Codex sessions use the workspace `.agents/skills/` mirror. The artifact allowlist excludes credential values, databases and sidecars, environment files, cache/run data, logs, virtual environments, Git metadata, bytecode, and key/certificate files by path. It does not scan source text for accidental secrets.

`OPENDART_API_KEY` is optional; the embedding host supplies an `EnvironmentCredentials` instance or uses the default environment loader. When the key is absent, the provider reports `MISSING_CREDENTIAL` and the research flow can continue with public/keyless or injected Web Research paths. The host also supplies any personal-state loader; no personal database is implicitly selected or opened by service composition.

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
