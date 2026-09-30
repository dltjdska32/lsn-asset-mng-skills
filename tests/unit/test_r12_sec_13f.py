"""Unit tests for REQ-2026-09-23-v1 R12: SEC 13F parsing, normalization, and portfolio comparison."""

from __future__ import annotations

import dataclasses
import json
import unittest
from datetime import datetime, timezone
from decimal import Decimal

from investment_stack.contracts.context import PublicAvailability
from investment_stack.contracts.calculation import CalculationRecord, CalculationStatus, InvestmentDecision
from investment_stack.contracts.errors import (
    ContractValidationError,
    DecimalValidationError,
    TimezoneValidationError,
)
from investment_stack.contracts.institutional import (
    AmendmentType,
    Filing13F,
    Form13FKind,
    Holding13F,
    HoldingSet13F,
    NoticeStatus,
    PutCall,
    QuantityType,
)
from investment_stack.institutional.compare import compare_portfolios
from investment_stack.institutional.models import (
    EffectiveHoldingSet,
    HoldingChangeStatus,
    InstitutionalPortfolioComparison,
    ParsedHoldingSet13F,
)
from investment_stack.institutional.normalize import (
    apply_split_adjustment,
    synthesize_effective_holdings,
)
from investment_stack.institutional.validation import run_point_in_time_audit, validate_amendment_cutoff_invariance
from investment_stack.contracts.slots import SelectedInputSet
from investment_stack.decisions.briefing import generate_briefing, make_institutional_briefing_context
from investment_stack.providers.sec_13f import (
    Sec13FAdapter,
    Sec13FSubmissionsError,
    Sec13FXmlParseError,
    filter_filings_by_cutoff,
    parse_information_table_xml,
    parse_submissions_json,
)

SAMPLE_SUBMISSIONS_JSON = {
    "cik": "0001067983",
    "name": "BERKSHIRE HATHAWAY INC",
    "filings": {
        "recent": {
            "accessionNumber": [
                "0001193125-24-200001",
                "0001193125-24-200002",
                "0001193125-24-200003",
                "0001193125-24-200004",
            ],
            "filingDate": [
                "2024-02-14",
                "2024-05-15",
                "2024-06-20",
                "2024-08-14",
            ],
            "reportDate": [
                "2023-12-31",
                "2024-03-31",
                "2024-03-31",
                "2024-06-30",
            ],
            "acceptanceDateTime": [
                "2024-02-14T21:05:00.000Z",
                "2024-05-15T20:30:00.000Z",
                "2024-06-20T17:15:00.000Z",
                "2024-08-14T21:45:00.000Z",
            ],
            "form": [
                "13F-HR",
                "13F-HR",
                "13F-HR/A",
                "13F-NT",
            ],
            "primaryDocument": [
                "xslForm13F_X02/primary_doc.xml",
                "xslForm13F_X02/primary_doc.xml",
                "xslForm13F_X02/primary_doc.xml",
                "primary_doc.xml",
            ],
            "primaryDocDescription": [
                "",
                "",
                "RESTATED HOLDINGS",
                "NOTICE",
            ],
            "fileNumber": [
                "028-04545",
                "028-04545",
                "028-04545",
                "028-04545",
            ],
        }
    }
}

SAMPLE_INFOTABLE_XML_POST_2023 = """<?xml version="1.0" encoding="UTF-8"?>
<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
    <infoTable>
        <nameOfIssuer>APPLE INC</nameOfIssuer>
        <titleOfClass>COM</titleOfClass>
        <cusip>037833100</cusip>
        <value>175000000</value>
        <shrsOrPrnAmt>
            <sshPrnamt>1000000</sshPrnamt>
            <sshPrnamtType>SH</sshPrnamtType>
        </shrsOrPrnAmt>
        <investmentDiscretion>SOLE</investmentDiscretion>
        <votingAuthority>
            <Sole>1000000</Sole>
            <Shared>0</Shared>
            <None>0</None>
        </votingAuthority>
    </infoTable>
    <infoTable>
        <nameOfIssuer>MICROSOFT CORP</nameOfIssuer>
        <titleOfClass>COM</titleOfClass>
        <cusip>594918104</cusip>
        <value>200000000</value>
        <shrsOrPrnAmt>
            <sshPrnamt>500000</sshPrnamt>
            <sshPrnamtType>SH</sshPrnamtType>
        </shrsOrPrnAmt>
        <investmentDiscretion>SOLE</investmentDiscretion>
        <votingAuthority>
            <Sole>500000</Sole>
            <Shared>0</Shared>
            <None>0</None>
        </votingAuthority>
    </infoTable>
    <infoTable>
        <nameOfIssuer>TESLA INC</nameOfIssuer>
        <titleOfClass>NOTE 1.25%</titleOfClass>
        <cusip>88160R101</cusip>
        <value>50000000</value>
        <shrsOrPrnAmt>
            <sshPrnamt>50000</sshPrnamt>
            <sshPrnamtType>PRN</sshPrnamtType>
        </shrsOrPrnAmt>
        <putCall>CALL</putCall>
        <investmentDiscretion>DEFINED</investmentDiscretion>
    </infoTable>
</informationTable>
"""

