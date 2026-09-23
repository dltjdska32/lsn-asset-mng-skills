"""Bounded CA03/04/07 residual audit. Memory only; no storage audit.

python -B CONTRACT-AUDIT-02-probes.py --repo PATH
PASS = expected boundary/normal behavior; FAIL = observed semantic mismatch;
BLOCKED = API/environment failure (never accepted as validation rejection).
The original CONTRACT-AUDIT-01 probe is not modified.
"""
from __future__ import annotations

import argparse
import importlib
import json
import socket
import sqlite3
import sys
from dataclasses import fields, replace
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path

sys.dont_write_bytecode = True
CASES = []
c = a = p = None


def deny_io(*args, **kwargs):
    raise RuntimeError("Audit-02 prohibits database/network access")


socket.create_connection = deny_io
socket.socket.connect = deny_io
sqlite3.connect = deny_io


def case(area, expected):
    def register(fn):
        CASES.append((fn, area, expected))
        return fn
    return register


def rejects(call):
    # Only the documented validation family counts as correct rejection.
    # TypeError, KeyError, AttributeError, ImportError, etc. propagate as BLOCKED.
    try:
        result = call()
    except c.ContractValidationError as exc:
        return type(exc).__name__
    raise AssertionError(f"Accepted invalid contract: {result!r}")


def wire(kind, payload):
    return {"contract_version": c.CONTRACT_VERSION, "kind": kind, "payload": payload}


def decode(kind, payload):
    return c.decode_contract(wire(kind, payload), expected_kind=kind)


def pub():
    return c.PublicAvailability.exact(datetime(2026, 9, 23, tzinfo=timezone.utc), locator="fixture://release")


def quote_payload():
    return {
        "quote_id": "q", "evidence_id": "e", "instrument_id": "TEST", "currency": "USD",
        "price": "10", "quote_kind": "REGULAR", "retrieved_at": "2026-09-23T09:00:00+00:00",
        "public_availability": c.to_canonical_dict(pub()), "is_trade": False,
    }


def calc(status="CALCULATED", **kw):
    return c.CalculationRecord.create(
        "calc", "run", "fixture", "fixture-formula", "1", status, [], "synthetic-snapshot", **kw
    )


def fact(dimension="MONEY", raw_unit="USD thousand", currency="USD", metric="revenue"):
    return c.FinancialFact(
        "f", "e", "TEST", "fixture-taxonomy", "fixture-tag", metric,
        D("2"), raw_unit, c.ScaleStatus.VALID, D("1000"), D("2000"),
        dimension, currency, "DURATION", "2025-01-01", "2025-12-31", 365,
        2025, "FY", "ANNUAL", "CONSOLIDATED", "IFRS", "REPORTED", pub(),
    )


def observation():
    return p.ProviderObservation(
        "financial", "fixture", "fixture://source", 4, "fixture", value="10", unit="USD",
        currency="USD", instrument_id="TEST", official_confirmation_status="NEWS_REPORTED",
        event_cluster_id="cluster", relevance_reason="fixture relevance",
    )


@case("CA03/control", "Wrong PublicAvailability nested kind is rejected")
def wrong_nested_kind():
    payload = quote_payload()
    payload["public_availability"] = c.encode_envelope(
        "GateDecision", c.GateDecision("g", "TRADING", "p", "1", "h", "DISABLED")
    )
    return rejects(lambda: decode("MarketQuote", payload))


@case("CA03/control", "Unknown nested PublicAvailability field is rejected")
def unknown_nested_field():
    payload = quote_payload()
    payload["public_availability"]["assume_approved"] = True
    return rejects(lambda: decode("MarketQuote", payload))


@case("CA03", "Duplicate is_approved JSON keys must not choose the last approval")
def duplicate_json_approval():
    document = ('{"contract_version":"' + c.CONTRACT_VERSION + '","kind":"CalculationAssumption",'
                '"payload":{"assumption_id":"a","name":"rate","value":"1",'
                '"is_approved":false,"is_approved":true}}')
    return rejects(lambda: c.decode_contract(document, expected_kind="CalculationAssumption"))


@case("CA03", "Nonstandard raw NaN JSON token is rejected before conversion to str")
def nonfinite_json_assumption():
    document = ('{"contract_version":"' + c.CONTRACT_VERSION + '","kind":"CalculationAssumption",'
                '"payload":{"assumption_id":"a","name":"rate","value":NaN,"unit":"ratio",'
                '"is_approved":true}}')
    return rejects(lambda: c.decode_contract(document, expected_kind="CalculationAssumption"))


@case("CA03/control", "Numeric quote NaN string is rejected")
def nonfinite_price():
    payload = quote_payload()
    payload["price"] = "NaN"
    return rejects(lambda: decode("MarketQuote", payload))


@case("CA03", "Unknown ProviderObservation field is rejected, not silently discarded")
def unknown_provider_field():
    payload = c.to_canonical_dict(observation())
    payload["unexpected_semantic_field"] = "x"
    return rejects(lambda: decode("ProviderObservation", payload))


