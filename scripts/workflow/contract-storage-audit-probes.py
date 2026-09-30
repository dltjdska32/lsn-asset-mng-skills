"""CA01/02/06 bounded acceptance; synthetic temporary run DBs only.

Run: python -X utf8 -B CONTRACT-AUDIT-03-probes.py --repo PATH
Never patches target classes, writes target files, or alters earlier probes.
BLOCKED means API/environment failure, never a successful rejection.
Holding13F is a genuine supported DTO control for generic ledger tests when
the separate MarketQuote registration path is blocked. It is not a quote shim.
"""
from __future__ import annotations
import argparse
import importlib
import json
import socket
import sqlite3
import sys
import tempfile
import traceback
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path
from urllib.parse import unquote, urlparse

sys.dont_write_bytecode = True
C = S = M = ROOT = None
CASES = []
PURPOSE = "INSTITUTIONAL_COMPARE"
NOW = datetime(2026, 9, 23, 0, 0, tzinfo=timezone.utc)

def io_guard(event, args):
    if event.startswith("socket.") and event in {"socket.connect", "socket.getaddrinfo"}:
        raise RuntimeError("Network prohibited")
    if event == "sqlite3.connect":
        db = str(args[0])
        if db == ":memory:":  # schema validation uses ephemeral in-memory SQLite
            return
        if db.startswith("file:"):
            db = unquote(urlparse(db).path)
            if len(db) > 2 and db[0] == "/" and db[2] == ":":
                db = db[1:]
        if ROOT is None or not Path(db).resolve().is_relative_to(ROOT):
            raise RuntimeError("SQLite outside synthetic temporary root prohibited")

sys.addaudithook(io_guard)

def case(fn):
    CASES.append(fn)
    return fn

def reject(call, errors=None):
    if errors is None:
        errors = (C.InputIntegrityError, C.ContractValidationError, C.EvidenceNotFoundError)
    try:
        call()
    except errors as exc:
        return type(exc).__name__
    raise AssertionError("Invalid input accepted")

def manager(name):
    m = M(ROOT / name, "run-synthetic")
    report = m.create()
    assert report.valid, report.errors
    return m

def holding(m, eid="h1", value="20"):
    h = C.Holding13F(eid, "filing-fixture", "CUSIP", "fixture", D("1"),
                     D(value), D(value), D("1"), value_scale=D("1"),
                     mapped_instrument_id="TEST")
    m.add_contract_evidence(evidence_id=eid, contract_envelope=C.encode_envelope("Holding13F", h))
    return C.BoundSlotInput("value", D(value), "CURRENCY", "USD", eid)

def request(as_of="2026-09-23T00:00:00+00:00", metric="holding_value", slot_id="value"):
    spec = C.SlotSpec(slot_id, PURPOSE, "TEST", metric, "MONEY", currency="USD")
    return C.SelectionRequest("req", PURPOSE, "TEST", (spec,), as_of=as_of)

def snap(m, slot, version=1, req=None):
    req = req or request()
    return C.SelectedInputSet.create(m.run_id, PURPOSE, version, [slot],
                                    instrument_id="TEST", request_hash=req.compute_request_hash())

def calc(m, s, slots=None, cid="calc"):
    return C.CalculationRecord.create(cid, m.run_id, "synthetic-identity", "identity", "1",
        "CALCULATED", s.slots if slots is None else slots, s.snapshot_hash,
        result_numeric=(s.slots if slots is None else slots)[0].canonical_value,
        result_unit="CURRENCY", result_currency="USD")

def fixture(name):
    m = manager(name)
    b = holding(m)
    s = snap(m, b)
    m.persist_contract_snapshot(s, expected_revision=0)
    return m, b, s

def seeded_read_fixture(name):
    """SQL seed for READ-boundary isolation, never a successful write-API claim.

    Uses a real registered Holding13F, real DTO/envelope/hash APIs, and a
    self-consistent ledger. Necessary because normal snapshot write is blocked.
    """
    m = manager(name)
    b = holding(m)
    s = snap(m, b)
    ledger = S.empty_contract_storage()
    ledger.update(latest_revision=1, latest_snapshot_hash=s.snapshot_hash,
        active_selections={s.active_key: s.snapshot_hash},
        history=[{"revision": 1, "previous_snapshot_hash": "", "snapshot_hash": s.snapshot_hash,
                  "envelope": C.encode_envelope("SelectedInputSet", s)}])
    write_meta(m, {C.CONTRACT_STORAGE_KEY: ledger})
    assert m.fetch_contract_snapshots() == (s,)
    return m, b, s