SAMPLE_INFOTABLE_XML_PRE_2023 = """<?xml version="1.0" encoding="UTF-8"?>
<informationTable xmlns="http://www.sec.gov/edgar/thirteenf/informationtable">
    <infoTable>
        <nameOfIssuer>APPLE INC</nameOfIssuer>
        <titleOfClass>COM</titleOfClass>
        <cusip>037833100</cusip>
        <value>150000</value>
        <shrsOrPrnAmt>
            <sshPrnamt>1000000</sshPrnamt>
            <sshPrnamtType>SH</sshPrnamtType>
        </shrsOrPrnAmt>
        <investmentDiscretion>SOLE</investmentDiscretion>
    </infoTable>
</informationTable>
"""


class TestSec13FSubmissionsParsing(unittest.TestCase):
    def test_provider_to_point_in_time_holdings_to_briefing(self) -> None:
        restatement_xml = b"""<informationTable><infoTable><nameOfIssuer>APPLE INC</nameOfIssuer>
        <titleOfClass>COM</titleOfClass><cusip>037833100</cusip><value>210000000</value>
        <shrsOrPrnAmt><sshPrnamt>1200000</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
        </infoTable></informationTable>"""
        tables = {
            "fixture://0001193125-24-200002": SAMPLE_INFOTABLE_XML_POST_2023.encode(),
            "fixture://0001193125-24-200003": restatement_xml,
        }

        def transport(url, _headers, _timeout):
            if url.startswith("https://data.sec.gov/submissions/"):
                return json.dumps(SAMPLE_SUBMISSIONS_JSON).encode()
            return tables[url]

        adapter = Sec13FAdapter(transport=transport)
        filings = adapter.fetch_submissions("1067983")
        report_period = "2024-03-31"
        relevant = [filing for filing in filings if filing.report_period == report_period]
        all_pairs = [
            (filing, adapter.fetch_information_table(f"fixture://{filing.accession}", filing))
            for filing in relevant
        ]

        before_cutoff = datetime(2024, 6, 1, tzinfo=timezone.utc)
        before_selected = [f for f in filter_filings_by_cutoff(filings, before_cutoff) if f.report_period == report_period]
        before_pairs = [(f, h) for f, h in all_pairs if f in before_selected]
        before = synthesize_effective_holdings("0001067983", report_period, before_pairs, before_cutoff)
        self.assertIsNotNone(before)
        self.assertEqual(3, len(before.holdings))
        self.assertNotIn("0001193125-24-200003", before.contributing_accessions)
        self.assertFalse(validate_amendment_cutoff_invariance("0001067983", report_period, all_pairs, before_cutoff)[0])

        cutoff = datetime(2024, 7, 1, tzinfo=timezone.utc)
        selected = [f for f in filter_filings_by_cutoff(filings, cutoff) if f.report_period == report_period]
        pairs = [(f, h) for f, h in all_pairs if f in selected]
        effective = synthesize_effective_holdings("0001067983", report_period, pairs, cutoff)
        self.assertIsNotNone(effective)
        self.assertEqual(1, len(effective.holdings))
        self.assertTrue(effective.holdings[0].filing_id.endswith("0001193125-24-200003"))

        audit = run_point_in_time_audit("synthetic-audit", cutoff, 1, selected, [], pre_registered_baseline=None)
        with self.assertRaises(ContractValidationError):
            make_institutional_briefing_context(effective, tuple(), audit)
        context = make_institutional_briefing_context(effective, tuple(selected), audit)
        input_set = SelectedInputSet.create("synthetic-run", "ASSET_ANALYSIS", 1, slots=[])
        calculation = CalculationRecord.create(
            "synthetic-calc", "synthetic-run", "placeholder", "placeholder", "1",
            CalculationStatus.UNAVAILABLE, [], input_set.snapshot_hash,
        )
        briefing = generate_briefing(
            input_set, {"synthetic-calc": calculation}, True, True, True,
            institutional_context=context,
        )
        self.assertEqual(InvestmentDecision.WAIT, briefing.decision)
        self.assertIn("2024-03-31", " ".join(briefing.section_core))
        self.assertIn("미검증", " ".join(briefing.section_core))
        self.assertIn("0001193125-24-200003", " ".join(briefing.section_details))

    def test_parse_submissions_json_success(self) -> None:
        filings = parse_submissions_json(SAMPLE_SUBMISSIONS_JSON)
        self.assertEqual(4, len(filings))

        # Check CIK padding & header metadata
        first = filings[0]
        self.assertEqual("0001067983", first.manager_cik)
        self.assertEqual("BERKSHIRE HATHAWAY INC", first.manager_name)
        self.assertEqual(Form13FKind.HR, first.form)
        self.assertEqual("2023-12-31", first.report_period)
        self.assertEqual("2024-02-14", first.filed_date)
        self.assertIsNotNone(first.public_availability.public_available_at)

        # Check amendment detection
        amendment = filings[2]
        self.assertEqual(Form13FKind.HR_A, amendment.form)
        self.assertEqual(AmendmentType.RESTATED, amendment.amendment_type)

        # Check notice only
        notice = filings[3]
        self.assertEqual(Form13FKind.NT, notice.form)
        self.assertEqual(NoticeStatus.NOTICE_ONLY, notice.notice_status)

    def test_parse_submissions_json_missing_cik(self) -> None:
        bad_data = {"filings": {"recent": {}}}
        with self.assertRaises(Sec13FSubmissionsError):
            parse_submissions_json(bad_data)

    def test_parse_submissions_json_rejects_invalid_identity(self) -> None:
        bad_cik = json.loads(json.dumps(SAMPLE_SUBMISSIONS_JSON))
        bad_cik["cik"] = "manager-1"
        with self.assertRaises(Sec13FSubmissionsError):
            parse_submissions_json(bad_cik)
        missing_accession = json.loads(json.dumps(SAMPLE_SUBMISSIONS_JSON))
        missing_accession["filings"]["recent"]["accessionNumber"][1] = ""
        with self.assertRaises(Sec13FSubmissionsError):
            parse_submissions_json(missing_accession)