@case("CA03", "Bool source tier cannot become authoritative integer 1")
def bool_source_tier():
    payload = c.to_canonical_dict(observation())
    payload["source_tier"] = True
    return rejects(lambda: decode("ProviderObservation", payload))


@case("CA03", "String false is_trade is not converted to True")
def string_false_quote():
    payload = quote_payload()
    payload["is_trade"] = "false"
    return rejects(lambda: decode("MarketQuote", payload))


@case("CA03", "String false is_amended is not converted to True")
def string_false_holding_set():
    return rejects(lambda: decode("HoldingSet13F", {
        "filing_id": "f", "manager_cik": "fixture", "report_period": "2026-06-30",
        "holdings": [], "total_eligible_value": "0", "is_amended": "false",
    }))


@case("CA03/control", "Valid quote including false boolean roundtrips exactly")
def quote_roundtrip():
    q = decode("MarketQuote", quote_payload())
    out = c.decode_contract(c.encode_contract(q), expected_kind="MarketQuote")
    assert out == q and out.is_trade is False, (q, out)
    return "equal, is_trade=False"


@case("CA04", "Trailing whitespace in policy purpose cannot turn disabled trading into conditional")
def purpose_spelling_bypass():
    base = c.GateDecision("g", "TRADING", "p", "1", "h", "CONDITIONAL")
    try:
        spaced = c.GateDecision("g2", "TRADING ", "p", "1", "h", "CONDITIONAL")
    except c.ContractValidationError as exc:
        return type(exc).__name__
    assert str(spaced.state) == "DISABLED", f"TRADING={base.state}; TRADING-space={spaced.state}"
    return str(spaced.state)


@case("CA04", "13F aggregate needs validation; approval alone cannot activate it")
def unvalidated_13f_enabled():
    try:
        g = c.GateDecision("g", "13F_AGGREGATE", "policy", "1", "h", "ENABLED",
                           approval_ref="approved-fixture", validation_ref=None)
    except c.ContractValidationError as exc:
        return type(exc).__name__
    assert str(g.state) == "DISABLED", f"state={g.state}; validation={g.validation_ref}"
    return str(g.state)


@case("CA04/control", "Valid approval+validation should not depend on policy ID containing a word")
def policy_id_word_false_positive():
    g = c.GateDecision("g", "13F_AGGREGATE", "previously-unapproved-policy", "1", "h", "ENABLED",
                       approval_ref="approved-fixture", validation_ref="validated-fixture")
    assert str(g.state) == "ENABLED", f"ID substring changed valid policy state to {g.state}"
    return str(g.state)


@case("CA04/contract-gap", "Typed gate reference must connect policy-sensitive calculation to its gate")
def gate_calculation_link():
    disabled = c.GateDecision("g", "13F_AGGREGATE", "p", "1", "h", "DISABLED")
    record = calc(result_numeric=D("5"), result_payload={"gate_ref": disabled.gate_id,
                                                        "score_status": "UNVALIDATED"})
    names = {f.name for f in fields(record)}
    assert names.intersection({"gate", "gate_ref", "gate_refs", "gate_decision", "gate_decisions"}), (
        f"No typed gate binding; disabled={disabled.state}, record={record.status}, "
        f"numeric={record.result_numeric}, free payload={record.result_payload}"
    )
    # A future field appearing is not sufficient to prove a validator works.
    raise NotImplementedError("New gate API: adapt this probe to bind disabled gate explicitly")


@case("CA04/control", "Simple arithmetic remains CALCULATED without investment-policy approval")
def ordinary_arithmetic():
    record = calc(result_numeric=D("2") + D("3"), result_unit="count")
    assert record.status == "CALCULATED" and record.result_numeric == D("5")
    assert record.verify_lineage()
    return "CALCULATED 5"


@case("CA04/control", "Explicit unapproved analyst assumption is allowed as explanatory CONDITIONAL scenario")
def explicit_scenario():
    assumption = c.CalculationAssumption("a", "scenario_growth", "0.01", "ratio",
                                         kind="ANALYST_SCENARIO", rationale="explicit synthetic scenario")
    record = calc("CONDITIONAL", assumptions=[assumption], result_numeric=D("101"))
    assert record.status == "CONDITIONAL" and record.verify_lineage()
    return "CONDITIONAL 101"


@case("CA04", "UNAVAILABLE cannot hide an output numeric under a nested generic key")
def nested_unavailable_numeric():
    return rejects(lambda: calc("UNAVAILABLE", result_payload={"details": {"entry": D("100")}}))


@case("CA04", "Renaming output to a Korean or neutral numeric-string key cannot evade unavailable")
def localized_unavailable_numeric():
    return rejects(lambda: calc("UNAVAILABLE", result_payload={"진입가": "100"}))


@case("CA04/control", "UNAVAILABLE may carry textual price_error diagnostic")
def unavailable_text_diagnostic():
    record = calc("UNAVAILABLE", result_payload={"price_error": "source unavailable"})
    assert record.result_numeric is None and record.verify_lineage()
    return "diagnostic accepted"


