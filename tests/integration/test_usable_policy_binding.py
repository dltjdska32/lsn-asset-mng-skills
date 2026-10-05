"""Synthetic end-to-end binding for conditional D12 B action numbers."""

from __future__ import annotations

import hashlib
import io
import json
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import tempfile

from investment_stack.calculations.valuation import DcfAssumptions, EquityValuationAnalyzer
from investment_stack.cli import main
from investment_stack.decisions.policy_b_market import load_policy_b_market_evidence
from investment_stack.evidence import RunDatabaseManager
from investment_stack.evidence.source_receipt import payload_sha256
from investment_stack.execution.host import open_configured_host
from investment_stack.execution.models import ModeRequest
from investment_stack.personal.intent import ConfirmationState, TransactionIntent, TransactionType
from investment_stack.personal.ledger import PersonalLedgerService
from investment_stack.personal.manager import PersonalDatabaseManager
from investment_stack.personal.reserves import CashReservationDraft
from investment_stack.reporting.policy_b_briefing import build_policy_b_section
from investment_stack.routing import RequestMode
from investment_stack.execution import execute_mode


AS_OF = "2026-09-28T12:00:00+00:00"
OBSERVED = "2026-09-28T11:55:00+00:00"
INSTRUMENT = "NASDAQ:ABC"
FIELDS = (
    "starting_fcf", "annual_growth_rate", "discount_rate", "terminal_growth_rate",
    "years", "net_debt", "shares_outstanding",
)


def _yahoo(symbol: str, price: str, observed_at: str) -> str:
    observed = datetime.fromisoformat(observed_at)
    return json.dumps({
        "chart": {"result": [{"meta": {
            "symbol": symbol, "regularMarketPrice": price, "currency": "USD",
            "exchangeName": "NMS", "exchangeTimezoneName": "America/New_York",
            "regularMarketTime": int(observed.timestamp()),
        }}], "error": None},
    }, separators=(",", ":"))


def _assumption_document(scenario: str, field: str, value: str, unit: str, currency: str | None) -> str:
    excerpt = f"{scenario} {field} is {value} in the filed source note for {INSTRUMENT}."
    body = {
        "record_type": "explicit_dcf_assumption_v1",
        "scenario": scenario, "field": field, "value": value, "unit": unit,
        "currency": currency, "published_at": "2026-09-01T00:00:00+00:00",
        "source_excerpt": excerpt,
    }
    if field == "starting_fcf":
        body["cash_flow_basis"] = "FCFF"
        body["source_excerpt"] = excerpt + " cash_flow_basis FCFF."
    return json.dumps(body, separators=(",", ":"))


class UsablePolicyBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.personal_path = root / "personal.db"
        manager = PersonalDatabaseManager(self.personal_path, backup_directory=root / "backups")
        self.assertEqual("VALID", manager.initialize().status.value)
        self.ledger = PersonalLedgerService(manager)
        self.ledger.register_account("cash", name="Synthetic cash", currency="USD", timezone_name="UTC")
        self.ledger.register_instrument(INSTRUMENT, canonical_name="Synthetic ABC", currency="USD")
        occurred = datetime(2026, 9, 28, 9, tzinfo=timezone.utc)
        self.ledger.post(TransactionIntent(
            TransactionType.DEPOSIT, account_id="cash", cash_amount="100000", currency="USD",
            occurred_at=occurred, timezone="UTC", confirmation_state=ConfirmationState.CONFIRMED,
            idempotency_key="synthetic-deposit",
        ))
        self.ledger.post(TransactionIntent(
            TransactionType.BUY, account_id="cash", instrument_id=INSTRUMENT, quantity="10",
            unit_price="100", currency="USD", occurred_at=occurred, timezone="UTC",
            confirmation_state=ConfirmationState.CONFIRMED, idempotency_key="synthetic-buy",
        ))
        self.state_version = self.ledger.get_current_state_version()
        self.ledger.declare_cash_reservations(expected_state_version=self.state_version, reservations=(
            CashReservationDraft("EMERGENCY_FUND", "USD", Decimal("1000")),
            CashReservationDraft("PLANNED_SPENDING", "USD", Decimal("500")),
            CashReservationDraft("PENDING_ORDER", "USD", Decimal("250"), INSTRUMENT),
        ))
        self.snapshot_id = "synthetic-snapshot"
        self.ledger.create_portfolio_snapshot(
            snapshot_id=self.snapshot_id, snapshot_type="BOOK_ONLY",
            as_of=datetime.fromisoformat(AS_OF), data={"ignored": True},
        )
        self.transactions_before = tuple(row["transaction_id"] for row in self.ledger.list_transactions())
        self.workspace = root / "workspace"
        self.run = RunDatabaseManager(self.workspace, "synthetic-run")
        self.assertTrue(self.run.create().valid)
        self.run.initialize_run_context(
            request_mode=RequestMode.PERSONAL_PORTFOLIO_ANALYSIS.value,
            analysis_as_of=AS_OF, analysis_timezone="UTC", state_version=self.state_version,
            personal_db_instance_id=manager.instance_id, portfolio_snapshot_id=self.snapshot_id,
            portfolio_data_as_of=AS_OF,
        )
        self._seed_quote()
        self._seed_dcf()
        self._seed_rules_and_thesis()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _seed_quote(self) -> None:
        payload = _yahoo("ABC", "100", OBSERVED)
        self.run.add_phase4_evidence(
            evidence_id="quote-1", evidence_type="market", source_uri="https://query1.finance.yahoo.com/v8/finance/chart/ABC",
            retrieved_at=OBSERVED, instrument_id=INSTRUMENT, metric="current_price", value=100,
            unit="USD/share", currency="USD", source_name="yahoo_finance", source_tier=2,
            observed_at=OBSERVED, published_at=OBSERVED, freshness_status="FRESH", provider_id="yahoo_chart",
        )
        self.run.add_market_observation(
            observation_id="quote-obs", evidence_id="quote-1", instrument_id=INSTRUMENT, observed_at=OBSERVED,
            value="100", unit="USD/share", currency="USD", claimed_market_time=OBSERVED,
            market_session_date="2026-09-28", provider_id="yahoo_chart", freshness_status="FRESH",
            metadata={"exchange": "NASDAQ", "quote_kind": "REGULAR"},
        )
        self.run.add_freshness_assessment(
            freshness_id="quote-fresh", evidence_id="quote-1", status="FRESH", details={},
        )
        self.run.mark_evidence_selected(evidence_id="quote-1", reason="reparsed provider body")
        self.run.add_source_document(
            document_id="quote-doc", evidence_id="quote-1", parser_id="yahoo_chart_v1", payload_text=payload,
        )

    def _seed_dcf(self) -> None:
        scenarios = {
            "conservative": DcfAssumptions(Decimal("80"), Decimal("0"), Decimal("0.10"), Decimal("0.02"), 1, Decimal("0"), Decimal("10")),
            "base": DcfAssumptions(Decimal("100"), Decimal("0"), Decimal("0.10"), Decimal("0.02"), 1, Decimal("0"), Decimal("10")),
            "optimistic": DcfAssumptions(Decimal("120"), Decimal("0"), Decimal("0.10"), Decimal("0.02"), 1, Decimal("0"), Decimal("10")),
        }
        records = []
        metrics = []
        for scenario, assumptions in scenarios.items():
            evidence = {}
            values = {}
            for field in FIELDS:
                raw = getattr(assumptions, field)
                value = str(raw)
                values[field] = value
                evidence_id = f"dcf-{scenario}-{field}"
                evidence[field] = evidence_id
                unit = "currency" if field in {"starting_fcf", "net_debt"} else "ratio"
                currency = "USD" if unit == "currency" else None
                if field == "years":
                    unit = "years"
                elif field == "shares_outstanding":
                    unit = "shares"
                self.run.add_phase4_evidence(
                    evidence_id=evidence_id, evidence_type="assumption",
                    source_uri=f"https://filings.example.test/{evidence_id}", retrieved_at="2026-09-01T00:00:00+00:00",
                    instrument_id=INSTRUMENT, metric=f"dcf_assumption:{scenario}:{field}", value=value,
                    unit=unit, currency=currency, source_name="filed excerpt", source_tier=1,
                    observed_at="2026-09-01T00:00:00+00:00", published_at="2026-09-01T00:00:00+00:00",
                    provider_id="filing",
                )
                self.run.mark_evidence_selected(evidence_id=evidence_id, reason="excerpt reparse")
                self.run.add_source_document(
                    document_id=f"doc-{evidence_id}", evidence_id=evidence_id,
                    parser_id="explicit_dcf_assumption_v1",
                    payload_text=_assumption_document(scenario, field, value, unit, currency),
                )
            records.append({"scenario": scenario, "values": values, "evidence": evidence})
            metrics.append({
                "name": f"dcf_scenario_{scenario}",
                "value": str(EquityValuationAnalyzer._dcf_per_share(assumptions)),
                "evidence_ids": list(evidence.values()),
            })
        result = {
            "subject": INSTRUMENT, "analysis_type": "EQUITY_VALUATION",
            "metadata": {"currency": "USD", "dcf_assumption_value_bindings": records},
            "metrics": metrics,
        }
        self.run.add_calculation(
            calculation_id="valuation-1", calculation_name="EQUITY_VALUATION",
            formula="explicit_dcf_scenarios", inputs={"subject": INSTRUMENT, "dcf_assumption_value_bindings": records},
            result=result,
        )

    def _seed_rules_and_thesis(self) -> None:
        rule = json.dumps({
            "record_type": "exchange_trading_rule_v1", "instrument_id": INSTRUMENT, "currency": "USD",
            "lot_size": "1", "price_tick": "0.01", "fee_per_unit": "0",
            "published_at": "2026-09-01T00:00:00+00:00",
            "rule_excerpt": f"Schedule {INSTRUMENT} currency USD lot_size=1 price_tick=0.01 fee_per_unit=0",
        }, separators=(",", ":"))
        thesis = json.dumps({
            "record_type": "thesis_status_v1", "instrument_id": INSTRUMENT, "impaired": False,
            "published_at": "2026-09-01T00:00:00+00:00",
            "rationale_excerpt": f"{INSTRUMENT} thesis_impaired=false because the filed cash-flow case remains intact.",
        }, separators=(",", ":"))
        self.run.add_phase4_evidence(
            evidence_id="rule-1", evidence_type="trading_rule", source_uri="https://rules.example.test/nasdaq",
            retrieved_at="2026-09-01T00:00:00+00:00", instrument_id=INSTRUMENT, metric="trading_rule",
            value="1", unit="shares", currency="USD", source_name="exchange schedule", source_tier=1,
            published_at="2026-09-01T00:00:00+00:00", provider_id="exchange",
        )
        self.run.mark_evidence_selected(evidence_id="rule-1", reason="rule excerpt")
        self.run.add_source_document(
            document_id="rule-doc", evidence_id="rule-1", parser_id="exchange_trading_rule_v1", payload_text=rule,
        )
        self.run.add_phase4_evidence(
            evidence_id="thesis-1", evidence_type="thesis", source_uri="https://notes.example.test/thesis",
            retrieved_at="2026-09-01T00:00:00+00:00", instrument_id=INSTRUMENT, metric="thesis_status",
            value="false", unit="flag", source_name="thesis note", source_tier=1,
            published_at="2026-09-01T00:00:00+00:00", provider_id="thesis",
        )
        self.run.mark_evidence_selected(evidence_id="thesis-1", reason="thesis excerpt")
        self.run.add_source_document(
            document_id="thesis-doc", evidence_id="thesis-1", parser_id="thesis_status_v1", payload_text=thesis,
        )

    def test_direct_section_waits_for_allocation_budget_without_posting(self) -> None:
        market = load_policy_b_market_evidence(
            self.run.database_path, run_id=self.run.run_id, instrument_id=INSTRUMENT, as_of=AS_OF,
        )
        self.assertTrue(market.quote_per_share.verified)
        self.assertTrue(market.fair_value_per_share.verified)
        self.assertIsNotNone(market.conservative_fair_value_per_share)
        section = build_policy_b_section(
            INSTRUMENT, datetime.fromisoformat(AS_OF), None,
            run_db=self.run, personal_ledger=self.ledger, evaluation_currency="USD",
        )
        rendered = "\n".join(section.lines)
        self.assertIn("진입 가격·금액·수량 대기", rendered)
        self.assertNotIn("추가 예산 상한 7000.00 USD", rendered)
        self.assertNotIn("수량 23주", rendered)
        self.assertNotIn("종목 8% 상한", rendered)
        self.assertNotIn("8% 복귀", rendered)
        self.assertEqual(self.transactions_before, tuple(row["transaction_id"] for row in self.ledger.list_transactions()))
        self.assertEqual(self.state_version, self.ledger.get_current_state_version())

    def test_configured_host_does_not_recreate_legacy_eight_percent_budget(self) -> None:
        services = open_configured_host(self.workspace, self.run.run_id, self.personal_path)
        result = execute_mode(ModeRequest(
            self.run.run_id, RequestMode.PERSONAL_PORTFOLIO_ANALYSIS,
            {"portfolio_source": "pinned_ledger", "evaluation_currency": "USD", "title": "합성"},
        ), services)
        self.assertIn(result.availability.value, {"PARTIAL", "COMPLETE"})
        self.assertTrue(result.report_refs)
        markdown = result.step_states[-1].result.output["report"].markdown
        self.assertNotIn("조건부 진입", markdown)
        self.assertIn("13F 점수는 기간 외 검증 전 매매 조건으로 사용하지 않습니다", markdown)
        self.assertIn("자동 주문이나 원장 기록을 수행하지 않습니다", markdown)
        self.assertIn("진입 가격·금액·수량 대기", markdown)
        self.assertEqual(self.transactions_before, tuple(row["transaction_id"] for row in self.ledger.list_transactions()))

    def test_cli_without_paths_stays_unconfigured_and_configured_cli_matches(self) -> None:
        import sys
        from contextlib import redirect_stdout
        previous = sys.stdin
        bare = io.StringIO()
        sys.stdin = io.StringIO("{}")
        try:
            with redirect_stdout(bare):
                bare_code = main(["execute", "--mode", "SINGLE_ASSET_ANALYSIS", "--run-id", "missing", "--json"])
        finally:
            sys.stdin = previous
        self.assertEqual(3, bare_code)
        self.assertIn("UNSUPPORTED", bare.getvalue())
        payload = json.dumps({
            "portfolio_source": "pinned_ledger", "evaluation_currency": "USD", "title": "합성",
        })
        captured = io.StringIO()
        sys.stdin = io.StringIO(payload)
        try:
            with redirect_stdout(captured):
                code = main([
                    "execute", "--mode", "PERSONAL_PORTFOLIO_ANALYSIS", "--run-id", self.run.run_id,
                    "--run-workspace", str(self.workspace), "--personal-db", str(self.personal_path), "--json",
                ])
        finally:
            sys.stdin = previous
        self.assertEqual(0, code)
        body = captured.getvalue()
        self.assertNotIn("1차 조건부 진입 100.00 USD/주", body)
        self.assertNotIn("수량 23주", body)
        self.assertIn("13F 점수는 기간 외 검증 전 매매 조건으로 사용하지 않습니다", body)
        self.assertIn("진입 가격·금액·수량 대기", body)
        self.assertEqual(self.transactions_before, tuple(row["transaction_id"] for row in self.ledger.list_transactions()))
        self.assertEqual(payload_sha256(_yahoo("ABC", "100", OBSERVED)), hashlib.sha256(_yahoo("ABC", "100", OBSERVED).encode()).hexdigest())

    def test_run_without_source_documents_keeps_action_numbers_waiting(self) -> None:
        bare = RunDatabaseManager(self.workspace, "bare-run")
        self.assertTrue(bare.create().valid)
        bare.initialize_run_context(
            request_mode=RequestMode.PERSONAL_PORTFOLIO_ANALYSIS.value,
            analysis_as_of=AS_OF, analysis_timezone="UTC", state_version=self.state_version,
            personal_db_instance_id=self.ledger.manager.instance_id, portfolio_snapshot_id=self.snapshot_id,
            portfolio_data_as_of=AS_OF,
        )
        services = open_configured_host(self.workspace, bare.run_id, self.personal_path)
        result = execute_mode(ModeRequest(
            bare.run_id, RequestMode.PERSONAL_PORTFOLIO_ANALYSIS,
            {"portfolio_source": "pinned_ledger", "evaluation_currency": "USD", "title": "자료 없음"},
        ), services)
        markdown = result.step_states[-1].result.output["report"].markdown
        self.assertIn("진입 가격·금액·수량 대기", markdown)
        self.assertNotIn("조건부 진입", markdown)
        self.assertEqual(self.transactions_before, tuple(row["transaction_id"] for row in self.ledger.list_transactions()))


if __name__ == "__main__":
    unittest.main()
