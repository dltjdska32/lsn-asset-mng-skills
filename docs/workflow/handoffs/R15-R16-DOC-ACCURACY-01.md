# R15/R16 documentation accuracy handoff

## Assignment

- Base checkpoint: `a1a41b0`.
- Branch: `codex/r15-r16-doc-accuracy`.
- Scope: documentation only; README, implementation status, and frozen architecture.
- Runtime, skills, and test files were not changed.

## Updates

- Replaced the obsolete `a861b6b` / `5d094a5` current-status section with checkpoint `a1a41b0`, recording root suite 595 OK/1 skip and independent fixed review 13/13 PASS as pre-final-review evidence.
- Documented seven-mode configured service composition and its host-injected `run.db`, personal ledger/loaders, providers, credentials, and callbacks. Clarified that the default CLI has no configured handlers.
- Corrected R01 wording: the default factory wires bounded pinned NASDAQ/KRX calendars and can qualify a verified dated observation as `LAST_VALID_CLOSE`. The snapshots are limited to September 2026; no general weekend-calendar coverage is claimed.
- Updated the historical B-only Naver note so the pre-integration `AVAILABLE` result is not presented as current behavior. Documented the 2026-09-27 Phase 4 → run.db → Phase 5 evidence path and its limited source/time scope.
- Clarified that external-provider connectivity checks do not establish broad or continuous vendor availability, that Investing.com live pages were not verified, that OpenDART credentials are host-injected, and that Codex UI auto-discovery from an arbitrary venv prefix remains unconfirmed.
- Corrected architecture status/roadmap text to point to the implementation-status document rather than claim implementation has not started or only architecture freeze is complete.

## Verification and limits

- Compared claims against `runtime/investment_stack/cli.py`, `execution/service_composition.py`, `providers/factory.py`, `providers/market_quotes.py`, `freshness/calendar.py`, and `deep_research.py`, plus the R01 and R14 handoffs.
- Checked all new relative Markdown links resolve within the checkout.
- `git diff --check`: passed.
- No tests were run; no runtime, skill, test, credential, or personal-data files were accessed for modification.
- Counts and live-source observations are reported as the `a1a41b0` checkpoint. Later review or verification findings may change them and should be recorded by the integrator.