class TestSec13FInformationTableXmlParsing(unittest.TestCase):
    def setUp(self) -> None:
        self.filings = parse_submissions_json(SAMPLE_SUBMISSIONS_JSON)

    def test_post_2023_exact_dollar_scale(self) -> None:
        # Filing from 2024-05-15 (post-2023)
        filing_post = self.filings[1]
        h_set = parse_information_table_xml(SAMPLE_INFOTABLE_XML_POST_2023, filing_post)

        self.assertEqual(3, len(h_set.holdings))
        # AAPL: raw_value = 175000000, post-2023 scale = 1 -> normalized_value = 175000000
        aapl = next(h for h in h_set.holdings if h.cusip == "037833100")
        self.assertEqual(Decimal("1"), aapl.value_scale)
        self.assertEqual(Decimal("175000000"), aapl.normalized_value)
        self.assertEqual(Decimal("1000000"), aapl.normalized_shares)
        self.assertEqual(QuantityType.SH, aapl.quantity_type)
        self.assertEqual(PutCall.NONE, aapl.put_call)

        # TSLA Call Note: PRN quantity and CALL option
        tsla = next(h for h in h_set.holdings if h.cusip == "88160R101")
        self.assertEqual(QuantityType.PRN, tsla.quantity_type)
        self.assertEqual(PutCall.CALL, tsla.put_call)
        self.assertEqual(Decimal("50000"), tsla.normalized_shares)

        # Total eligible value check
        self.assertEqual(Decimal("425000000"), h_set.total_eligible_value)

    def test_pre_2023_thousand_dollar_scale(self) -> None:
        # Synthetic filing from 2022-11-14 (pre-2023)
        filing_pre = Filing13F(
            filing_id="13f:0001067983:0001193125-22-100000",
            manager_cik="0001067983",
            manager_name="BERKSHIRE HATHAWAY INC",
            form=Form13FKind.HR,
            accession="0001193125-22-100000",
            report_period="2022-09-30",
            filed_date="2022-11-14",
            public_availability=self.filings[0].public_availability,
        )
        h_set = parse_information_table_xml(SAMPLE_INFOTABLE_XML_PRE_2023, filing_pre)
        self.assertEqual(1, len(h_set.holdings))
        aapl = h_set.holdings[0]

        # Raw value is 150000 ($1,000s) -> normalized value should be 150,000,000 ($)
        self.assertEqual(Decimal("1000"), aapl.value_scale)
        self.assertEqual(Decimal("150000"), aapl.raw_value)
        self.assertEqual(Decimal("150000000"), aapl.normalized_value)

    def test_malformed_xml_raises_sec13f_xml_error(self) -> None:
        with self.assertRaises(Sec13FXmlParseError):
            parse_information_table_xml("<informationTable><unclosedTag>", self.filings[0])


class TestPointInTimeCutoffFiltering(unittest.TestCase):
    def setUp(self) -> None:
        self.filings = parse_submissions_json(SAMPLE_SUBMISSIONS_JSON)

    def test_point_in_time_cutoff_filtering(self) -> None:
        # Cutoff as of 2024-05-01 (before 2024-05-15 filing)
        cutoff_may_01 = datetime(2024, 5, 1, 0, 0, tzinfo=timezone.utc)
        available = filter_filings_by_cutoff(self.filings, cutoff_may_01)
        self.assertEqual(1, len(available))
        self.assertEqual("0001193125-24-200001", available[0].accession)

        # Cutoff as of 2024-07-01 (includes 2024-05-15 and 2024-06-20 restatement, but not 2024-08-14)
        cutoff_july_01 = datetime(2024, 7, 1, 0, 0, tzinfo=timezone.utc)
        available_july = filter_filings_by_cutoff(self.filings, cutoff_july_01)
        self.assertEqual(3, len(available_july))
        accessions = [f.accession for f in available_july]
        self.assertNotIn("0001193125-24-200004", accessions)

    def test_date_only_conservative_cutoff(self) -> None:
        # Date-only filing from 2024-05-15 (spans America/New_York day, interval_end in UTC)
        pub_date_only = PublicAvailability.from_source_date("2024-05-15", source_timezone="America/New_York", locator="edgar:date_only")
        f_date_only = Filing13F(
            filing_id="13f:0001067983:date_only",
            manager_cik="0001067983",
            manager_name="BERKSHIRE HATHAWAY INC",
            form=Form13FKind.HR,
            accession="date_only",
            report_period="2024-03-31",
            filed_date="2024-05-15",
            public_availability=pub_date_only,
        )
        # Mid-day cutoff on 2024-05-15: date-only is NOT available before interval_end (conservative upper bound)
        midday_cutoff = datetime(2024, 5, 15, 12, 0, tzinfo=timezone.utc)
        self.assertFalse(pub_date_only.is_point_in_time_available(midday_cutoff))

        # Cutoff after interval_end on 2024-05-16: now available
        after_cutoff = datetime(2024, 5, 16, 12, 0, tzinfo=timezone.utc)
        self.assertTrue(pub_date_only.is_point_in_time_available(after_cutoff))

    def test_naive_cutoff_raises_timezone_error(self) -> None:
        naive_cutoff = datetime(2024, 5, 1, 0, 0)
        with self.assertRaises(TimezoneValidationError):
            filter_filings_by_cutoff(self.filings, naive_cutoff)


