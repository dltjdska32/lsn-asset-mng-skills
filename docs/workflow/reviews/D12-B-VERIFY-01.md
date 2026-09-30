# D12-B separate final verification

- Exact verified source: `61fd2ebaede88fefd361ff0ca0f23bb01bcb2dd4`.
- Verifier: `/root/d12_b_final_verification`, a Codex session separate from the Luna Medium policy implementer and independent reviewer. It made no root source edits.
- Isolated temporary archive: 512 tracked blobs matched the Git tree after normalizing Git archive's Windows CRLF conversion; no tracked source changes after build/tests.
- Fresh wheel and sdist built successfully. `policy_b.py` bytes matched between source, sdist, wheel, and installed wheel.
- Independent full unittest discovery: **671 OK, 1 skipped**, 127.0 seconds. The first archive-only run hit 12 existing packaging test assertions that require a `.git` directory; after `git init` in the temporary archive, the full suite passed. These were test-environment failures, not code failures.
- Installed-wheel synthetic adversarial probes passed: complete trusted inputs yielded 80%/75%/70% tiers and three equal budgets; 8% position cap, 10% cash floor, strictly above 10% concentration review, 1.2× optimistic threshold with verified positive holdings, zero risk budget, and invalid/unverified input WAIT gates behaved as specified. No orders or file writes occurred.
- Separate synthetic persisted-DCF-only equity run showed a verified conditional DCF value but kept the final briefing at WAIT and hid actionable entry price, quantity, and the 80%/75%/70% numeric tiers.
- Coordinator independently built wheel/sdist and ran **671 OK, 1 skipped** on the same exact source. This document records the separate verifier's own result rather than substituting that coordinator check.

Scope limit: no real personal portfolio database, live market quote, private credential, or automatic order was used. The current host does not bind actual personal state, valuation assumptions, quote/FX, reserve exclusions, fees, and trading units into D12 B. User-specific price, amount and quantity therefore remain WAIT.
