"""Test suite for R04 SEC Company Facts parsing logic."""

import unittest
from decimal import Decimal
from unittest.mock import MagicMock, patch

from investment_stack.providers.adapters import SecCompanyFactsAdapter
from investment_stack.providers.models import ProviderRequest
from investment_stack.providers.registry import ProviderCapability
from investment_stack.providers.models import ProviderStatus


class SecCompanyFactsAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = SecCompanyFactsAdapter()
        self.request = ProviderRequest(
            capability=ProviderCapability.FUNDAMENTALS,
            analysis_as_of="2024-03-31T23:59:59Z",
            analysis_timezone="UTC",
            instrument_id="AAPL",
            parameters={"cik": "0000320193"}
        )

    def _mock_fetch_json(self, mock_fetch, facts_dict):
        mock_fetch.return_value = {"cik": 320193, "entityName": "Apple Inc.", "facts": facts_dict}

    @patch("investment_stack.providers.adapters.fetch_json")
    def test_parse_multiple_facts_and_units(self, mock_fetch):
        # 복수 fact, 단위, 동일 기간 정정, future filed, unsupported tag
        facts_dict = {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "start": "2023-01-01",
                                "end": "2023-12-31",
                                "val": 1000,
                                "accn": "0001",
                                "fy": 2023,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2024-02-15",
                                "frame": "CY2023"
                            },
                            {
                                "start": "2023-01-01",
                                "end": "2023-12-31",
                                "val": 1100,
                                "accn": "0002", # revised accession
                                "fy": 2023,
                                "fp": "FY",
                                "form": "10-K/A",
                                "filed": "2024-03-10",
                                "frame": "CY2023"
                            },
                            {
                                "start": "2024-01-01",
                                "end": "2024-03-31",
                                "val": 500,
                                "accn": "0003",
                                "fy": 2024,
                                "fp": "Q1",
                                "form": "10-Q",
                                "filed": "2024-05-01", # future filed > analysis_as_of (2024-03-31)
                                "frame": "CY2024Q1"
                            }
                        ]
                    }
                },
                "EarningsPerShareBasic": {
                    "units": {
                        "USD/shares": [
                            {
                                "start": "2023-01-01",
                                "end": "2023-12-31",
                                "val": 5.25,
                                "accn": "0001",
                                "fy": 2023,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2024-02-15"
                            }
                        ]
                    }
                },
                "UnsupportedTagXYZ": {
                    "units": {
                        "USD": [
                            {"start": "2023-01-01", "end": "2023-12-31", "val": 999, "form": "10-K", "filed": "2024-02-15"}
                        ]
                    }
                }
            },
            "dei": {
                "EntityCommonStockSharesOutstanding": {
                    "units": {
                        "shares": [
                            {
                                # Instant metric, start not required
                                "end": "2023-12-31",
                                "val": 16000000000,
                                "accn": "0001",
                                "fy": 2023,
                                "form": "10-K",
                                "filed": "2024-02-15"
                            }
                        ]
                    }
                }
            }
        }
        self._mock_fetch_json(mock_fetch, facts_dict)
        
        result = self.adapter.fetch(self.request)
        
        self.assertEqual(result.status, ProviderStatus.AVAILABLE)
        # Should have 2 Revenues + 1 EPS + 1 Shares = 4 facts total (future one is skipped)
        self.assertEqual(len(result.observations), 4)
        
        # Check deterministic order: namespace (dei then us-gaap) -> tag -> unit -> period_end -> start -> accn -> filed -> val
        obs_shares = result.observations[0]
        self.assertEqual(obs_shares.metric, "shares_outstanding")
        self.assertEqual(obs_shares.unit, "shares")
        self.assertEqual(obs_shares.value, Decimal("16000000000"))
        self.assertTrue(obs_shares.metadata["calculation_input_approved"])

        obs_eps = result.observations[1]
        self.assertEqual(obs_eps.metric, "eps")
        self.assertEqual(obs_eps.unit, "USD/shares")
        self.assertEqual(obs_eps.value, Decimal("5.25"))
        self.assertTrue(obs_eps.metadata["calculation_input_approved"])
        
        obs_rev1 = result.observations[2]
        self.assertEqual(obs_rev1.metric, "revenue")
        self.assertEqual(obs_rev1.value, Decimal("1000"))
        self.assertEqual(obs_rev1.metadata["accn"], "0001")
        self.assertTrue(obs_rev1.metadata["calculation_input_approved"])
        
        obs_rev2 = result.observations[3]
        self.assertEqual(obs_rev2.metric, "revenue")
        self.assertEqual(obs_rev2.value, Decimal("1100"))
        self.assertEqual(obs_rev2.metadata["accn"], "0002")
        self.assertTrue(obs_rev2.metadata["calculation_input_approved"])

    @patch("investment_stack.providers.adapters.fetch_json")
    def test_missing_required_fields_marks_partial(self, mock_fetch):
        # malformed fact (missing start for duration, or missing end, form, or filed)
        facts_dict = {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {"start": "2023-01-01", "val": 1000, "form": "10-K", "filed": "2024-02-15"}, # missing end
                            {"start": "2023-01-01", "end": "2023-12-31", "val": 2000, "filed": "2024-02-15"}, # missing form
                            {"end": "2023-12-31", "val": 3000, "form": "10-K", "filed": "2024-02-15"}, # duration missing start
                            {"start": "2024-01-01", "end": "2023-12-31", "val": 4000, "form": "10-K", "filed": "2024-02-15"}, # start > end
                        ]
                    }
                }
            }
        }
        self._mock_fetch_json(mock_fetch, facts_dict)
        
        result = self.adapter.fetch(self.request)
        
        self.assertEqual(result.status, ProviderStatus.PARTIAL)
        self.assertEqual(len(result.observations), 4)
        for obs in result.observations:
            self.assertFalse(obs.metadata["calculation_input_approved"])
            self.assertIsNotNone(obs.relevance_reason)

    @patch("investment_stack.providers.adapters.fetch_json")
    def test_empty_facts_unavailable(self, mock_fetch):
        # 빈 facts
        facts_dict = {}
        self._mock_fetch_json(mock_fetch, facts_dict)
        
        result = self.adapter.fetch(self.request)
        
        self.assertEqual(result.status, ProviderStatus.UNAVAILABLE)
        self.assertEqual(len(result.observations), 0)

    @patch("investment_stack.providers.adapters.fetch_json")
    def test_invalid_values_skipped(self, mock_fetch):
        # dict, bool, NaN, Infinity, None
        facts_dict = {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {"start": "2023-01-01", "end": "2023-12-31", "val": {"bad": "dict"}, "form": "10-K", "filed": "2024-02-15"},
                            {"start": "2023-01-01", "end": "2023-12-31", "val": "NaN", "form": "10-K", "filed": "2024-02-15"},
                            {"start": "2023-01-01", "end": "2023-12-31", "val": "Infinity", "form": "10-K", "filed": "2024-02-15"},
                            {"start": "2023-01-01", "end": "2023-12-31", "val": True, "form": "10-K", "filed": "2024-02-15"},
                            {"start": "2023-01-01", "end": "2023-12-31", "val": None, "form": "10-K", "filed": "2024-02-15"},
                        ]
                    }
                }
            }
        }
        self._mock_fetch_json(mock_fetch, facts_dict)
        
        result = self.adapter.fetch(self.request)
        
        # All invalid values are skipped completely via `continue`
        self.assertEqual(result.status, ProviderStatus.UNAVAILABLE)
        self.assertEqual(len(result.observations), 0)

    @patch("investment_stack.providers.adapters.fetch_json")
    def test_permutation_invariance(self, mock_fetch):
        # Different dictionary insertion orders should yield same observation order
        f1 = {"start": "2023-01-01", "end": "2023-12-31", "val": 100, "accn": "0001", "form": "10-K", "filed": "2024-02-15"}
        f2 = {"start": "2023-01-01", "end": "2023-12-31", "val": 200, "accn": "0002", "form": "10-K/A", "filed": "2024-03-10"}
        
        dict1 = {"us-gaap": {"Revenues": {"units": {"USD": [f1, f2]}}}}
        dict2 = {"us-gaap": {"Revenues": {"units": {"USD": [f2, f1]}}}}
        
        self._mock_fetch_json(mock_fetch, dict1)
        r1 = self.adapter.fetch(self.request)
        
        self._mock_fetch_json(mock_fetch, dict2)
        r2 = self.adapter.fetch(self.request)
        
        self.assertEqual(
            [o.metadata["accn"] for o in r1.observations],
            [o.metadata["accn"] for o in r2.observations]
        )


if __name__ == "__main__":
    unittest.main()
