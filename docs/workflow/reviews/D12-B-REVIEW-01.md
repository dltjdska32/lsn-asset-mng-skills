# D12-B independent review

- Review source: `91adaa283c2961547673864bfb8964b50e256bdb` (policy source `ba3ef0a`, originating in isolated `codex/d12-b` worktree).
- Independent reviewer: `/root/d12_b_independent_review`; read-only review, 34 focused tests passed.
- P1: equity report displayed numeric 80/75/70% DCF-based "entry ceilings" without binding valuation assumptions, personal state, reserves, and costs. This contradicted the D12 WAIT gate. Coordinator removed the numeric reference-price projection and retained WAIT on `ff84430329e38c85fa2342cab9bffeebd32e002d`.
- P2: policy evaluator accepted cash plus holding value greater than the total portfolio, yielding a conditional budget for impossible state. Assigned back to the original Luna Medium implementer; fix source `dcbd6aa87f05216f8ab22672b9cd0a7d6a21ebf4` was integrated as `10bf46d804679fdaa81492738329130ff0716de5`.
- P2: overvaluation triggered a one-third reduction review even with zero holdings. Same implementer fixed it in `dcbd6aa`/`10bf46d`.
- Follow-up: `afe7156` (integrated `dd0e793`) suppresses numeric entry tiers and budget until complete trusted-host attestations and verified typed values are present; `Money` defaults to unverified. `386296d` (integrated `61fd2eb`) stops additions when the cash floor leaves zero available cash or a stricter verified risk budget is zero.
- Independent re-review of exact source `61fd2ebaede88fefd361ff0ca0f23bb01bcb2dd4`: all original P1/P2 findings closed by adversarial reproduction, focused suites **39 OK** (policy **23 OK**), no new P1/P2 in the changed scope. This is a review pass, not the separate final verification.
- Limit: readiness flags are trusted-host attestations, not proof of persisted evidence. No host presently binds personal state, valuation input values, FX/costs and units for actionable entries; user-specific prices/quantity remain WAIT.

All tests and examples use synthetic data. No personal ledger or order was used.
