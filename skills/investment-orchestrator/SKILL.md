---
name: investment-orchestrator
description: Route investment requests to one of the seven v1.3 request modes and coordinate its predefined runtime pipeline. Use for asset updates, personal portfolio analysis, single-asset analysis, asset comparisons, portfolio scenarios, thesis reviews, and report refreshes.
---

# Investment Orchestrator

Apply [the v7 capital allocation policy](references/capital-allocation-policy.md)
inside existing calculation, review and report stages. Keep all eight skills and
seven fixed pipelines. Capital competition and ranking are existing-stage
capabilities, never a new skill or a substitute for executed research/review.

1. Classify the request as exactly one supported request mode. Prefer an explicit user mode when supplied.
2. Call the runtime router and fixed pipeline planner. Do not invent steps, a DAG, or a new mode.
3. For asset updates, extract only a typed intent candidate. Never write SQL or declare a transaction posted yourself.
4. Require the runtime to validate `occurred_at`, timezone, ambiguity, impact, idempotency, and storage health.
5. Treat quantity-only or date-ambiguous transactions as draft or confirmation-required.
6. Never reinterpret an unsupported in-kind transfer as a sale, purchase, or adjustment.
7. Delegate qualitative analysis and reporting to the relevant skills after runtime validation.
8. Preserve explicit unknowns and partial availability in the final result.

Run `py -m investment_stack route "<request>" --mode <MODE> --json` to resolve the mode and fixed steps through the Python runtime. Then execute those steps through the matching `investment_stack` runtime modules, using a fresh run ID and an isolated `workspace/runs/<run-id>/run.db`. Never reuse a prior run database or a snapshot-specific replay script for a new request.

For `PERSONAL_PORTFOLIO_ANALYSIS`, require this exact pipeline:

1. `pin_personal_state`
2. `lightweight_all_assets`
3. `apply_materiality_gate`
4. `deep_research_selected_assets`
5. `calculate_allocation_and_risk`
6. `conditional_review`
7. `render_partial_aware_report`

Use `RunDatabaseManager` for the isolated evidence store, `Phase5AssetAnalysisRuntime` for materiality/allocation/risk, and `Phase6ReportReviewRuntime` for conditional review and partial-aware reporting. Persist each executed step with `record_task_state`. Do not create a run until the user asks to execute analysis.

## Live deep-research execution rule

For `DEEP_RESEARCH_SELECTED_ASSETS` and `DEEP_RESEARCH_REQUESTED_ASSETS`, do not substitute a manual Codex/web summary for runtime execution. Use `Phase4ResearchRuntime` + `EvidenceResearchStore` for retrieval/evidence and `LiveDeepResearchRuntime` to bridge selected equities into `Phase5AssetAnalysisRuntime`. If Codex performs the external web lookup, serialize only structured hits (source identity, timestamp, value/unit/currency, source kind, metric/period metadata) through `WebResearchBundleBackend`; then let the runtime enforce cutoff/freshness, selection, normalization, calculation lineage, and partial/unavailable behavior. For every numeric financial fact, preserve the source unit scale explicitly (for example `JPY million`, `KRW billion`, `million shares`, `JPY/share`); never strip a million/billion/share scale and never infer one from magnitude.

A selected equity must attempt, in order: timestamped current-price research, latest eligible official/regulatory financial research, deterministic fundamental analysis, valuation when validated inputs permit, and optional latest relevant news. Provider or credential failure is persisted and falls through to the existing Web Research adapter. Screenshot prices remain portfolio-snapshot evidence and must never be promoted to authoritative current-price observations.

When external search is performed by Codex, do not finish with the prose findings. Create a structured research bundle and feed it to `WebResearchBundleBackend` (or use `scripts/run_live_equity_research.py` for a single-equity verification) so provider states, financial observations, evidence selection, and calculation IDs are actually persisted.


## Configured personal portfolio execution

