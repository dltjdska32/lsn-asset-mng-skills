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

Use `python -m investment_stack route "<request>" --json` to inspect the selected mode and fixed steps.

