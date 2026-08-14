---
name: valuation
description: Value supported securities using evidence-linked inputs and asset-appropriate models. Use for equity valuation, scenario ranges, multiples, discounted cash flow, and cross-checks; do not use corporate valuation models for Bitcoin, gold, or silver.
---

# Investment Valuation

1. Verify asset classification before choosing a method.
2. Use deterministic runtime calculations with evidence IDs, units, currency, and as-of timestamps.
3. Expose every material assumption and provide a range when inputs are uncertain.
4. Cross-check model output against at least one compatible method when evidence permits.
5. Reject stale prices as current prices and label unavailable inputs.
6. Never apply company cash-flow or earnings valuation to Bitcoin, gold, or silver.
7. Return valuation status, confidence, sensitivities, and limitations. Do not mutate personal state.