Use `scripts/capture_market_data.py --personal-db <materialized-authoritative-personal.db> --output-dir <run-input-directory>` to capture actual public HTTP payloads before setting the analysis cutoff. Capture failures are explicit. Preserve payload SHA-256, original retrieval time, listing identity, quote time, session, delay and source metadata. Do not use a capture manifest as proof of an eligible quote: `MarketQuoteProvider` still enforces identity, currency, timestamps and the pinned session calendar.

Execute `scripts/run_personal_portfolio.py --personal-db <materialized-authoritative-personal.db> --run-workspace <isolated-workspace> --live-providers --market-captures <run-input-directory> --web-research-bundle <structured-research.json>`. Use `--research-all-held` only when the user explicitly requests research of every holding. Use `--include-reference-assets` for BTC native analysis and the explicitly external ETH framework; neither reference asset is added to held positions. Pass user event restrictions through `--special-rules` only with their source identified. DB restrictions take precedence and cannot be released by a valuation number.

Read the authoritative snapshot and ledger projection before pricing. Preserve account/currency cash identities. If cash, reservations and the broker snapshot disagree, keep reconciliation partial and withhold the cash total; never rewrite personal.db to make the run complete. ETF inputs route to `FundAnalysisInput`, never an equity model. Media repetition cannot establish official confirmation. A potentially material reported event can trigger research while its valuation impact remains `WAIT` under the existing event impact contract.

Build distributable runtime artifacts with `python scripts/build_verified_distribution.py`. It removes cached build output and verifies every Python/SQL/JSON runtime file in the wheel against the actual source. Do not distribute an old build directory or accept a wheel solely because creation succeeded.

## Generic security identity and standalone analysis

There is no production list of portfolio tickers. Register `identifiers` through `PersonalLedgerService.register_instrument`, using `listing_id` (EXCHANGE:TICKER) or explicit `exchange`/`ticker`, with the registered currency and EQUITY/FUND asset class. US bare tickers can resolve from live provider metadata; a name/internal slug is not sufficient identity. Identity resolution does not approve a price: quote identity, date, session, currency and freshness validation still runs independently. Unsupported or conflicting identities retain an explicit partial reason.

Old personal DBs lacking identifiers can supply `--instrument-registry <external-registry.json>` without rewriting personal.db. The optional registry has `schema_version: 1` and an `instruments` object keyed by instrument ID, with explicit listing metadata. DB identifiers take precedence. New securities do not require editing this registry when DB identifiers or a resolvable explicit US ticker are supplied. Do not silently add resolved identities or reference assets to the personal ledger.

`python scripts/run_asset_analysis.py --personal-db <db> --run-workspace <workspace> --asset AAPL --live-providers` runs SINGLE_ASSET_ANALYSIS for an unheld stock. Multiple `--asset` values run ASSET_COMPARISON. The same resolver accepts an `assets` list in ModeRequest; explicit typed `research_specs` remain supported. Use `--assets-json` for explicit listing/currency/type/provider identifiers. Funds use the portfolio fund route; the existing standalone equity mode explicitly rejects a fund equity spec rather than valuing it as a company.

Live news discovery uses related ticker bindings and publication times, marks headlines as NEWS_REPORTED, and screens potential material events for verification. Search headlines are not independently verified issuer disclosures or approved calculation inputs. A supplied verified web research bundle takes precedence. US financial retrieval can resolve a ticker/exchange to CIK through the SEC directory; DART corp codes and missing foreign issuer data remain explicit required inputs. Unknown business type must not justify invented DCF assumptions or target prices.

When materializing a legacy DB with an associated `instrument-registry.json`, materialize that registry beside the explicitly supplied personal.db, or provide its path through `--instrument-registry`. Only the exact sibling filename is used as the optional default; no folder scan occurs. This is identity metadata, never an override of position/cash/ledger facts. New registered identifiers take precedence. Use `--offline-captures` to forbid every missing-payload network fallback; original retrieval/quote timestamps stay intact, and expired FX is rejected rather than refreshed artificially.
