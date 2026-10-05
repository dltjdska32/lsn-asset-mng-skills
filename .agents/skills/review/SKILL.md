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

## v7 executed adversarial review

Apply [the capital allocation policy](references/capital-allocation-policy.md).
Persist actual Level 3 assessments for concentration and allocation triggers,
including funds. Topic gaps make both review and its fixed stage partial; a task
name or a trigger is not review output. Keep new concentration/add proposals
provisional until an evidence-bound complete review exists.