def empty_snapshot(m, version=1, req=None):
    req = req or C.SelectionRequest("req-empty", PURPOSE, "TEST", (), as_of=NOW.isoformat())
    return C.SelectedInputSet.create(m.run_id, PURPOSE, version, [], instrument_id="TEST",
                                    request_hash=req.compute_request_hash())

def read_meta(m):
    return json.loads(m.fetch_metadata()["metadata_json"])

def write_meta(m, meta):
    with closing(sqlite3.connect(m.database_path)) as db:
        db.execute("UPDATE run_metadata SET metadata_json=? WHERE run_id=?", (json.dumps(meta), m.run_id))
        db.commit()

def reopened(m):
    n = M(m.workspace_root, m.run_id)
    r = n.open()
    return n, r

@case
def exact_quote_registration_and_snapshot():
    m = manager("exact-quote")
    q = C.MarketQuote("q", "e", "TEST", "USD", D("10"), "REGULAR", NOW,
                      C.PublicAvailability.exact(NOW, locator="fixture://release"))
    assert C.decode_contract(C.encode_contract(q), expected_kind="MarketQuote") == q
    m.add_contract_evidence(evidence_id="e", contract_envelope=C.encode_envelope("MarketQuote", q))
    b = C.BoundSlotInput("price", D("10"), "CURRENCY", "USD", "e",
                         public_available_at=NOW.isoformat())
    s = C.SelectedInputSet.create(m.run_id, "CURRENT_PRICE", 1, [b], instrument_id="TEST")
    m.persist_contract_snapshot(s)
    assert m.fetch_contract_snapshots() == (s,)
    return "exact quote registration and snapshot roundtrip"

@case
def typed_holding_snapshot_reopen_control():
    m, b, s = fixture("typed-control")
    n, r = reopened(m)
    assert r.valid and n.fetch_contract_snapshots() == (s,)
    assert n.verify_contract_storage_integrity()
    return "genuine Holding13F registration -> snapshot -> reopen"

@case
def raw_metadata_cannot_impersonate_typed_evidence():
    m = manager("raw-forged")
    m.add_evidence(evidence_id="fake", evidence_type="raw", metadata={
        "canonical_payload": {"canonical_value": "999", "canonical_currency": "USD", "instrument_id": "TEST"}})
    b = C.BoundSlotInput("value", D("999"), "CURRENCY", "USD", "fake")
    return reject(lambda: m.persist_contract_snapshot(snap(m, b)))

@case
def incomplete_projection_cannot_authorize_value():
    m = manager("projection-missing")
    m.add_evidence(evidence_id="fake", evidence_type="raw", metadata={"canonical_payload": {"contract_kind": "MarketQuote"}})
    b = C.BoundSlotInput("value", D("999"), "CURRENCY", "USD", "fake")
    return reject(lambda: m.persist_contract_snapshot(snap(m, b)))

@case
def registered_identity_must_match_envelope():
    m = manager("identity")
    q = C.MarketQuote("q", "original", "TEST", "USD", D("20"), "REGULAR", NOW,
                      C.PublicAvailability.exact(NOW, locator="fixture://release"))
    def insert_and_bind():
        m.add_contract_evidence(evidence_id="different", contract_envelope=C.encode_envelope("MarketQuote", q))
        m.persist_contract_snapshot(snap(m, C.BoundSlotInput("value", D("20"), "CURRENCY", "USD", "different")))
    return reject(insert_and_bind)

def snapshot_mutation(name, **changes):
    m = manager(name)
    b = holding(m)
    return reject(lambda: m.persist_contract_snapshot(snap(m, replace(b, **changes))))

@case
def canonical_value_mismatch():
    return snapshot_mutation("value-bad", canonical_value=D("999"))

