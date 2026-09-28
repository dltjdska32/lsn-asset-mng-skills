from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from investment_stack.decisions.policy_b_market import load_policy_b_market_evidence


AS_OF = "2026-09-28T12:00:00+00:00"


def make_db(path: Path, *, status: str = "FRESH", evidence_value: str = "100", market_value: str = "100", published: str = "2026-09-28T11:00:00+00:00") -> None:
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE run_metadata(run_id TEXT, analysis_as_of TEXT);
        CREATE TABLE evidence(evidence_id TEXT, run_id TEXT, evidence_type TEXT,
          instrument_id TEXT, metric TEXT, value_text TEXT, unit TEXT, currency TEXT,
          observed_at TEXT, published_at TEXT, freshness_status TEXT, selection_state TEXT);
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
        "INSERT INTO evidence VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
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
        self.assertTrue(any("assumption-value provenance" in reason for reason in result.unavailable_reasons))


if __name__ == "__main__":
    unittest.main()
