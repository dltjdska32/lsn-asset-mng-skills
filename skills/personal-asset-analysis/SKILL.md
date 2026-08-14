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