class TestAmendmentChainSynthesis(unittest.TestCase):
    def setUp(self) -> None:
        self.filings = parse_submissions_json(SAMPLE_SUBMISSIONS_JSON)
        # Original filing for 2024-03-31
        self.filing_orig = self.filings[1]
        self.hset_orig = parse_information_table_xml(SAMPLE_INFOTABLE_XML_POST_2023, self.filing_orig)

        # Restatement filing for 2024-03-31
        self.filing_restate = self.filings[2]
        # Restatement XML: Apple position revised to 1,200,000 shares ($210M)
        restate_xml = """<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
            <infoTable>
                <nameOfIssuer>APPLE INC</nameOfIssuer>
                <titleOfClass>COM</titleOfClass>
                <cusip>037833100</cusip>
                <value>210000000</value>
                <shrsOrPrnAmt>
                    <sshPrnamt>1200000</sshPrnamt>
                    <sshPrnamtType>SH</sshPrnamtType>
                </shrsOrPrnAmt>
            </infoTable>
        </informationTable>"""
        self.hset_restate = parse_information_table_xml(restate_xml, self.filing_restate)

    def test_amendment_restated_replaces_prior_holdings_when_available(self) -> None:
        pairs = [(self.filing_orig, self.hset_orig), (self.filing_restate, self.hset_restate)]

        # Cutoff BEFORE restatement (2024-06-01): must use original 3 holdings
        cutoff_before = datetime(2024, 6, 1, 0, 0, tzinfo=timezone.utc)
        eff_before = synthesize_effective_holdings("0001067983", "2024-03-31", pairs, cutoff_before)
        self.assertIsNotNone(eff_before)
        self.assertEqual(3, len(eff_before.holdings))
        self.assertFalse(eff_before.has_restatements)
        self.assertEqual(("0001193125-24-200002",), eff_before.contributing_accessions)

        # Cutoff AFTER restatement (2024-07-01): must be completely replaced with restated 1 holding
        cutoff_after = datetime(2024, 7, 1, 0, 0, tzinfo=timezone.utc)
        eff_after = synthesize_effective_holdings("0001067983", "2024-03-31", pairs, cutoff_after)
        self.assertIsNotNone(eff_after)
        self.assertEqual(1, len(eff_after.holdings))
        self.assertTrue(eff_after.has_restatements)
        self.assertIn("0001193125-24-200003", eff_after.contributing_accessions)
        aapl = eff_after.holdings[0]
        self.assertEqual(Decimal("1200000"), aapl.normalized_shares)
        self.assertEqual(Decimal("210000000"), aapl.normalized_value)

    def test_addition_amendment_merges_holdings(self) -> None:
        f_add = Filing13F(
            filing_id="13f:0001067983:add1",
            manager_cik="0001067983",
            manager_name="BERKSHIRE HATHAWAY INC",
            form=Form13FKind.HR_A,
            accession="add1",
            report_period="2024-03-31",
            filed_date="2024-07-15",
            public_availability=PublicAvailability.exact(datetime(2024, 7, 15, tzinfo=timezone.utc), locator="add1"),
            amendment_type=AmendmentType.ADD_NEW_HOLDINGS,
        )
        add_xml = """<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
            <infoTable>
                <nameOfIssuer>CHEVRON CORP</nameOfIssuer>
                <titleOfClass>COM</titleOfClass>
                <cusip>166764100</cusip>
                <value>80000000</value>
                <shrsOrPrnAmt>
                    <sshPrnamt>500000</sshPrnamt>
                    <sshPrnamtType>SH</sshPrnamtType>
                </shrsOrPrnAmt>
            </infoTable>
        </informationTable>"""
        hset_add = parse_information_table_xml(add_xml, f_add)

        pairs = [(self.filing_orig, self.hset_orig), (f_add, hset_add)]
        cutoff = datetime(2024, 8, 1, 0, 0, tzinfo=timezone.utc)
        eff = synthesize_effective_holdings("0001067983", "2024-03-31", pairs, cutoff)
        self.assertIsNotNone(eff)
        # Original 3 + addition 1 = 4 holdings
        self.assertEqual(4, len(eff.holdings))
        self.assertTrue(eff.has_additions)
        self.assertIn("166764100", [h.cusip for h in eff.holdings])

    def test_ambiguous_amendment_does_not_partially_overwrite_snapshot(self) -> None:
        ambiguous = dataclasses.replace(
            self.filing_restate,
            amendment_type=None,
            amendment_number=2,
        )
        pairs = [(self.filing_orig, self.hset_orig), (ambiguous, self.hset_restate)]
        cutoff = datetime(2024, 7, 1, tzinfo=timezone.utc)
        effective = synthesize_effective_holdings("0001067983", "2024-03-31", pairs, cutoff)
        self.assertIsNotNone(effective)
        self.assertTrue(effective.has_unresolved_amendments)
        self.assertEqual(len(self.hset_orig.holdings), len(effective.holdings))

    def test_filing_and_holding_set_identity_mismatch_is_rejected(self) -> None:
        mismatched_set = dataclasses.replace(self.hset_orig, manager_cik="9999999999")
        cutoff = datetime(2024, 6, 1, tzinfo=timezone.utc)
        effective = synthesize_effective_holdings(
            "0001067983", "2024-03-31", [(self.filing_orig, mismatched_set)], cutoff
        )
        self.assertIsNone(effective)

    def test_amendment_with_different_base_accession_is_not_applied(self) -> None:
        wrong_base = dataclasses.replace(self.filing_restate, base_accession="unrelated-accession")
        cutoff = datetime(2024, 7, 1, tzinfo=timezone.utc)
        effective = synthesize_effective_holdings(
            "0001067983", "2024-03-31",
            [(self.filing_orig, self.hset_orig), (wrong_base, self.hset_restate)],
            cutoff,
        )
        self.assertIsNotNone(effective)
        self.assertTrue(effective.has_unresolved_amendments)
        self.assertEqual(len(self.hset_orig.holdings), len(effective.holdings))
        self.assertNotIn(wrong_base.accession, effective.contributing_accessions)

    def test_notice_only_filing_does_not_clear_last_holdings(self) -> None:
        notice = dataclasses.replace(
            self.filing_restate,
            form=Form13FKind.NT,
            amendment_type=None,
            amendment_number=None,
        )
        pairs = [(self.filing_orig, self.hset_orig), (notice, self.hset_restate)]
        cutoff = datetime(2024, 7, 1, tzinfo=timezone.utc)
        effective = synthesize_effective_holdings("0001067983", "2024-03-31", pairs, cutoff)
        self.assertIsNotNone(effective)
        self.assertEqual(len(self.hset_orig.holdings), len(effective.holdings))
        self.assertTrue(effective.has_unresolved_amendments)
        self.assertTrue(any("Notice-only" in warning for warning in effective.parsing_warnings))

    def test_invalid_quantity_row_is_skipped_and_coverage_is_partial(self) -> None:
        malformed = """<informationTable><infoTable><nameOfIssuer>TEST</nameOfIssuer>
        <titleOfClass>COM</titleOfClass><cusip>123456789</cusip><value>100</value>
        <shrsOrPrnAmt><sshPrnamt>NaN</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
        </infoTable></informationTable>"""
        parsed = parse_information_table_xml(malformed, self.filing_orig)
        self.assertEqual((), parsed.holdings)
        self.assertEqual("PARTIAL_MISSING_ROWS", parsed.coverage_status)
        self.assertEqual(1, parsed.missing_row_count)


