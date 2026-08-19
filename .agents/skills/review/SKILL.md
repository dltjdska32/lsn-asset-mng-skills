---
name: review
description: Perform risk-based conditional review of investment analysis and transaction decisions. Use when materiality is high, confidence is low, sources conflict, critical data is stale, an instrument is new, net-worth impact is large, or an unsupported or high-impact state change is requested.
---

# Investment Review

1. Confirm runtime schema, balance, freshness, lineage, idempotency, event time, timezone, transfer type, confirmation, and DB-integrity checks ran.
2. Review high-materiality conclusions, low-confidence findings, source conflicts, and stale critical inputs.
3. Escalate unsupported in-kind transfer, bootstrap/repair, large net-worth change, rumor-driven conclusions, and strong strategy changes.
4. Check that unknowns and partial results remain visible in the report.
5. Check that no Skill invented a price, timestamp, transaction, calculation, or personal state.
6. Return actionable findings by severity. An independent reviewer agent remains optional.