@case
def canonical_currency_mismatch():
    return snapshot_mutation("currency-bad", canonical_currency="KRW")

@case
def canonical_currency_omission():
    return snapshot_mutation("currency-missing", canonical_currency=None)

@case
def canonical_unit_mismatch():
    return snapshot_mutation("unit-bad", canonical_unit="THOUSAND_USD")

@case
def invented_public_time():
    return snapshot_mutation("public-bad", public_available_at="1900-01-01T00:00:00+00:00")

@case
def unresolved_eligibility():
    return snapshot_mutation("eligibility-bad", eligibility_id="nonexistent-eligible-decision")

@case
def invented_fingerprint():
    return snapshot_mutation("fingerprint-bad", input_fingerprint="not-derived-from-evidence")

@case
def instrument_mismatch():
    m = manager("instrument-bad")
    b = holding(m)
    s = C.SelectedInputSet.create(m.run_id, PURPOSE, 1, [b], instrument_id="OTHER")
    return reject(lambda: m.persist_contract_snapshot(s))

@case
def immutable_s1_s2_reopen():
    m, b, s1 = fixture("s1-s2")
    s2 = snap(m, holding(m, "h2", "30"), 2)
    m.persist_contract_snapshot(s2, expected_revision=1)
    n, r = reopened(m)
    assert r.valid and n.fetch_contract_snapshots() == (s1, s2)
    assert n.fetch_active_contract_snapshot(PURPOSE, instrument_id="TEST", request_hash=request().compute_request_hash()) == s2
    assert s1.slots[0].canonical_value == D("20")
    return "S1=20 preserved; S2=30 active after reopen"

@case
def actual_calculation_persist_replay():
    m, b, s = seeded_read_fixture("calc-positive")
    rec = calc(m, s)
    m.persist_contract_calculation(rec)
    n, r = reopened(m)
    assert r.valid and n.fetch_contract_calculations() == (rec,)
    assert n.fetch_contract_calculations()[0].result_numeric == s.slots[0].canonical_value
    return "identity formula replayed from immutable bound input"

@case
def atomic_snapshot_calculation_positive():
    m = manager("atomic-positive")
    s = empty_snapshot(m)
    rec = C.CalculationRecord.create("constant", m.run_id, "constant", "constant", "1",
                                    "CALCULATED", [], s.snapshot_hash, result_numeric=D("1"))
    m.persist_contract_snapshot(s, calculations=(rec,))
    assert m.fetch_contract_calculations() == (rec,)
    return "snapshot+calculation persisted atomically"

@case
def calculation_full_slot_match():
    m, b, s = seeded_read_fixture("calc-fields")
    changes = {"canonical_value": D("999"), "canonical_unit": "wrong", "canonical_currency": "KRW",
               "evidence_id": "different", "observation_id": "obs", "calculation_id": "upstream",
               "eligibility_id": "elig", "public_available_at": "1900-01-01T00:00:00+00:00",
               "input_fingerprint": "wrong"}
    for field, value in changes.items():
        bad = calc(m, s, [replace(b, **{field: value})], cid=field)
        reject(lambda: m.persist_contract_calculation(bad), (C.InputIntegrityError,))
    return "all 9 non-slot-id binding fields rejected when different"

@case
def historical_snapshot_reference_not_current():
    m, b, s1 = seeded_read_fixture("calc-ref")
    s2 = snap(m, holding(m, "h2", "30"), 2)
    meta = read_meta(m)
    ledger = meta[C.CONTRACT_STORAGE_KEY]
    ledger["history"].append({"revision": 2, "previous_snapshot_hash": s1.snapshot_hash,
        "snapshot_hash": s2.snapshot_hash, "envelope": C.encode_envelope("SelectedInputSet", s2)})
    ledger.update(latest_revision=2, latest_snapshot_hash=s2.snapshot_hash)
    ledger["active_selections"][s2.active_key] = s2.snapshot_hash
    write_meta(m, meta)
    bad = calc(m, s1, s2.slots)
    return reject(lambda: m.persist_contract_calculation(bad), (C.InputIntegrityError,))

