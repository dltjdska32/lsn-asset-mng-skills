from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from decimal import Decimal as D
from pathlib import Path

from investment_stack.calculations.valuation import DcfAssumptions, EquityValuationAnalyzer
from investment_stack.decisions.policy_b_market import load_policy_b_market_evidence


AS_OF = "2026-09-28T12:00:00+00:00"


def make_db(path: Path, *, status: str = "FRESH", evidence_value: str = "100", market_value: str = "100", published: str = "2026-09-28T11:00:00+00:00") -> None:
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE run_metadata(run_id TEXT, analysis_as_of TEXT);
        CREATE TABLE evidence(evidence_id TEXT, run_id TEXT, evidence_type TEXT,
          instrument_id TEXT, metric TEXT, value_text TEXT, unit TEXT, currency TEXT,
          observed_at TEXT, published_at TEXT, freshness_status TEXT, selection_state TEXT,
          source_uri TEXT, source_name TEXT, retrieved_at TEXT);
        CREATE TABLE market_observations(observation_id TEXT, run_id TEXT, evidence_id TEXT,
          instrument_id TEXT, observed_at TEXT, value_numeric NUMERIC, unit TEXT,
          metadata_json TEXT, currency TEXT, claimed_market_time TEXT, market_session_date TEXT,
          provider_id TEXT, freshness_status TEXT);
        CREATE TABLE freshness_assessments(freshness_id TEXT, run_id TEXT, evidence_id TEXT,
          status TEXT, assessed_at TEXT, details_json TEXT);
        CREATE TABLE calculations(calculation_id TEXT, run_id TEXT, calculation_name TEXT,
          formula TEXT, inputs_json TEXT, result_json TEXT, created_at TEXT);
    """)
    connection.execute("INSERT INTO run_metadata VALUES (?, ?)", ("r1", AS_OF))
    connection.execute(
        "INSERT INTO evidence (evidence_id,run_id,evidence_type,instrument_id,metric,value_text,unit,currency,observed_at,published_at,freshness_status,selection_state) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("e1", "r1", "market", "ABC", "current_price", evidence_value, "USD/share", "USD",
         "2026-09-28T11:00:00+00:00", published, status, "SELECTED"),
    )
    connection.execute(
        "INSERT INTO market_observations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("o1", "r1", "e1", "ABC", "2026-09-28T11:00:00+00:00", market_value, "USD/share",
         json.dumps({"quote_kind": "REGULAR"}), "USD", "2026-09-28T11:00:00+00:00", "2026-09-28",
         "synthetic", status),
    )
    details = {"quote_kind": status, "effective_time": "2026-09-28T11:00:00+00:00",
               "public_available_time": published, "market_session_date": "2026-09-28",
               "calendar_id": "XNYS-v1"} if status == "LAST_VALID_CLOSE" else {}
    connection.execute("INSERT INTO freshness_assessments VALUES (?,?,?,?,?,?)",
                       ("f1", "r1", "e1", status, AS_OF, json.dumps(details)))
    connection.commit()
    connection.close()


def add_valid_dcf(path: Path, *, forged_field: str | None = None, future_field: str | None = None, omit_field: str | None = None, duplicate_field: str | None = None, forged_output: bool = False) -> None:
    connection = sqlite3.connect(path)
    scenarios = {
        "base": DcfAssumptions(D("100"), D("0.05"), D("0.10"), D("0.02"), 5, D("10"), D("10")),
        "optimistic": DcfAssumptions(D("100"), D("0.08"), D("0.10"), D("0.02"), 5, D("10"), D("10")),
    }
    fields = ("starting_fcf", "annual_growth_rate", "discount_rate", "terminal_growth_rate", "years", "net_debt", "shares_outstanding")
    units = {"starting_fcf": ("currency", "USD"), "annual_growth_rate": ("ratio", None),
             "discount_rate": ("ratio", None), "terminal_growth_rate": ("ratio", None),
             "years": ("years", None), "net_debt": ("currency", "USD"), "shares_outstanding": ("shares", None)}
    records, metrics = [], []
    for scenario_name, assumptions in scenarios.items():
        values = {field: str(getattr(assumptions, field)) for field in fields}
        evidence = {}
        for field in fields:
            if scenario_name == "base" and field == omit_field:
                continue
            evidence_id = f"{scenario_name}-{field}"
            evidence[field] = evidence_id
            stored_value = values[field]
            if scenario_name == "base" and field == forged_field:
                stored_value = str(D(stored_value) + D("1"))
            published = "2026-09-28T13:00:00+00:00" if scenario_name == "base" and field == future_field else "2026-09-28T10:00:00+00:00"
            unit, currency = units[field]
            connection.execute(
                "INSERT INTO evidence (evidence_id,run_id,evidence_type,instrument_id,metric,value_text,unit,currency,published_at,retrieved_at,selection_state,source_uri,source_name) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (evidence_id, "r1", "assumption", "ABC", f"dcf_assumption:{scenario_name}:{field}",
                 json.dumps(stored_value), unit, currency, published, "2026-09-28T11:00:00+00:00",
                 "SELECTED", "https://example.invalid/source", "synthetic receipt"),
            )
            if scenario_name == "base" and field == duplicate_field:
                connection.execute(
                    "INSERT INTO evidence (evidence_id,run_id,evidence_type,instrument_id,metric,value_text,unit,currency,published_at,retrieved_at,selection_state,source_uri,source_name) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (f"duplicate-{evidence_id}", "r1", "assumption", "ABC",
                     f"dcf_assumption:{scenario_name}:{field}", json.dumps(stored_value), unit,
                     currency, published, "2026-09-28T11:00:00+00:00", "SELECTED",
                     "https://example.invalid/duplicate", "synthetic duplicate"),
                )
        records.append({"scenario": scenario_name, "values": values, "evidence": evidence})
        metrics.append({"name": f"dcf_scenario_{scenario_name}",
                        "value": str(EquityValuationAnalyzer._dcf_per_share(assumptions)),
                        "evidence_ids": list(evidence.values())})
    if forged_output:
        next(metric for metric in metrics if metric["name"] == "dcf_scenario_base")["value"] = "999"
    result = {"subject": "ABC", "analysis_type": "EQUITY_VALUATION",
              "metadata": {"currency": "USD", "dcf_assumption_value_bindings": records}, "metrics": metrics}
    inputs = {"subject": "ABC", "dcf_assumption_value_bindings": records}
    connection.execute("INSERT INTO calculations VALUES (?,?,?,?,?,?,?)",
                       ("valuation1", "r1", "EQUITY_VALUATION", "deterministic_phase5_asset_analysis",
                        json.dumps(inputs), json.dumps(result), AS_OF))
    connection.commit()
    connection.close()


class PolicyBMarketAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "run.db"

    def tearDown(self):
        self.temp.cleanup()

    def load(self):
        return load_policy_b_market_evidence(self.db, run_id="r1", instrument_id="ABC", as_of=AS_OF)

    def test_valid_same_run_quote_becomes_verified_money(self):
        make_db(self.db)
        result = self.load()
        self.assertEqual(result.quote_per_share.amount, 100)
        self.assertEqual(result.quote_per_share.currency, "USD")
        self.assertTrue(result.quote_per_share.verified)
        self.assertEqual(result.quote_evidence_id, "e1")

    def test_stale_quote_is_rejected(self):
        make_db(self.db, status="STALE")
        result = self.load()
        self.assertIsNone(result.quote_per_share)
        self.assertTrue(any("not eligible" in reason for reason in result.unavailable_reasons))

    def test_last_valid_close_requires_persisted_session_calendar_proof(self):
        make_db(self.db, status="LAST_VALID_CLOSE")
        result = self.load()
        self.assertIsNotNone(result.quote_per_share)
        self.assertTrue(result.quote_per_share.verified)

    def test_unproven_last_valid_close_is_rejected(self):
        make_db(self.db, status="LAST_VALID_CLOSE")
        connection = sqlite3.connect(self.db)
        try:
            connection.execute("UPDATE freshness_assessments SET details_json='{}'")
            connection.commit()
        finally:
            connection.close()
        result = self.load()
        self.assertIsNone(result.quote_per_share)
        self.assertTrue(any("calendar" in reason or "timestamps" in reason for reason in result.unavailable_reasons))

    def test_future_published_quote_is_rejected(self):
        make_db(self.db, published="2026-09-28T13:00:00+00:00")
        result = self.load()
        self.assertIsNone(result.quote_per_share)
        self.assertTrue(any("future-dated" in reason for reason in result.unavailable_reasons))

    def test_forged_market_value_mismatch_is_rejected(self):
        make_db(self.db, market_value="999")
        result = self.load()
        self.assertIsNone(result.quote_per_share)
        self.assertTrue(any("do not match" in reason for reason in result.unavailable_reasons))

    def test_dcf_scenario_id_does_not_certify_fair_values(self):
        make_db(self.db)
        connection = sqlite3.connect(self.db)
        try:
            connection.execute("INSERT INTO calculations VALUES (?,?,?,?,?,?,?)",
                               ("calc1", "r1", "valuation", "dcf", '{"scenario_id":"base"}',
                                '{"fair_value_per_share":120}', AS_OF))
            connection.commit()
        finally:
            connection.close()
        result = self.load()
        self.assertIsNotNone(result.quote_per_share)
        self.assertIsNone(result.fair_value_per_share)
        self.assertIsNone(result.optimistic_fair_value_per_share)
        self.assertTrue(any("calculation is missing" in reason or "binding contract" in reason for reason in result.unavailable_reasons))

    def test_complete_value_bound_dcf_scenarios_produce_verified_money(self):
        make_db(self.db)
        add_valid_dcf(self.db)
        result = self.load()
        self.assertIsNotNone(result.fair_value_per_share, result.unavailable_reasons)
        expected = EquityValuationAnalyzer._dcf_per_share(
            DcfAssumptions(D("100"), D("0.05"), D("0.10"), D("0.02"), 5, D("10"), D("10"))
        )
        self.assertEqual(result.fair_value_per_share.amount, expected)
        self.assertEqual(result.optimistic_fair_value_per_share.currency, "USD")
        self.assertTrue(result.optimistic_fair_value_per_share.verified)

    def test_forged_missing_or_future_dcf_binding_fails_closed(self):
        for kwargs, expected in (
            ({"forged_field": "annual_growth_rate"}, "does not equal"),
            ({"future_field": "discount_rate"}, "future provenance"),
            ({"omit_field": "shares_outstanding"}, "lacks complete"),
            ({"duplicate_field": "net_debt"}, "duplicate, or conflicting"),
            ({"forged_output": True}, "does not match its verified assumptions"),
        ):
            with self.subTest(kwargs=kwargs):
                if self.db.exists():
                    self.db.unlink()
                make_db(self.db)
                add_valid_dcf(self.db, **kwargs)
                result = self.load()
                self.assertIsNone(result.fair_value_per_share)
                self.assertTrue(any(expected in reason for reason in result.unavailable_reasons))


if __name__ == "__main__":
    unittest.main()
