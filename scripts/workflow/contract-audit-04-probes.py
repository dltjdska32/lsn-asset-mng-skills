"""Bounded memory-only typed gate audit for 49837ea; no DB/network/patching.

python -X utf8 -B CONTRACT-AUDIT-04-probes.py --repo PATH
Negative rejection counts only ContractValidationError; unexpected API errors
are BLOCKED. Encoding/decoding tests stored representation, not DB persistence.
"""
from __future__ import annotations
import argparse
import importlib
import json
import sys
import traceback
from decimal import Decimal as D
from pathlib import Path

sys.dont_write_bytecode = True
C = None
CASES = []

def deny_io(event, args):
    if event == "sqlite3.connect" or event in {"socket.connect", "socket.getaddrinfo"}:
        raise RuntimeError("AUDIT-04 prohibits all DB and network access")

sys.addaudithook(deny_io)

def case(fn):
    CASES.append(fn)
    return fn

def reject(call):
    try:
        result = call()
    except C.ContractValidationError as exc:
        return type(exc).__name__
    raise AssertionError(f"Invalid use accepted: consumable={getattr(result, 'is_consumable', None)}")

def gate(state="ENABLED", purpose="13F_WEIGHT", approved=True, validated=True):
    return C.GateDecision("gate", purpose, "policy-fixture", "1", "hash-fixture", state,
        approval_ref="approval-fixture" if approved else None,
        validation_ref="validation-fixture" if validated else None)

def record(formula="13f_weight", requirement="POLICY_VERIFICATION", purpose="13F_WEIGHT",
           refs=("gate",), status="CALCULATED", outputs=True, assumptions=()):
    return C.CalculationRecord.create("calc", "run-synthetic", "synthetic-weight", formula, "1", status,
        [], "synthetic-snapshot", gate_refs=refs, requirement=requirement, purpose=purpose,
        typed_outputs=[C.TypedOutput("WEIGHT", D("0.2"), "ratio")] if outputs else [],
        assumptions=assumptions)

def consume(rec, *gates):
    assert rec.verify_lineage(), "probe constructed invalid lineage"
    return C.validate_calculation_for_use(rec, registered_gates=gates)

@case
def disabled_gate_consumer_rejects():
    return reject(lambda: consume(record(), gate("DISABLED")))

@case
def disabled_gate_after_roundtrip_rejects():
    rec = C.decode_contract(C.encode_contract(record()), expected_kind="CalculationRecord")
    g = C.decode_contract(C.encode_contract(gate("DISABLED")), expected_kind="GateDecision")
    assert rec.gate_refs == ("gate",) and rec.verify_lineage()
    return reject(lambda: consume(rec, g))

@case
def validated_gate_consumable_control():
    rec = record()
    result = consume(rec, gate())
    assert result.is_consumable and result.outputs == rec.typed_outputs
    assert str(result.requirement) == "POLICY_VERIFICATION"
    return "validated fixture gate -> consumable WEIGHT 0.2"

@case
def unapproved_13f_rejects():
    g = gate("CONDITIONAL", approved=False, validated=False)
    assert str(g.state) == "DISABLED"
    return reject(lambda: consume(record(), g))

@case
def approved_but_unvalidated_13f_rejects():
    g = gate(validated=False)
    assert str(g.state) == "DISABLED"
    return reject(lambda: consume(record(), g))

@case
def unregistered_gate_rejects():
    return reject(lambda: consume(record()))

@case
def unrelated_gate_purpose_rejects():
    return reject(lambda: consume(record(), gate(purpose="UNRELATED_DIAGNOSTIC")))

@case
def renamed_formula_cannot_lower_13f_requirement():
    # Same purpose, output, gate and formula version; only the formula ID/declared
    # requirement differ. A closed trusted mapping must decide its requirement.
    rec = record(formula="portfolio_weight_v2", requirement="ARITHMETIC")
    return reject(lambda: consume(rec, gate("DISABLED")))

@case
def known_13f_formula_ignores_lower_requirement():
    return reject(lambda: consume(record(requirement="ARITHMETIC"), gate("DISABLED")))

@case
def ordinary_arithmetic_control():
    rec = C.CalculationRecord.create("sum", "run-synthetic", "sum", "sum", "1", "CALCULATED",
        [], "synthetic-snapshot", result_numeric=D("5"), result_unit="count",
        typed_outputs=[C.TypedOutput("ARITHMETIC_RESULT", D("5"), "count")])
    result = consume(rec)
    assert result.is_consumable and result.outputs[0].value == D("5")
    return "2+3 synthetic result remains consumable without policy gate"

@case
def explicit_scenario_control():
    assumption = C.CalculationAssumption("a", "growth", "0.01", "ratio",
        kind="ANALYST_SCENARIO", rationale="explicit synthetic scenario", is_approved=False)
    rec = C.CalculationRecord.create("scenario", "run-synthetic", "scenario", "scenario_growth", "1",
        "CONDITIONAL", [], "synthetic-snapshot", assumptions=[assumption],
        typed_outputs=[C.TypedOutput("SCENARIO_VALUE", D("101"), "USD", "USD")])
    result = consume(rec)
    assert result.is_consumable and str(result.record.status) == "CONDITIONAL"
    return "explicit unapproved analyst scenario remains CONDITIONAL"

@case
def unavailable_not_consumable_control():
    result = consume(record(status="UNAVAILABLE", outputs=False), gate("DISABLED"))
    assert not result.is_consumable and result.outputs == ()
    return "UNAVAILABLE produces no consumable outputs"

def main():
    global C
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", type=Path, required=True)
    args = ap.parse_args()
    sys.path.insert(0, str(args.repo.resolve() / "runtime"))
    try:
        C = importlib.import_module("investment_stack.contracts")
    except Exception as exc:
        print(f"BLOCKED imports: {type(exc).__name__}: {exc}")
        return 2
    print("repo:", args.repo.resolve())
    totals = {"PASS": 0, "FAIL": 0, "BLOCKED": 0}
    for fn in CASES:
        try:
            detail = fn()
            status = "PASS"
        except AssertionError as exc:
            status, detail = "FAIL", str(exc)
        except C.ContractValidationError as exc:
            status, detail = "FAIL", f"Unexpected rejection: {type(exc).__name__}: {exc}"
        except Exception as exc:
            frame = traceback.extract_tb(exc.__traceback__)[-1]
            status, detail = "BLOCKED", f"{type(exc).__name__}: {exc} ({Path(frame.filename).name}:{frame.lineno})"
        totals[status] += 1
        print(status, fn.__name__, "=>", detail)
    print("TOTAL", json.dumps(totals, sort_keys=True))
    return int(bool(totals["FAIL"] or totals["BLOCKED"]))

if __name__ == "__main__":
    raise SystemExit(main())