@case
def transaction_rolls_back_invalid_calculation():
    m = manager("rollback")
    b = holding(m)
    s = snap(m, b)
    bad = calc(m, s, [replace(b, canonical_value=D("999"))])
    result = reject(lambda: m.persist_contract_snapshot(s, calculations=(bad,)), (C.InputIntegrityError,))
    assert m.fetch_contract_snapshots() == () and m.fetch_contract_calculations() == ()
    return result + "; no partial ledger write"

@case
def same_instrument_two_request_scopes():
    m = manager("scopes")
    r1 = C.SelectionRequest("req-empty", PURPOSE, "TEST", (), as_of=NOW.isoformat())
    r2 = replace(r1, as_of="2026-09-24T00:00:00+00:00")
    s1, s2 = empty_snapshot(m, 1, r1), empty_snapshot(m, 2, r2)
    assert r1.compute_request_hash() != r2.compute_request_hash()
    m.persist_contract_snapshot(s1)
    m.persist_contract_snapshot(s2)
    for req, s in ((r1, s1), (r2, s2)):
        assert m.fetch_active_contract_snapshot(PURPOSE, instrument_id="TEST", request_hash=req.compute_request_hash()) == s
    reject(lambda: m.fetch_active_contract_snapshot(PURPOSE, instrument_id="TEST"), (C.AmbiguousSnapshotError,))
    return "distinct hashes select distinct snapshots; unspecified request is ambiguous"

@case
def request_hash_requires_resolvable_descriptor():
    m = manager("request-descriptor")
    # No request descriptor with this identity exists in the run.
    s = C.SelectedInputSet.create(m.run_id, PURPOSE, 1, [], instrument_id="TEST", request_hash="unregistered-request")
    return reject(lambda: m.persist_contract_snapshot(s))

@case
def read_rejects_stale_snapshot_hash():
    m, b, s = seeded_read_fixture("hash-corrupt")
    meta = read_meta(m)
    meta[C.CONTRACT_STORAGE_KEY]["history"][0]["envelope"]["payload"]["slots"][0]["canonical_value"] = "999"
    write_meta(m, meta)
    n, r = reopened(m)
    result = reject(lambda: n.fetch_contract_snapshots(), (C.CorruptedStorageError,)) if r.valid else "open rejected"
    return result + f"; open.valid={r.valid}"

@case
def reopen_marks_corrupt_ledger_invalid():
    m = manager("open-corrupt")
    m.persist_contract_snapshot(empty_snapshot(m))
    meta = read_meta(m)
    meta[C.CONTRACT_STORAGE_KEY]["latest_revision"] = 999
    write_meta(m, meta)
    n, r = reopened(m)
    assert not r.valid, "open.valid=True for counter-tail corruption; typed read must be tested separately"
    return "reopen rejected"

@case
def read_rejects_wrong_scope_existing_pointer():
    m = manager("pointer-corrupt")
    r1 = C.SelectionRequest("req-empty", PURPOSE, "TEST", (), as_of=NOW.isoformat())
    r2 = replace(r1, as_of="2026-09-24T00:00:00+00:00")
    s1, s2 = empty_snapshot(m, 1, r1), empty_snapshot(m, 2, r2)
    m.persist_contract_snapshot(s1)
    m.persist_contract_snapshot(s2)
    meta = read_meta(m)
    meta[C.CONTRACT_STORAGE_KEY]["active_selections"][s1.active_key] = s2.snapshot_hash
    write_meta(m, meta)
    n, r = reopened(m)
    if not r.valid:
        return "open rejected"
    return reject(lambda: n.fetch_active_contract_snapshot(PURPOSE, instrument_id="TEST", request_hash=r1.compute_request_hash()),
                  (C.CorruptedStorageError, C.InputIntegrityError))

@case
def read_rechecks_evidence_binding():
    m, b, s = seeded_read_fixture("evidence-corrupt")
    with closing(sqlite3.connect(m.database_path)) as db:
        raw = db.execute("SELECT metadata_json FROM evidence WHERE evidence_id=?", (b.evidence_id,)).fetchone()[0]
        meta = json.loads(raw)
        meta["canonical_payload"]["canonical_value"] = "999"
        db.execute("UPDATE evidence SET metadata_json=? WHERE evidence_id=?", (json.dumps(meta), b.evidence_id))
        db.commit()
    n, r = reopened(m)
    if not r.valid:
        return "open rejected"
    return reject(lambda: n.fetch_contract_snapshots(), (C.CorruptedStorageError, C.InputIntegrityError))