@case("immutability", "Caller-owned original dict does not mutate record payload")
def copied_input_control():
    original = {"details": {"value": "1"}}
    record = calc(result_numeric=D("1"), result_payload=original)
    original["details"]["value"] = "999"
    assert record.result_payload["details"]["value"] == "1" and record.verify_lineage()
    return "source copy isolated"


@case("immutability", "Direct record nested payload mutation must be prevented")
def direct_payload_mutation():
    record = calc(result_numeric=D("1"), result_payload={"details": {"value": "1"}})
    try:
        record.result_payload["details"]["value"] = "999"
    except (TypeError, AttributeError) as exc:
        # These exceptions count only for the specific mutation operation.
        assert record.result_payload["details"]["value"] == "1"
        return "mutation rejected: " + type(exc).__name__
    raise AssertionError(f"Record mutated; verify_lineage={record.verify_lineage()}")


@case("CA07", "ProviderObservation confirmation/cluster/relevance survive typed roundtrip")
def provider_semantic_roundtrip():
    obs = observation()
    out = c.decode_contract(obs.to_contract_envelope(), expected_kind="ProviderObservation")
    assert (out.official_confirmation_status, out.event_cluster_id, out.relevance_reason) == (
        obs.official_confirmation_status, obs.event_cluster_id, obs.relevance_reason
    ), (out.official_confirmation_status, out.event_cluster_id, out.relevance_reason)
    return "semantic fields preserved"


@case("CA07", "ProviderObservation classmethod and typed decoder agree")
def provider_decoders_agree():
    env = observation().to_contract_envelope()
    left = p.ProviderObservation.from_contract_envelope(env)
    right = c.decode_contract(env, expected_kind="ProviderObservation")
    assert left == right, "Two public decoders produce different confirmation/provenance"
    return "same object semantics"


@case("CA07/control", "Normalized MONEY adapter uses base currency unit")
def money_unit_control():
    out = a.fact_to_observation(fact())
    assert out.value == "2000" and out.unit == "USD", (out.value, out.unit)
    return "2000 USD"


@case("CA07", "Normalized SHARES cannot keep thousand-shares unit")
def normalized_shares_unit():
    out = a.fact_to_observation(fact("SHARES", "thousand shares", None, "shares_outstanding"))
    assert out.unit in {"shares", "SHARES"}, (out.value, out.unit)
    return str(out.unit)


@case("CA07", "Normalized per-share money cannot keep thousand-money/share unit")
def normalized_eps_unit():
    out = a.fact_to_observation(fact("MONEY_PER_SHARE", "USD thousand/share", "USD", "eps"))
    assert out.unit in {"USD/share", "USD/shares"}, (out.value, out.unit)
    return str(out.unit)


@case("CA07", "PublicAvailability locator/evidence identity must survive quote projection")
def quote_provenance_projection():
    q = decode("MarketQuote", quote_payload())
    out = a.quote_to_observation(q)
    md = out.metadata
    has_source = out.source_url == q.public_availability.source_locator or any(
        key in md for key in ("public_availability", "contract_envelope", "typed_payload")
    )
    has_evidence = md.get("evidence_id") == q.evidence_id or any(
        key in md for key in ("contract_envelope", "typed_payload")
    )
    assert has_source and has_evidence, (out.source_url, md)
    return "provenance retained"


@case("CA07/control", "13F PRN and voting semantics survive exact typed roundtrip")
def holding_roundtrip_control():
    h = c.Holding13F("h", "f", "cusip", "fixture", D("1"), D("2"), D("2"), D("1"),
                     quantity_type="PRN", value_scale=D("1"), voting_sole=D("1"))
    out = c.decode_contract(c.encode_contract(h), expected_kind="Holding13F")
    assert out == h, (h, out)
    return "equal, PRN/voting retained"


def main():
    global c, a, p
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(args.repo.resolve() / "runtime"))
    c = importlib.import_module("investment_stack.contracts")
    a = importlib.import_module("investment_stack.providers.contract_adapters")
    p = importlib.import_module("investment_stack.providers.models")
    print("repo:", args.repo.resolve(), "contract:", c.CONTRACT_VERSION)
    totals = {"PASS": 0, "FAIL": 0, "BLOCKED": 0}
    for fn, area, expected in CASES:
        try:
            detail = fn()
            status = "PASS"
        except AssertionError as exc:
            status, detail = "FAIL", str(exc)
        except c.ContractValidationError as exc:
            # A valid control case being rejected is a semantic FAIL, not a PASS.
            status, detail = "FAIL", f"Unexpected validation rejection: {type(exc).__name__}: {exc}"
        except Exception as exc:
            status, detail = "BLOCKED", f"{type(exc).__name__}: {exc}"
        totals[status] += 1
        print(f"{status} {fn.__name__} [{area}] expected={expected}")
        print("  observed:", detail)
    print("TOTAL", json.dumps(totals, sort_keys=True))
    return int(bool(totals["FAIL"] or totals["BLOCKED"]))


if __name__ == "__main__":
    raise SystemExit(main())
