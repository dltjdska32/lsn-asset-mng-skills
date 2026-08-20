---
name: investment-report
description: Produce evidence-based investment reports with pinned as-of state, calculation lineage, confidence, and explicit partial or unavailable sections. Use for final single-asset, comparison, portfolio, scenario, thesis-review, and refreshed reports.
---

# Investment Report

1. State the analysis date, timezone, pinned state version when applicable, and report availability.
2. Separate evidence, calculations, interpretation, and proposed monitoring actions.
3. Cite the evidence identifiers and source timestamps used for each material conclusion.
4. Display stale, conflicting, partial, and unavailable inputs prominently.
5. Never label an unverified or stale value as a current price.
6. Keep rumors from changing the base case; label news confirmation state.
7. Include risks, thesis breakers, monitoring signals, and model limitations.
8. Present strategy as analysis, never as an executed order or posted transaction.


## v1.3.1 user-facing quote/report rules

9. User-facing status/action labels must be Korean. Keep internal enum/database values in English for compatibility, but render `UNKNOWN/PARTIAL/LIVE/DELAYED/STALE/BUY/HOLD/SELL/Confidence` as clear Korean labels.
10. For a current-price claim, do not stop at the first failed, untimestamped, stale, or invalid source. Retry appropriate fallback sources; use `확인 불가` only after fresh/current evidence still cannot be verified.
11. Every displayed price must carry its data date/time and market/freshness state. Old observations must never be presented as today's current price or used as a current-price calculation input.
12. When multiple comparable sources disagree, verify timestamp/session/source authority and never average the conflicting prices. Preserve conflict lineage.
13. Separate quote retrieval from news research. Prefer market-appropriate quote sources; web research is fallback and must satisfy timestamp/freshness rules.
14. When current price remains unavailable, explain the reason in Korean (for example `오늘 시세 확인 실패`, checked-source count when known, and latest verified data time when known) rather than exposing an internal English status code.