class TestPortfolioComparison(unittest.TestCase):
    def test_partial_report_cannot_supply_portfolio_weight_denominator(self) -> None:
        prior = HoldingSet13F.create(
            "prior", "manager", "2024-03-31",
            [Holding13F("p1", "prior", "037833100", "APPLE", Decimal("10"), Decimal("100"), Decimal("100"), Decimal("10"), value_scale=Decimal("1"))],
        )
        current = ParsedHoldingSet13F.create_parsed(
            "current", "manager", "2024-06-30",
            [Holding13F("c1", "current", "037833100", "APPLE", Decimal("12"), Decimal("120"), Decimal("120"), Decimal("12"), value_scale=Decimal("1"))],
            total_eligible_value=Decimal("120"),
            missing_row_count=1,
            total_rows_observed=2,
            coverage_status="PARTIAL_MISSING_ROWS",
        )
        comparison = compare_portfolios(prior, current)
        self.assertTrue(comparison.is_comparable)
        self.assertFalse(comparison.is_value_comparable)
        apple = next(change for change in comparison.changes if change.cusip == "037833100")
        self.assertIsNone(apple.prior_weight)
        self.assertIsNone(apple.current_weight)
        self.assertIsNone(apple.weight_change)

    def test_comparison_metrics_and_split_adjustment(self) -> None:
        # Prior period: Q1 with 1,000,000 AAPL shares ($175M)
        f_q1 = Filing13F(
            filing_id="13f:0001067983:q1",
            manager_cik="0001067983",
            manager_name="TEST MGR",
            form=Form13FKind.HR,
            accession="q1",
            report_period="2024-03-31",
            filed_date="2024-05-15",
            public_availability=PublicAvailability.exact(datetime(2024, 5, 15, tzinfo=timezone.utc), locator="q1"),
        )
        h_q1 = [
            Holding13F("h1", "13f:0001067983:q1", "037833100", "APPLE INC", Decimal("1000000"), Decimal("175000000"), Decimal("175000000"), Decimal("1000000")),
            Holding13F("h2", "13f:0001067983:q1", "594918104", "MICROSOFT CORP", Decimal("500000"), Decimal("200000000"), Decimal("200000000"), Decimal("500000")),
        ]
        set_q1 = HoldingSet13F.create("13f:0001067983:q1", "0001067983", "2024-03-31", h_q1)

        # Current period: Q2 with 2,500,000 AAPL shares (following 2:1 stock split) and MSFT sold
        f_q2 = Filing13F(
            filing_id="13f:0001067983:q2",
            manager_cik="0001067983",
            manager_name="TEST MGR",
            form=Form13FKind.HR,
            accession="q2",
            report_period="2024-06-30",
            filed_date="2024-08-14",
            public_availability=PublicAvailability.exact(datetime(2024, 8, 14, tzinfo=timezone.utc), locator="q2"),
        )
        h_q2 = [
            Holding13F("h3", "13f:0001067983:q2", "037833100", "APPLE INC", Decimal("2500000"), Decimal("220000000"), Decimal("220000000"), Decimal("2500000")),
            Holding13F("h4", "13f:0001067983:q2", "02079K107", "ALPHABET INC", Decimal("300000"), Decimal("50000000"), Decimal("50000000"), Decimal("300000")),
        ]
        set_q2 = HoldingSet13F.create("13f:0001067983:q2", "0001067983", "2024-06-30", h_q2)

        # Compare with 2:1 stock split on AAPL
        splits = {"037833100": Decimal("2")}
        comp = compare_portfolios(set_q1, set_q2, split_factors=splits)

        self.assertTrue(comp.is_comparable)
        self.assertEqual(3, len(comp.changes))

        # Check AAPL split-adjusted change
        # Prior raw: 1,000,000 -> split adj: 2,000,000. Current: 2,500,000. Delta = +500,000 (+25%)
        aapl_ch = next(c for c in comp.changes if c.cusip == "037833100")
        self.assertEqual(HoldingChangeStatus.INCREASED, aapl_ch.status)
        self.assertEqual(Decimal("500000"), aapl_ch.share_change)
        self.assertEqual(Decimal("0.25"), aapl_ch.share_change_pct)
        self.assertTrue(aapl_ch.is_split_adjusted)

        # Check Alphabet (New position)
        goog_ch = next(c for c in comp.changes if c.cusip == "02079K107")
        self.assertEqual(HoldingChangeStatus.NEW_POSITION, goog_ch.status)
        self.assertIsNone(goog_ch.prior_shares)
        self.assertEqual(Decimal("300000"), goog_ch.current_shares)

        # Check Microsoft (Closed position under complete report)
        msft_ch = next(c for c in comp.changes if c.cusip == "594918104")
        self.assertEqual(HoldingChangeStatus.CLOSED_POSITION, msft_ch.status)
        self.assertEqual(Decimal("-500000"), msft_ch.share_change)

    def test_absence_not_sold_when_confidential_omission(self) -> None:
        # When confidential omission is flagged, missing position should be NOT_REPORTED, not CLOSED_POSITION
        set_q1 = HoldingSet13F.create(
            "13f:0001067983:q1",
            "0001067983",
            "2024-03-31",
            [Holding13F("h1", "13f:0001067983:q1", "037833100", "APPLE INC", Decimal("100"), Decimal("100"), Decimal("100"), Decimal("100"))],
        )
        set_q2_empty = HoldingSet13F.create(
            "13f:0001067983:q2",
            "0001067983",
            "2024-06-30",
            [],
        )
        comp = compare_portfolios(set_q1, set_q2_empty, is_confidential_omission=True)
        ch = comp.changes[0]
        self.assertEqual(HoldingChangeStatus.NOT_REPORTED, ch.status)
        self.assertEqual(NoticeStatus.CONFIDENTIAL_OMISSION, ch.notice_status)

    def test_incomparability_on_prn_sh_mismatch_and_manager_mismatch(self) -> None:
        # PRN in prior, SH in current for same CUSIP -> INCOMPARABLE, not assumed sold
        h_prn = [Holding13F("h1", "f1", "88160R101", "TESLA", Decimal("10000"), Decimal("10000"), Decimal("10000"), Decimal("10000"), quantity_type=QuantityType.PRN)]
        h_sh = [Holding13F("h2", "f2", "88160R101", "TESLA", Decimal("20000"), Decimal("20000"), Decimal("20000"), Decimal("20000"), quantity_type=QuantityType.SH)]

        set_prn = HoldingSet13F.create("f1", "0001067983", "2024-03-31", h_prn)
        set_sh = HoldingSet13F.create("f2", "0001067983", "2024-06-30", h_sh)

        comp = compare_portfolios(set_prn, set_sh)
        self.assertTrue(comp.is_comparable)
        for ch in comp.changes:
            self.assertEqual(HoldingChangeStatus.INCOMPARABLE, ch.status)

        # Manager mismatch -> is_comparable = False
        h_f3 = [dataclasses.replace(h, filing_id="f3", holding_id=f"f3:{h.cusip}") for h in h_sh]
        set_diff_mgr = HoldingSet13F.create("f3", "0000000001", "2024-06-30", h_f3)
        comp_diff = compare_portfolios(set_prn, set_diff_mgr)
        self.assertFalse(comp_diff.is_comparable)
        self.assertIn("Manager mismatch", comp_diff.incomparable_reasons[0])
        self.assertEqual((), comp_diff.changes)

        # Identical period -> is_comparable = False
        h_f4 = [dataclasses.replace(h, filing_id="f4", holding_id=f"f4:{h.cusip}") for h in h_sh]
        set_same_period = HoldingSet13F.create("f4", "0001067983", "2024-03-31", h_f4)
        comp_same = compare_portfolios(set_prn, set_same_period)
        self.assertFalse(comp_same.is_comparable)
        self.assertIn("Observation periods must be distinct", comp_same.incomparable_reasons[0])


