---
name: investment-orchestrator
description: Route investment requests to one of the seven v1.3 request modes and coordinate its predefined runtime pipeline. Use for asset updates, personal portfolio analysis, single-asset analysis, asset comparisons, portfolio scenarios, thesis reviews, and report refreshes.
---

# Investment Orchestrator

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
