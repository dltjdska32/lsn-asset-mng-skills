"""Coordinator residual checks: synthetic temporary run DBs only; no network."""
import argparse
import json
import sqlite3
import sys
import tempfile
from contextlib import closing
from decimal import Decimal
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--repo', type=Path, required=True)
args = parser.parse_args()
sys.path.insert(0, str(args.repo.resolve() / 'runtime'))
from investment_stack import contracts as c
from investment_stack.contracts.storage import CONTRACT_STORAGE_KEY, empty_contract_storage
from investment_stack.evidence.manager import RunDatabaseManager

failures = []
def check(name, operation):
    try:
        operation()
    except c.ContractError as exc:
        print('PASS', name, type(exc).__name__)
    else:
        failures.append(name)
        print('FAIL', name, 'accepted invalid input')

with tempfile.TemporaryDirectory(prefix='contract-residual-synthetic-') as td:
    root = Path(td)
    manager = RunDatabaseManager(root, 'synthetic-residual')
    assert manager.create().valid
    manager.add_evidence(evidence_id='value-free', evidence_type='test')
    slot = c.BoundSlotInput('price', Decimal('999999'), 'USD', 'USD', 'value-free')
    snap = c.SelectedInputSet.create(manager.run_id, 'CURRENT_PRICE', 1, [slot])
    check('value_free_evidence_cannot_authorize_price', lambda: manager.persist_contract_snapshot(snap))

    check('typed_evidence_decoder_is_required', lambda: manager.add_contract_evidence(
        evidence_id='malformed', contract_envelope=c.encode_envelope('MarketQuote', {'currency': 'USD'})))

    for case, change in (
        ('counter_tail_mismatch', lambda s: s.update(latest_revision=999)),
        ('missing_history_envelope', lambda s: s.update(history=[{'revision': 1, 'snapshot_hash': 'x'}], latest_revision=1, latest_snapshot_hash='x')),
        ('dangling_active_pointer', lambda s: s.update(active_selections={'CURRENT_PRICE:TEST': 'missing'})),
    ):
        storage = empty_contract_storage()
        change(storage)
        with closing(sqlite3.connect(manager.database_path)) as connection:
            connection.execute('UPDATE run_metadata SET metadata_json=? WHERE run_id=?',
                               (json.dumps({CONTRACT_STORAGE_KEY: storage}), manager.run_id))
            connection.commit()
        check(case + '_read', manager.fetch_contract_snapshots)

print('TOTAL FAIL', len(failures))
raise SystemExit(bool(failures))