class TestSourceVintageAndMissingRowCoverage(unittest.TestCase):
    def test_source_vintage_pre_and_post_2023(self) -> None:
        xml_one_holding = """<?xml version="1.0"?>
        <informationTable>
            <infoTable>
                <nameOfIssuer>APPLE INC</nameOfIssuer>
                <titleOfClass>COM</titleOfClass>
                <cusip>037833100</cusip>
                <value>1000</value>
                <shrsOrPrnAmt>
                    <sshPrnAmt>100</sshPrnAmt>
                    <sshPrnAmtType>SH</sshPrnAmtType>
                </shrsOrPrnAmt>
            </infoTable>
        </informationTable>"""

        # Pre-2023 filing date: scale = 1000, vintage = PRE_2023_THOUSANDS
        filing_pre = Filing13F(
            filing_id="f_pre",
            manager_cik="0001067983",
            manager_name="TEST MGR",
            form=Form13FKind.HR,
            accession="acc_pre",
            report_period="2022-09-30",
            filed_date="2022-11-14",
            public_availability=PublicAvailability.exact(datetime(2022, 11, 14, tzinfo=timezone.utc), locator="acc_pre"),
        )
        set_pre = parse_information_table_xml(xml_one_holding, filing_pre)
        self.assertEqual(Decimal("1000"), set_pre.holdings[0].value_scale)
        self.assertEqual(Decimal("1000000"), set_pre.holdings[0].normalized_value)
        self.assertEqual(Decimal("1000000"), set_pre.total_eligible_value)
        self.assertEqual("PRE_2023_THOUSANDS", set_pre.source_vintage)
        self.assertFalse(set_pre.scale_uncertain)
        self.assertEqual("COMPLETE", set_pre.coverage_status)

        # Post-2023 filing date: scale = 1, vintage = POST_2023_DOLLARS
        filing_post = Filing13F(
            filing_id="f_post",
            manager_cik="0001067983",
            manager_name="TEST MGR",
            form=Form13FKind.HR,
            accession="acc_post",
            report_period="2024-03-31",
            filed_date="2024-05-15",
            public_availability=PublicAvailability.exact(datetime(2024, 5, 15, tzinfo=timezone.utc), locator="acc_post"),
        )
        set_post = parse_information_table_xml(xml_one_holding, filing_post)
        self.assertEqual(Decimal("1"), set_post.holdings[0].value_scale)
        self.assertEqual(Decimal("1000"), set_post.holdings[0].normalized_value)
        self.assertEqual(Decimal("1000"), set_post.total_eligible_value)
        self.assertEqual("POST_2023_DOLLARS", set_post.source_vintage)
        self.assertFalse(set_post.scale_uncertain)
        self.assertEqual("COMPLETE", set_post.coverage_status)

        # Explicit override scale
        set_override = parse_information_table_xml(xml_one_holding, filing_post, default_scale=Decimal("500"))
        self.assertEqual(Decimal("500"), set_override.holdings[0].value_scale)
        self.assertEqual("EXPLICIT_OVERRIDE", set_override.source_vintage)

    def test_source_vintage_missing_filed_date_unavailable(self) -> None:
        xml = """<?xml version="1.0"?>
        <informationTable>
            <infoTable>
                <nameOfIssuer>APPLE INC</nameOfIssuer>
                <cusip>037833100</cusip>
                <value>500</value>
                <shrsOrPrnAmt><sshPrnAmt>50</sshPrnAmt><sshPrnAmtType>SH</sshPrnAmtType></shrsOrPrnAmt>
            </infoTable>
        </informationTable>"""
        # Filing lacking filed_date -> DO NOT guess from report_period, DO NOT default to 1
        filing_no_date = Filing13F(
            filing_id="f_no_date",
            manager_cik="0001067983",
            manager_name="TEST MGR",
            form=Form13FKind.HR,
            accession="acc_no_date",
            report_period="2022-09-30",
            filed_date="",
            public_availability=PublicAvailability.unknown(),
        )
        h_set = parse_information_table_xml(xml, filing_no_date)
        self.assertTrue(h_set.scale_uncertain)
        self.assertEqual("MISSING_FILING_DATE", h_set.source_vintage)
        self.assertEqual("UNCERTAIN_SCALE", h_set.coverage_status)
        self.assertIsNone(h_set.holdings[0].value_scale)
        self.assertEqual(Decimal("500"), h_set.holdings[0].raw_value)
        self.assertEqual(Decimal("0"), h_set.holdings[0].normalized_value)
        self.assertEqual(Decimal("0"), h_set.total_eligible_value)
        self.assertTrue(any("lacks filed_date" in w for w in h_set.parsing_warnings))

    def test_source_vintage_invalid_filed_date_unavailable(self) -> None:
        xml = """<?xml version="1.0"?>
        <informationTable>
            <infoTable>
                <nameOfIssuer>APPLE INC</nameOfIssuer>
                <cusip>037833100</cusip>
                <value>500</value>
                <shrsOrPrnAmt><sshPrnAmt>50</sshPrnAmt><sshPrnAmtType>SH</sshPrnAmtType></shrsOrPrnAmt>
            </infoTable>
        </informationTable>"""
        filing_bad_date = Filing13F(
            filing_id="f_bad_date",
            manager_cik="0001067983",
            manager_name="TEST MGR",
            form=Form13FKind.HR,
            accession="acc_bad_date",
            report_period="2024-03-31",
            filed_date="NOT_A_DATE",
            public_availability=PublicAvailability.unknown(),
        )
        h_set = parse_information_table_xml(xml, filing_bad_date)
        self.assertTrue(h_set.scale_uncertain)
        self.assertEqual("INVALID_FILING_DATE", h_set.source_vintage)
        self.assertEqual("UNCERTAIN_SCALE", h_set.coverage_status)
        self.assertIsNone(h_set.holdings[0].value_scale)
        self.assertEqual(Decimal("0"), h_set.total_eligible_value)

    def test_missing_row_coverage_and_absence_safeguard(self) -> None:
        # XML with 1 valid row, 1 missing CUSIP row, 1 missing value row
        xml_with_bad_rows = """<?xml version="1.0"?>
        <informationTable>
            <infoTable>
                <nameOfIssuer>APPLE INC</nameOfIssuer>
                <cusip>037833100</cusip>
                <value>1000</value>
                <shrsOrPrnAmt><sshPrnAmt>100</sshPrnAmt><sshPrnAmtType>SH</sshPrnAmtType></shrsOrPrnAmt>
            </infoTable>
            <infoTable>
                <nameOfIssuer>BROKEN CUSIP</nameOfIssuer>
                <value>2000</value>
            </infoTable>
            <infoTable>
                <nameOfIssuer>BROKEN VALUE</nameOfIssuer>
                <cusip>594918104</cusip>
            </infoTable>
        </informationTable>"""
        filing = Filing13F(
            filing_id="f_bad_rows",
            manager_cik="0001067983",
            manager_name="TEST MGR",
            form=Form13FKind.HR,
            accession="acc_bad_rows",
            report_period="2024-06-30",
            filed_date="",
            public_availability=PublicAvailability.exact(datetime(2024, 8, 14, tzinfo=timezone.utc), locator="acc_bad_rows"),
        )
        set_curr = parse_information_table_xml(xml_with_bad_rows, filing)
        self.assertEqual(1, len(set_curr.holdings))
        self.assertEqual(2, set_curr.missing_row_count)
        self.assertEqual(3, set_curr.total_rows_observed)
        self.assertEqual("PARTIAL_MISSING_ROWS", set_curr.coverage_status)
        self.assertTrue(set_curr.scale_uncertain)
        self.assertEqual("MISSING_FILING_DATE", set_curr.source_vintage)
        self.assertEqual(4, len(set_curr.parsing_warnings))
        self.assertTrue(any("lacks filed_date" in warning for warning in set_curr.parsing_warnings))
        self.assertTrue(any("Row 1" in warning and "missing CUSIP" in warning for warning in set_curr.parsing_warnings))
        self.assertTrue(any("Row 2" in warning and "missing value" in warning for warning in set_curr.parsing_warnings))
        self.assertTrue(any("2 of 3 rows skipped" in warning for warning in set_curr.parsing_warnings))
        self.assertEqual(Decimal("0"), set_curr.total_eligible_value)

        # Build prior set with AAPL and MSFT
        prior_h = [
            Holding13F("h_p1", "f_p", "037833100", "APPLE INC", Decimal("100"), Decimal("1000"), Decimal("1000"), Decimal("100")),
            Holding13F("h_p2", "f_p", "594918104", "MICROSOFT CORP", Decimal("50"), Decimal("500"), Decimal("500"), Decimal("50")),
        ]
        set_prior = HoldingSet13F.create("f_p", "0001067983", "2024-03-31", prior_h)

        # Compare: MSFT is absent in current set. Because current set has missing rows (PARTIAL),
        # MSFT must NOT be marked CLOSED_POSITION; it must be preserved as NOT_REPORTED!
        comp = compare_portfolios(set_prior, set_curr)
        self.assertEqual("PARTIAL", comp.coverage_status)
        msft_ch = next(c for c in comp.changes if c.cusip == "594918104")
        self.assertEqual(HoldingChangeStatus.NOT_REPORTED, msft_ch.status)
        self.assertNotEqual(HoldingChangeStatus.CLOSED_POSITION, msft_ch.status)

    def test_value_comparison_unavailable_when_scale_uncertain(self) -> None:
        xml_prior = """<?xml version="1.0"?>
        <informationTable>
            <infoTable>
                <nameOfIssuer>APPLE INC</nameOfIssuer>
                <cusip>037833100</cusip>
                <value>1000</value>
                <shrsOrPrnAmt><sshPrnAmt>100</sshPrnAmt><sshPrnAmtType>SH</sshPrnAmtType></shrsOrPrnAmt>
            </infoTable>
        </informationTable>"""
        filing_prior_uncertain = Filing13F(
            filing_id="f_unc",
            manager_cik="0001067983",
            manager_name="TEST MGR",
            form=Form13FKind.HR,
            accession="acc_unc",
            report_period="2024-03-31",
            filed_date="",
            public_availability=PublicAvailability.unknown(),
        )
        set_prior = parse_information_table_xml(xml_prior, filing_prior_uncertain)

        filing_curr_normal = Filing13F(
            filing_id="f_norm",
            manager_cik="0001067983",
            manager_name="TEST MGR",
            form=Form13FKind.HR,
            accession="acc_norm",
            report_period="2024-06-30",
            filed_date="2024-08-14",
            public_availability=PublicAvailability.exact(datetime(2024, 8, 14, tzinfo=timezone.utc), locator="acc_norm"),
        )
        set_curr = parse_information_table_xml(xml_prior, filing_curr_normal)

        comp = compare_portfolios(set_prior, set_curr)
        self.assertTrue(comp.is_comparable)
        self.assertFalse(comp.is_value_comparable)
        self.assertTrue(any("Reported values and weights unavailable" in w for w in comp.comparison_warnings))
        ch = comp.changes[0]
        self.assertIsNone(ch.prior_value)
        self.assertIsNone(ch.prior_weight)
        self.assertIsNone(ch.weight_change)
        self.assertEqual(Decimal("0"), ch.share_change)


if __name__ == "__main__":
    unittest.main()