@case
def read_rechecks_calculation_against_snapshot():
    m, b, s = seeded_read_fixture("calc-corrupt")
    # Deliberate corrupt DB fixture, not a claim that the write API accepted this.
    # Each object is self-consistent, but calculation input contradicts its snapshot.
    bad = calc(m, s, [replace(b, canonical_value=D("999"))])
    assert bad.verify_lineage()
    meta = read_meta(m)
    meta[C.CONTRACT_STORAGE_KEY]["calculations"] = [{"calculation_id": bad.calculation_id,
        "envelope": C.encode_envelope("CalculationRecord", bad)}]
    write_meta(m, meta)
    n, r = reopened(m)
    if not r.valid:
        return "open rejected"
    return reject(lambda: n.fetch_contract_calculations(), (C.CorruptedStorageError, C.InputIntegrityError))

@case
def seeded_read_control():
    m, b, s = seeded_read_fixture("seeded-control")
    n, r = reopened(m)
    assert r.valid and n.fetch_contract_snapshots() == (s,) and n.verify_contract_storage_integrity()
    return "SQL-seeded consistent typed ledger reads correctly; not write acceptance"

@case
def empty_scope_history_reopen_control():
    m = manager("empty-history")
    s1, s2 = empty_snapshot(m), empty_snapshot(m, 2)
    m.persist_contract_snapshot(s1)
    m.persist_contract_snapshot(s2)
    n, r = reopened(m)
    assert r.valid and n.fetch_contract_snapshots() == (s1, s2)
    return "empty S1/S2 history preserved; does not establish financial-input acceptance"

@case
def read_rejects_counter_tail_corruption():
    m = manager("counter-read")
    m.persist_contract_snapshot(empty_snapshot(m))
    meta = read_meta(m)
    meta[C.CONTRACT_STORAGE_KEY]["latest_revision"] = 999
    write_meta(m, meta)
    n, r = reopened(m)
    return "open rejected" if not r.valid else reject(lambda: n.fetch_contract_snapshots(), (C.CorruptedStorageError,))

def main():
    global C, S, M, ROOT
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", type=Path, required=True)
    args = ap.parse_args()
    sys.path.insert(0, str(args.repo.resolve() / "runtime"))
    try:
        C = importlib.import_module("investment_stack.contracts")
        S = importlib.import_module("investment_stack.contracts.storage")
        M = importlib.import_module("investment_stack.evidence.manager").RunDatabaseManager
    except Exception as exc:
        print(f"BLOCKED imports: {type(exc).__name__}: {exc}")
        return 2
    work = Path(__file__).resolve().parent.parent / "work"
    work.mkdir(exist_ok=True)
    totals = {"PASS": 0, "FAIL": 0, "BLOCKED": 0}
    print("repo:", args.repo.resolve())
    with tempfile.TemporaryDirectory(prefix="audit03-", dir=work) as temp:
        ROOT = Path(temp).resolve()
        for fn in CASES:
            try:
                detail = fn()
                status = "PASS"
            except AssertionError as exc:
                status, detail = "FAIL", str(exc)
            except C.ContractError as exc:
                status, detail = "FAIL", f"Unexpected contract rejection: {type(exc).__name__}: {exc}"
            except Exception as exc:
                frame = traceback.extract_tb(exc.__traceback__)[-1]
                status, detail = "BLOCKED", f"{type(exc).__name__}: {exc} ({Path(frame.filename).name}:{frame.lineno})"
            totals[status] += 1
            print(status, fn.__name__, "=>", detail)
    ROOT = None
    print("TOTAL", json.dumps(totals, sort_keys=True))
    print("Temporary synthetic databases cleaned up.")
    return int(bool(totals["FAIL"] or totals["BLOCKED"]))

if __name__ == "__main__":
    raise SystemExit(main())
