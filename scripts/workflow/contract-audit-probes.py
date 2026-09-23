"""Read-only, memory-only contract acceptance probes for snapshot 73d376e.

Run with Python -B CONTRACT-AUDIT-01-probes.py [--repo PATH].
PASS means the stated required boundary holds; FAIL reproduces a finding;
BLOCKED means an API/import mismatch prevented testing that boundary.
No runtime source edits, DB access, network, or generated output files.
Numbers are synthetic fixtures, not investment policy recommendations.
"""
from __future__ import annotations

import argparse
import importlib
import json
import socket
import sqlite3
import sys
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path

sys.dont_write_bytecode = True


def deny_io(*args, **kwargs):
    raise RuntimeError("This probe prohibits network and database access")


socket.create_connection = deny_io
socket.socket.connect = deny_io
sqlite3.connect = deny_io
PROBES = []
c = None


def probe(area, expected):
    def register(fn):
        PROBES.append((fn, area, expected))
        return fn
    return register


def decode(kind, payload):
    return c.decode_contract(c.encode_envelope(kind, payload), expected_kind=kind)


def must_reject(fn):
    try:
        fn()
    except c.ContractError:
        return
    raise AssertionError("Invalid input was accepted instead of ContractError")


def availability():
    return c.PublicAvailability.exact(
        datetime(2026, 9, 23, tzinfo=timezone.utc), locator="fixture"
    )


def fact():
    return c.FinancialFact(
        "f", "e", "TEST", "gaap", "Revenue", "revenue",
        D("2"), "USD million", c.ScaleStatus.VALID, D("1000000"), D("2000000"),
        "MONEY", "USD", "DURATION", "2025-01-01", "2025-12-31", 365,
        2025, "FY", "ANNUAL", "CONSOLIDATED", "US-GAAP", "REPORTED", availability(),
    )


def holding(**kwargs):
    return c.Holding13F("h", "filing", "cusip", "Issuer", D("1"), D("2"),
                        D("2"), D("1"), **kwargs)


def bar():
    return c.Bar(
        "b", "e", "TEST", "1h", "2026-09-23",
        datetime(2026, 9, 23, 9, tzinfo=timezone.utc),
        datetime(2026, 9, 23, 10, tzinfo=timezone.utc), "UTC",
        D("1"), D("2"), D("1"), D("2"), D("0"), "USD", availability(),
        is_complete=False,
    )


@probe("COMMON_CODEC", "String 'false' must not become approved True")
def string_false_approval():
    must_reject(lambda: decode("CalculationAssumption", {
        "assumption_id": "a", "name": "unapproved", "value": "1",
        "is_approved": "false",
    }))


@probe("COMMON_CODEC", "String 'false' is not a wire bool for is_complete")
def string_false_coverage():
    must_reject(lambda: decode("CoverageDecision", {
        "request_id": "r", "fulfilled_slots": [], "missing_slots": ["price"],
        "is_complete": "false", "unknown_rule": "ignore",
    }))


@probe("COMMON_CONTRACT", "Missing required slot and is_complete=True cannot coexist")
def contradictory_coverage():
    must_reject(lambda: decode("CoverageDecision", {
        "request_id": "r", "fulfilled_slots": [], "missing_slots": ["price"],
        "conflicted_slots": [], "is_complete": True,
    }))


@probe("COMMON_CODEC", "MarketQuote requires PublicAvailability, not another registered kind")
def wrong_nested_kind():
    gate = c.GateDecision("g", "TRADING", "unapproved", "1", "hash", "CONDITIONAL")
    must_reject(lambda: decode("MarketQuote", {
        "quote_id": "q", "evidence_id": "e", "instrument_id": "TEST",
        "currency": "USD", "price": "1", "quote_kind": "REGULAR",
        "retrieved_at": "2026-09-23T09:00:00+00:00",
        "public_availability": c.encode_envelope("GateDecision", gate),
    }))


@probe("COMMON_CODEC", "Unknown enum/date and bool duration cannot form a valid SlotSpec")
def invalid_slot_wire():
    must_reject(lambda: decode("SlotSpec", {
        "slot_id": "s", "purpose": "ALIEN", "instrument_id": "TEST",
        "metric": "revenue", "dimension": "ALIEN", "target_period_start": "bad",
        "target_period_end": "worse", "duration_days": True,
    }))


@probe("COMMON_SLOT_PREDICATE", "Required instrument identity must not match None")
def missing_instrument():
    s = c.SlotSpec("s", "FINANCIAL_CALC", "TEST", "revenue", "MONEY", "USD")
    matched, reason = s.matches_candidate(candidate_currency="USD", candidate_dimension="MONEY")
    assert matched is False, (matched, reason)


@probe("COMMON_GATE", "Unapproved TRADING policy needs disabled/rejected gate, not bare CONDITIONAL")
def unapproved_conditional_gate():
    try:
        g = c.GateDecision("g", "TRADING", "unapproved", "1", "hash", "CONDITIONAL")
    except c.ContractError:
        return
    assert str(g.state) == "DISABLED", "Unapproved policy accepted as bare CONDITIONAL"


@probe("COMMON_OUTPUT_CONTRACT", "UNAVAILABLE must not carry a consumable action price")
def unavailable_action_payload():
    must_reject(lambda: c.CalculationRecord.create(
        "u", "run", "model", "f", "1", "UNAVAILABLE", [], "snapshot",
        result_payload={"buy_price": "100"},
    ))


