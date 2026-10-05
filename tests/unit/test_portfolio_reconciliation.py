from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from investment_stack.calculations import (
    AllocationAnalyzer,
    PortfolioReconciliationInput,
    PositionExposure,
    ReconciliationConfig,
    ReconciliationStatus,
    reconcile_portfolio_total,
)
from investment_stack.materiality import load_materiality_config


D = Decimal


class PortfolioReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = ReconciliationConfig("test-v1", D("1000"), D("0.001"))

    def test_conflicting_total_is_unresolved_and_naive_total_is_not_authoritative(self) -> None:
        result = reconcile_portfolio_total(
            PortfolioReconciliationInput(
                reported_total=D("1046450"),
                group_totals={"stocks": D("817062"), "cash": D("343971")},
                group_components={
                    "stocks": tuple(map(D, ("407710", "151449", "95400", "44700", "42000", "29100", "26400", "22100"))),
                    "cash": (D("139106"), D("204707")),
                },
            ),
            self.config,
        )
        self.assertEqual(ReconciliationStatus.UNRESOLVED, result.status)
        self.assertIsNone(result.authoritative_total)
        self.assertEqual(D("1162672"), result.naive_component_total)
        self.assertEqual(D("1161033"), result.confirmed_group_total)

    def test_cash_components_are_not_added_on_top_of_cash_group_total(self) -> None:
        result = reconcile_portfolio_total(
            PortfolioReconciliationInput(
                reported_total=D("1000"),
                group_totals={"stocks": D("600"), "cash": D("400")},
                group_components={"stocks": (D("600"),), "cash": (D("150"), D("250"))},
            ),
            self.config,
        )
        self.assertEqual(ReconciliationStatus.RESOLVED, result.status)
        self.assertEqual(D("1000"), result.authoritative_total)

    def test_unresolved_denominator_suppresses_weights(self) -> None:
        allocation = AllocationAnalyzer().analyze(
            (
                PositionExposure("A", D("700"), asset_class="EQUITY"),
                PositionExposure("B", D("300"), asset_class="CASH"),
            ),
            denominator_resolved=False,
        )
        self.assertEqual("PARTIAL", allocation.status)
        self.assertIsNone(allocation.denominator)
        self.assertEqual({}, allocation.by_asset_class)
        self.assertEqual(D("1000"), allocation.valued_total)

    def test_missing_materiality_config_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "materiality.yaml"
            path.write_text('version: "x"\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_materiality_config(path)

    def test_repository_materiality_config_loads_explicit_version(self) -> None:
        path = Path(__file__).resolve().parents[2] / "config" / "materiality.yaml"
        config = load_materiality_config(path)
        self.assertEqual("v1.0", config.version)
        self.assertEqual(D("0.05"), config.min_weight)


if __name__ == "__main__":
    unittest.main()
