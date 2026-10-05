---
name: personal-asset-analysis
description: Analyze confirmed personal portfolio state, cash, liabilities, exposures, concentration, liquidity, and risk. Use for personal portfolio reviews, net-worth analysis, allocation diagnostics, and non-posting scenarios based on a pinned state version.
---

# Personal Asset Analysis

1. Pin `personal.state_version`, analysis time, and timezone before analysis.
2. Use posted ledger projections only. Exclude drafts, pending transactions, and unsupported in-kind transfers from confirmed state.
3. Run the all-asset lightweight pass before requesting any portfolio deep research.
4. Apply the materiality gate and deep-research only selected assets.
5. Distinguish valued, unvalued, and partially valued positions in all totals.
6. Analyze account, asset class, country, currency, sector, liquidity, custody, leverage, and look-through exposure.
7. Present scenarios as non-posting outputs; never imply that an order or ledger change occurred.
8. State missing data and net-worth limitations plainly.
9. Build selected-equity deep-research callbacks with `LiveDeepResearchRuntime`; a materiality PASS followed by prose-only web analysis does not satisfy `deep_research_selected_assets`.

## v7 capital allocation and completed calculations

Apply [the capital allocation policy](references/capital-allocation-policy.md).
Concentration is risk information, never an automatic sell rule. Compare all held
and requested candidate assets. Materiality limits expensive research only.
Persist a lightweight baseline for every holding and refresh the whole universe
after selected research. Final CAPITAL_COMPETITION.ranking includes all holdings;
missing scores stay null/WATCH/LOW with provenance and coverage limitations.
Separate actual
transaction FX/P&L, account buying power, fund look-through and risk proxy outputs.
