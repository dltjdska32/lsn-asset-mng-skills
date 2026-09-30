"""Replay captured public responses against market-source eligibility boundaries."""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('--repo', type=Path, required=True)
args = p.parse_args()
sys.path.insert(0, str(args.repo.resolve() / 'runtime'))
from investment_stack.providers.market_quotes import parse_naver_basic_quote
from investment_stack.providers.ohlcv import parse_naver_ohlcv
from investment_stack.contracts import ContractError

source = args.repo / 'workspace/runs/source-inputs'
payload = json.loads((source / 'naver_basic.json').read_text(encoding='utf-8-sig'))
missing_time = dict(payload)
missing_time.pop('localTradedAt', None)
cases = {
    'source_identity_must_match_request': lambda: parse_naver_basic_quote(payload, instrument_id='KRX:000660'),
    'missing_market_time_must_not_use_retrieval': lambda: parse_naver_basic_quote(missing_time),
    'unknown_adjustment_must_not_be_verified': lambda: parse_naver_ohlcv(
        (source / 'naver_ohlcv.json').read_bytes(),
        analysis_as_of=datetime(2026, 9, 23, 8, tzinfo=timezone.utc)),
}
failed = 0
for name, call in cases.items():
    try:
        result = call()
        valid = not result.is_usable
    except ContractError:
        valid = True
    except Exception as exc:
        print('BLOCKED', name, type(exc).__name__, str(exc))
        failed += 1
        continue
    print('PASS' if valid else 'FAIL', name)
    failed += not valid
raise SystemExit(bool(failed))
