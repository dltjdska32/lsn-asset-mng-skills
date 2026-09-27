# Handoff: LUNA-B-TRANSFER-02

## Assignment and commits

- **Owner:** Codex GPT-6 Luna Medium
- **Branch:** `codex/luna-b-transfer-02`
- **Worktree:** `C:/Users/lsn/.codex/worktrees/72d3/lsn-asset-mng-skills`
- **Base / requested target SHA:** `0ed93d8e100494a350f5ecde160c72ffafaf26a1`
- **Provider implementation commit:** `5d424e4` (`fix: bind Naver OHLCV to verified request route`)
- **Documentation commit / implementation target SHA:** `3ffe21d` (`docs: qualify market data and Windows package status`)
- No root integration, push, merge, personal database access, credential access, or order placement was performed.

## Changes

- Adapted Naver's actual daily-price response: the public endpoint returns a top-level list without an echoed ticker and uses comma-grouped numeric fields. The parser now binds that response only to the canonical HTTPS Naver `/api/stock/{code}/price` route, rejects unbound or mismatched routes, and parses valid thousands separators.
- Preserved Naver's returned raw bars and parse diagnostics when the provider cannot create a validated `BarSet`. An adjustment flag alone no longer suffices; both a strict `True` flag and a non-empty receipt are required. Receipt authenticity remains unverified.
- Added provider tests for route identity, raw-bar handling, adjustment gating, and the live response shape. Removed parser-authored `calculation_input_approved=True` metadata from the B market-quote sources; data source parsers do not grant calculation eligibility.
- Updated Windows setup guidance to invoke pip, tests, and skill sync through the same venv interpreter. Clarified architecture vs package version, package allowlist limits, truststore wiring status, quote freshness requirements, indicator conventions, and source-provenance limitations.

## Verification performed

- B-focused provider, OHLCV, and technical fixture suite: **45 tests passed** in a Windows venv with `truststore 0.10.4` and `tzdata 2026.4`. These are fixture tests, not live-source evidence.
- Built `investment-stack-0.1.0` wheel and sdist on Windows; installed the wheel into an isolated venv. `tests.test_packaging`: **5/5 passed**, including artifact allowlist checks and installed 8-skill source/mirror byte equality.
- Ran `scripts/sync_agent_skills.py --check` through the installed venv interpreter: exit 0.
- `git diff --check`: passed. Git printed only its configured LF-to-CRLF conversion warnings.
- Live source requests used a temporary `truststore.SSLContext` transport with normal certificate and hostname validation. Naver Samsung quote/page and daily-price endpoints, Yahoo AAPL chart, and Coinbase BTC-USD returned HTTP 200. B quote adapters parsed Naver, Yahoo, and Coinbase responses; Yahoo daily OHLCV produced 22 bars.
- Naver quote parsed as `LAST_VALID_CLOSE` at **2026-09-23 15:30 KST**, despite retrieval on 2026-09-27. The provider returned `AVAILABLE` because no R01 eligibility evaluator was supplied. This observation is stale and is not evidence of a current KRX price.
- Naver daily-price live response parsed into five raw bars with zero discarded rows. The provider correctly returned `UNAVAILABLE` because no verified adjustment receipt was available; no adjusted KRX `BarSet` is claimed.
- Direct Investing.com US and Korea page requests returned HTTP 403. They remain fixture-only candidates.
- With the declared truststore installed, the production `providers/http.py::urllib_transport` still returned `ProviderTransportError` for a public HTTPS request. A direct default-urllib probe earlier showed certificate verification failure. This confirms that dependency declaration does not wire scoped Windows TLS.

## Not run / remaining limits

- Full repository suite and independent final review/verification were not run in this B handoff.
- The new live Naver parser path has focused synthetic tests and was exercised against a public response. Japanese and metals providers, KRX official token/API access, and a complete market-by-market live fallback sequence remain unverified.
- R01 freshness-evaluator wiring is outside B ownership. The current adapter can return a parsed stale quote as `AVAILABLE` unless its caller supplies that evaluator; freshness policy and current-price eligibility are not implied by parser success.
- Naver request-route binding is request provenance, not a ticker echoed by the response. The adjustment receipt is a caller-provided marker, not a verified corporate-action record. Official calendar, session-gap, split-factor, and correction coverage checks remain incomplete.
- The R08 functions have hand-calculated fixture coverage, but this run did not execute a live bars-to-chart-to-briefing flow. Their `Sequence[Bar]` API carries no source provenance, so the caller must keep raw diagnostics out of production calculations.
- Wheel-installed Codex UI auto-discovery in a separate environment was not tested. Package tests establish included files and installed mirror equality only.

## Request to A / root

`runtime/investment_stack/providers/http.py` is A-owned and was left untouched. Connect `truststore` through a scoped SSL context while keeping certificate and hostname verification enabled, and preserve Decimal parsing where provider JSON currently becomes binary floats. Add default-transport tests, then repeat the Naver/Yahoo/Coinbase public checks through the production transport and report any access failures. Do not treat the installed dependency by itself as evidence that TLS is connected.