@probe("COMMON_SET_VS_EVALUATOR", "Raw invalid data may survive, but cannot declare validated coverage")
def invalid_raw_promoted_to_coverage():
    # Constructor rejection is one possible design; preservation with no eligibility
    # is also valid. This does NOT require deleting/rejecting all raw invalid facts.
    try:
        invalid = replace(fact(), explicit_scale=c.ScaleStatus.INVALID,
                          normalized_value=D("999"), currency="JPY",
                          period_start=None, period_end="not-a-date", duration_days=None)
        other = replace(fact(), fact_id="g", evidence_id="e2",
                        canonical_metric="operating_income", reporting_frequency="QUARTER",
                        period_start="2026-04-01", period_end="2026-06-30", duration_days=91)
        fs = c.FinancialSet.create("set", "TEST", "USD", [invalid, other])
    except c.ContractError:
        return
    assert "revenue" not in fs.covered_metrics, (
        "Collection promoted to covered metrics without coherence/eligibility receipt",
        fs.covered_metrics,
    )


@probe("COMMON_STORAGE_CODEC", "Unsupported schema_version must be rejected")
def unknown_storage_version():
    must_reject(lambda: c.extract_contract_storage(json.dumps({c.CONTRACT_STORAGE_KEY: {
        "schema_version": "999", "latest_revision": 10, "history": [],
        "active_selections": {"PRICE": "missing"},
    }})))


@probe("COMMON_STORAGE_CODEC", "Present null namespace is corrupted, not an empty legacy ledger")
def null_storage_namespace():
    must_reject(lambda: c.extract_contract_storage(json.dumps({c.CONTRACT_STORAGE_KEY: None})))


@probe("COMMON_ADAPTER", "Normalized value must carry canonical unit, not raw million unit")
def normalized_fact_unit():
    adapters = importlib.import_module("investment_stack.providers.contract_adapters")
    obs = adapters.fact_to_observation(fact())
    assert D(obs.value) == D("2000000") and obs.unit == "USD", (obs.value, obs.unit)


@probe("COMMON_ADAPTER", "Bar close is price; it must not carry volume unit SHARES")
def bar_price_unit():
    adapters = importlib.import_module("investment_stack.providers.contract_adapters")
    obs = adapters.bar_to_observation(bar())
    assert obs.unit in {"USD", "USD/share", "PRICE"}, obs.unit


@probe("COMMON_13F_CODEC", "Non-null voting fields must survive encode/decode exactly")
def voting_roundtrip():
    h = holding(value_scale=D("1"), voting_sole=D("1"),
                voting_shared=D("2"), voting_none=D("3"))
    out = c.decode_contract(c.encode_contract(h), expected_kind="Holding13F")
    assert (out.voting_sole, out.voting_shared, out.voting_none) == (D("1"), D("2"), D("3")), out


@probe("COMMON_13F_ADAPTER", "PRN/SH quantity basis must survive the provider bridge")
def quantity_type_preserved():
    adapters = importlib.import_module("investment_stack.providers.contract_adapters")
    obs = adapters.holding_to_observation(holding(quantity_type="PRN", value_scale=D("1")))
    assert obs.metadata.get("quantity_type") == "PRN", obs.metadata.get("quantity_type")


@probe("COMMON_13F_CONTRACT", "No source mapping means no invented scale=1000")
def no_implicit_13f_scale():
    try:
        h = holding()
    except c.ContractError:
        return
    assert h.value_scale is None, h.value_scale


@probe("COMMON_SET_CONTRACT", "A validated daily BarSet cannot contain hourly bars")
def bar_interval_scope():
    must_reject(lambda: c.BarSet.create("TEST", "1d", "USD", "RAW", [bar()]))


@probe("COMMON_HASH_CONTRACT", "Purpose/public version/fingerprint changes must alter semantic identity")
def snapshot_semantic_scope():
    s = c.BoundSlotInput("price", D("1"), "USD", "USD", "e")
    one = c.SelectedInputSet.create("run", "CURRENT_PRICE", 1, [s])
    two = c.SelectedInputSet.create("run", "FINANCIAL_CALC", 1, [replace(
        s, public_available_at="2999-01-01T00:00:00Z", input_fingerprint="different"
    )])
    assert one.semantic_hash() != two.semantic_hash(), "Different semantics share hash"


@probe("KNOWN_IMPORT_LIMIT", "Manager must import before real run DB integrity probes are possible")
def manager_import_boundary():
    importlib.import_module("investment_stack.evidence.manager")


def main():
    global c
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path,
                        default=Path("C:/Users/lsn/lsn-asset-mng-worktrees/contract-audit"))
    args = parser.parse_args()
    sys.path.insert(0, str(args.repo.resolve() / "runtime"))
    c = importlib.import_module("investment_stack.contracts")
    print("repo:", args.repo.resolve())
    print("contract_version:", c.CONTRACT_VERSION)
    totals = {"PASS": 0, "FAIL": 0, "BLOCKED": 0}
    for fn, area, expected in PROBES:
        detail = ""
        try:
            fn()
            status = "PASS"
        except AssertionError as exc:
            status, detail = "FAIL", str(exc)
        except Exception as exc:
            status, detail = "BLOCKED", f"{type(exc).__name__}: {exc}"
        totals[status] += 1
        print(f"{status} {fn.__name__} [{area}] expected={expected}")
        if detail:
            print("  observed:", detail)
    print("TOTAL", json.dumps(totals, sort_keys=True))
    return 0 if totals["FAIL"] == totals["BLOCKED"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
