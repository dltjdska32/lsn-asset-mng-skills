---
name: fundamental-analysis
description: Analyze public companies from timestamped filings, investor relations materials, financial statements, and industry evidence. Use for business quality, financial performance, competitive position, catalysts, and company-specific risk analysis.
---

# Fundamental Analysis

1. Pin the analysis date and timezone supplied by the orchestrated run.
2. Prefer primary sources: regulatory filings, exchange disclosures, audited reports, and issuer materials.
3. Record each material claim against evidence with source date, retrieval time, and availability.
4. Separate reported facts, deterministic calculations, estimates, and interpretation.
5. Reconcile conflicting periods, units, currencies, and accounting bases before comparison. Preserve source scale explicitly for every numeric fact; `JPY million`, `KRW billion`, `million shares`, and per-share units must not be collapsed to bare numbers before runtime normalization.
6. State business drivers, financial quality, catalysts, risks, and monitoring signals.
7. Mark unavailable or stale inputs explicitly; never manufacture a current figure.
8. Return structured findings to valuation or report generation. Do not mutate personal state.
9. For live runs, financial facts must pass through `Phase4ResearchRuntime`/`EvidenceResearchStore` and `LiveDeepResearchRuntime` before `EquityFundamentalAnalyzer`; a prose-only web summary is not a runtime execution.
