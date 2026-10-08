# FORECAST-LOGIC-01 design and assignment

Owner of design/review: Codex. Implementer: Antigravity CLI 1.2.12, gemini-3.1-pro-high with --effort high and session-only --dangerously-skip-permissions. User supplied Antigravity login context after the separate gemini command failed authentication.
User authorization (2026-10-08 KST): Gemini CLI session approval bypass and local implementation commits; Codex owns design and review. This overrides historical coordinator-only commit ownership for this task. No global permission changes, remote push, deployment, real personal DB or orders.
Base: 2bfec11cf9e1dc26f9426791b2a9d064915e2965. Branch: codex/forecast-v7-logic-fix.
Worktree: C:/Users/lsn/lsn-asset-mng-skills/workspace/cache/forecast-v7-logic-fix.
Input: workspace/cache/v7-input (reviewed external patch source only; untracked, never commit this cache).
Requirements: forecasting corrections identified in this chat; linked repository R01/R03/R07/R09/R15/R16 boundaries.

## Scope and ownership

Implement the forecasting logic corrections as an optional, reviewable subsystem in this repository, preserving existing 8 skills/7 modes and behavior. Import external forecasting module into runtime/investment_stack/forecasting; isolate imported tests under tests/forecasting. Import only needed standalone scripts; do not import unrelated data collectors or replace current providers. The runner may read the external market_data.db schema via a read-only connection but does not create/use personal DBs.
Gemini owns new forecasting/**, tests/forecasting/**, forecasting-specific scripts, a requirements-forecasting.txt extras file, task-specific integration documentation, and handoff FORECAST-LOGIC-01. Minimal pyproject optional-dependency changes only if needed. Do not edit existing execution modes, D12 policy, personal/**, general providers, old design/decisions/tasks, AGENTS.md, or skills mirrors. Codex reviews all changes.
Full production Capital Competition/Top10 and automatic hourly execution are outside this correction batch: never silently enable unvalidated forecasts or trade/rank policies. Build the return/risk assessment interface and conditional workflow clearly; document integration limits. Real pretrained inference and real-data OOS cannot be claimed from synthetic tests.

## F01: shared economic contract

Request must carry offset-aware analysis_as_of, positive finite current_price, nonempty instrument/currency, history observation timestamps, fixed positive integer horizon and frequency, explicit target_date consistent with last usable observation and forecast steps, and target semantics (terminal price, price return versus total return). Reject bool-as-number, NaN/Inf, nonpositive prices, future/duplicate/unsorted observations, length mismatch and invalid frequencies; do not silently infer currencies or disclosure timestamps.
Model outputs bind instrument, currency, analysis_as_of, target_date, horizon/frequency, price basis and point semantics (mean/median/point). Ensemble checks these before mixing. Price basis must be consistent (e.g. split-adjusted price excluding dividend reinvestment); total-return prices cannot be silently mixed with ordinary price anchors. Positive finite monotonic quantiles with finite keys in [0,1] required when present. No need to fabricate absent quantiles.

## F02: current value versus future fundamental scenarios

Keep current fair value separate from future terminal valuation. Existing present-value DCF is never automatically used as a year-five anchor.
FundamentalAnchor used in ensemble requires explicit terminal target_date, currency, instrument, evidence/assumption references, and compatible price basis. An incomplete/undocumented anchor remains partial/unavailable. Caller references establish lineage, not source authenticity; explicitly label supplied scenarios and do not promote them to verified investment evidence.
Add a pure future-fundamental scenario helper: explicit horizon-year revenue/growth, operating/cash-flow margins as applicable, terminal valuation method/multiple, terminal net debt and fully diluted terminal share count; produce terminal per-share scenario values with formulas and source references. Do not invent growth/margins/multiple/dilution defaults. ROIC/reinvestment constraints are checked only if supplied. Expose this as scenario arithmetic, not an approved investment forecast. A limited revenue-multiple or earnings/FCF-multiple model with explicit input semantics is sufficient; no universal financial-company valuation claims.
Bear/base/bull are assumption scenarios, not q10/q50/q90. No automatic assignment of scenario bounds to statistical quantiles.

## F03: ensemble and status

Reject duplicate model identities rather than counting/weighting twice. Unknown models have no arbitrary positive prior. Reject nonfinite/negative priors and reliability scores. Zero-weight models cannot affect point, quantiles or completion. Validate outputs centrally and isolate invalid model outputs with exclusion reasons.
Distinguish computation status (COMPLETE/PARTIAL/UNAVAILABLE/ERROR) from empirical validation level (e.g. EXPERIMENTAL/OOS_VALIDATED). Never call experimental bootstrap output investment-ready. Partial anchor/components propagate partial completeness. COMPLETE requires compatible complete anchor and >=2 distinct, positively weighted, complete model outputs; missing uncertainty is explicitly recorded separately.
Bootstrap priors remain the supplied raw values normalized over eligible components; disclose resulting effective weights and source BOOTSTRAP or OOS. Do NOT impose permanent 60% anchor minimum or invented score thresholds. Reliability metrics need same OOS horizon/data universe/cutoff/metric semantics before comparison, and do not become probabilities. Preserve unmodified fundamental values separately from combined estimates.
Point aggregation may remain geometric, but record it is a representative estimate, not E[price] or E[CAGR]. Reject/flag gross divergence rather than claiming a 3x rule is validated; default experimental thresholds must be disclosed.
Do not construct final calibrated quantiles by averaging quantiles from changing component sets. Preserve component quantiles; either use a documented common calibrated distribution method or report ensemble uncertainty UNAVAILABLE until compatible calibrated uncertainty evidence is supplied. No invented +-30% intervals or forced flat quantiles described as calibration.

## F04: time and market-data runner

Runner requires --as-of with timezone and uses only rows knowable/observed by that instant. Use SQLite mode=ro so missing/wrong paths never create DB files. Filter retrieved_at if historical reproducibility requested; do not relabel today's retrieval as historical knowledge. Explicit source selection or deterministic source-quality/conflict policy; no arbitrary last SQL row.
Require instrument/currency consistency. Reject conflicting same-date suppliers unless a specified source resolves them; do not mix adjustment bases. Require positive finite valid OHLCV and honest missing-volume behavior. Use complete months only; do not relabel the current incomplete month as a completed future month. Local exchange session/month completion needs explicit trustworthy cutoff/calendar evidence or conservatively use preceding month and report lag; no fake live close.
Use split-adjusted OHLC consistently via known raw-to-adjusted factor with disclosed basis, or reject series whose adjustment policy cannot be established. Never fill missing adjusted close to raw and claim adjustment confirmed. Do not treat dividend-adjusted total returns as split-only adjustments.
Kronos dropna/truncation must retain exact matching timestamps. Chronos covariates require valid timestamp-aligned values and supplied publication times for empirical inputs; unknown future covariates are scenario assumptions, explicitly marked.
5Y remains month-end 60 steps. Preserve available full point forecast path when model supplies it, but never fabricate a path from a terminal number. FinCast without a configured verified bridge stays unavailable.

## F05: point-in-time datasets and supervised ML

Add shared training split/walk-forward logic with mandatory label_available_at or future_as_of, feature publication timestamps, required feature schema, and forbidden future/label fields. For each fit, train features and labels must be available by fit cutoff; validation/test fit/calibration cutoffs must be honest. Random splits prohibited. Reject missing cutoff metadata and empty/invalid splits. Expanding folds must exclude labels overlapping a fit cutoff. Train/validation/test cutoffs strictly ordered.
PIT checking must be invoked by actual training scripts, not an optional separate utility. Distinguish target future date from label availability, use latter if later. Return known-as-of evidence and enforce schema semantic units. No future prices/target fields selectable via --features.
Artifact metadata carries training target, horizon years, feature schema/publication bindings, max label availability cutoff, calibration cutoff, OOS scope/metrics and provenance including SYNTHETIC or REAL. Synthetic artifacts only produce experimental arithmetic outputs, never OOS_VALIDATED.
Adapter enforces trained horizon (5y only unless matching other artifact), cutoff<=request as_of, finite features and publication times<=as_of, explicit current eligible price. Missing/invalid OOS evidence means EXPERIMENTAL/PARTIAL, not empirically approved. Do not gate merely by user-provided boolean. Validate evidence structure and preserve provenance; authenticity remains unverified unless existing trusted runtime evidence is bound.
Native JSON/text + SHA256 loading only. Reject model_file escaping artifact directory. No pickle/joblib for tabular production load. Calibration residuals unavailable => quantile uncertainty unavailable, not handpicked spreads.

## F06: Monte Carlo and return/risk assessment

Require explicit history frequency consistent with simulated step frequency; positive integer steps/path count, finite current/target and timestamps. No dropping interior invalid prices and joining returns across gaps. Check min observations, disclose stationarity/normal/iid assumptions. Median target and expected terminal value are distinct; report mean/median correctly.
Optional stochastic terminal model can remain lognormal, with explicit conditional scenario status and no empirical calibration claim. Combine only when target and covariance/volatility data are coherent, and mark double-counting risks if model uncertainty already represented. Model disagreement and business-scenario uncertainty must be separately visible, not silently subsumed in historical volatility.
Create assessment output separating representative price CAGR, median CAGR, expected simple cumulative return and expected CAGR when actual samples exist, downside quantiles, loss probability, and optionally path drawdown only if paths exist. Price-only excludes dividends/tax/FX/costs explicitly. Total return requires explicit cashflows/FX assumptions, no silent zero defaults. No investment ranking from unavailable risk or experimental output; expose reasons for withholding ranking. Keep current intrinsic value and terminal fundamentals/AI estimates separately.
Engine calls optional coherent uncertainty/assessment stage and returns/persists it; runner outputs assessment. Do not pretend disconnected helpers form integrated E2E. Existing personal ledger/automated orders are untouched.

## F07: loaders, storage and failure isolation

Pretrained load is local-only and rechecks pinned checkpoint/tokenizer hash immediately before load, along with required config hash/provenance or pinned snapshot manifest. Source imports use verified Kronos source revision and dirty-tree detection, not arbitrary module named model. Windows absolute/missing paths fail closed. Do not download models during tests. Bootstrap locally writes manifests for all files/revision; validate before trusting. No global git reset/clean or deleting user model directories.
Catch individual adapter exceptions, produce explicit ERROR and continue healthy models. If request itself invalid, reject the whole request. Persistence keeps request as_of/target_date/price basis/provenance/validation status and component/assessment links; no NaN JSON. Caller-selected run DB must not be personal.db; validate run identity where practical and document additive schema. No actual personal DB tests.

## Acceptance checks

Meaningful tests for: current DCF rejected as terminal anchor; mixed horizon/currency/instrument/as-of; NaN/Inf and bool; duplicate and zero-weight models; partial propagation; unavailable calibration; training future-label leakage at fold cutoff; missing feature timestamps; trained 5y model rejected on 1y; future calibration cutoff; synthetic artifact validation label; incomplete/future month and corrected OHLC/source conflict; Kronos timestamp alignment; loader hash mismatch before from_pretrained (mocked, no weights); Windows path; adapter failure isolation; coherent monthly uncertainty/return assessment; no rankings without validated inputs; forecast persistence and run identity. Add a synthetic full core workflow test from explicit future-fundamental scenarios + injected model adapters through ensemble/uncertainty/assessment/storage. Synthetic testing does not prove forecast accuracy.
Run focused forecasting tests and relevant existing regression/package checks with the same interpreter. Record exactly what ran, counts, skips and dependency/network limits. Do not claim full existing suite success without execution. Codex independently runs adversarial checks and reviews final diff before acceptance. Commit local owned changes explicitly (no git add .), leave no staged leftovers, no push.

## Handoff

docs/workflow/handoffs/FORECAST-LOGIC-01.md must report base/final commit, files changed, tests run, unrun real inference/OOS, model used, remaining limitations and integration boundaries. Do not create reviewer approval documents yourself.
