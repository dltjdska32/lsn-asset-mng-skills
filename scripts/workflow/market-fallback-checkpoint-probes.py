"""Read-only, offline source replay against a Gemini B checkpoint.

The captured public responses are development fixtures, not fresh live quotes.
This script reports behavior; failed assertions do not edit the target worktree.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    args = parser.parse_args()
    repo = args.repo.resolve()
    sys.path.insert(0, str(repo / "runtime"))
    from investment_stack.providers.market_quotes import MarketQuoteProvider
    from investment_stack.providers.models import ProviderStatus

    inputs = repo / "workspace" / "runs" / "source-inputs"
    coinbase = (inputs / "coinbase_btc_ticker.json").read_bytes()
    kraken = (inputs / "kraken_btc_trades.json").read_bytes()
    as_of = datetime(2026, 9, 23, 9, 30, tzinfo=timezone.utc)
    clock = lambda: as_of
    cases = [
        ("primary_ok", lambda url: (200, coinbase if "coinbase" in url else kraken), True, "coinbase_public", 1),
        ("primary_http_failure", lambda url: (503, b"" ) if "coinbase" in url else (200, kraken), True, "kraken_trades", 2),
        ("primary_parse_failure", lambda url: (200, b"{}") if "coinbase" in url else (200, kraken), True, "kraken_trades", 2),
        ("primary_future_time", lambda url: (200, json.dumps({**json.loads(coinbase), "time": "2026-09-24T00:00:00Z"}).encode()) if "coinbase" in url else (200, kraken), True, "kraken_trades", 2),
        ("both_fail", lambda url: (503, b""), False, None, None),
    ]
    failures = 0
    for name, responder, expected_available, expected_source, expected_calls in cases:
        calls: list[str] = []

        def transport(url, headers, timeout):
            calls.append(url)
            status, body = responder(url)
            return status, body, {}

        result = MarketQuoteProvider(transport=transport, clock=clock).fetch_current(
            "CRYPTO:BTC/USD", analysis_as_of=as_of
        )
        available = result.status == ProviderStatus.AVAILABLE
        source = result.metadata.get("selected_source")
        attempts = result.metadata.get("attempts", ())
        ok = (
            available == expected_available
            and source == expected_source
            and len(attempts) == len(calls)
            and (expected_calls is None or len(calls) == expected_calls)
        )
        print(f"{'PASS' if ok else 'FAIL'} {name}: status={result.status} source={source} calls={len(calls)} attempts={len(attempts)}")
        failures += not ok

    # A BTC/EUR request must never be fulfilled by the hardcoded BTC/USD endpoint.
    calls = []

    def usd_transport(url, headers, timeout):
        calls.append(url)
        return 200, coinbase if "coinbase" in url else kraken, {}

    wrong_pair = MarketQuoteProvider(transport=usd_transport, clock=clock).fetch_current(
        "CRYPTO:BTC/EUR", analysis_as_of=as_of
    )
    pair_ok = wrong_pair.status != ProviderStatus.AVAILABLE
    print(f"{'PASS' if pair_ok else 'FAIL'} wrong_pair_rejected: status={wrong_pair.status} calls={len(calls)}")
    failures += not pair_ok
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
