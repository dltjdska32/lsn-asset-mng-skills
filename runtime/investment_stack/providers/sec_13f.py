"""SEC Form 13F submissions metadata parsing, Information Table XML extraction, and point-in-time filtering."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from investment_stack.contracts.codec import parse_finite_decimal
from investment_stack.contracts.context import PublicAvailability, PublicAvailabilityKind
from investment_stack.contracts.errors import (
    ContractValidationError,
    PointInTimeError,
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
from investment_stack.institutional.models import ParsedHoldingSet13F
from investment_stack.providers.http import (
    ProviderTransportError,
    Transport,
    fetch_json,
    urllib_transport,
)

logger = logging.getLogger(__name__)

# SEC Form 13F modernization effective date (SEC Release No. 34-95148)
# Prior to this date, values were reported rounded to thousands ($1,000s).
# On/after this date, values are reported rounded to the nearest dollar ($1).
SEC_13F_VALUE_UNIT_CHANGE_DATE = "2023-01-03"


class Sec13FError(Exception):
    """Base error for SEC 13F parsing and collection."""


class Sec13FXmlParseError(Sec13FError):
    """Raised when 13F Information Table XML cannot be parsed."""


class Sec13FSubmissionsError(Sec13FError):
    """Raised when EDGAR Submissions JSON cannot be parsed or lacks required fields."""


def _local_tag(elem: ET.Element) -> str:
    """Return XML element tag stripped of any namespace prefix."""
    return elem.tag.split("}")[-1].lower()


def _find_child_text(parent: ET.Element, *tag_names: str) -> str | None:
    """Search immediate children for matching local tag name (case-insensitive) and return stripped text."""
    target_names = {t.lower() for t in tag_names}
    for child in parent:
        if _local_tag(child) in target_names:
            if child.text:
                val = child.text.strip()
                if val:
                    return val
    return None


def _find_child_elem(parent: ET.Element, *tag_names: str) -> ET.Element | None:
    """Search immediate children for matching local tag name (case-insensitive)."""
    target_names = {t.lower() for t in tag_names}
    for child in parent:
        if _local_tag(child) in target_names:
            return child
    return None


def parse_submissions_json(
    data: dict[str, Any],
    *,
    forms: tuple[str, ...] = ("13F-HR", "13F-HR/A", "13F-NT"),
) -> list[Filing13F]:
    """Parse EDGAR submissions API JSON into structured Filing13F headers.

    Extracts accession numbers, report dates, filing dates, acceptance timestamps,
    and constructs verified point-in-time PublicAvailability envelopes.
    """
    if not isinstance(data, dict):
        raise Sec13FSubmissionsError("Submissions data must be a dictionary")

    raw_cik = str(data.get("cik", "")).strip()
    if not raw_cik:
        raise Sec13FSubmissionsError("Submissions data missing 'cik'")
    manager_cik = raw_cik.zfill(10)
    manager_name = str(data.get("name", "")).strip() or f"CIK-{manager_cik}"

    filings_obj = data.get("filings")
    if not isinstance(filings_obj, dict):
        raise Sec13FSubmissionsError("Submissions data missing 'filings' object")

    recent = filings_obj.get("recent")
    if not isinstance(recent, dict):
        raise Sec13FSubmissionsError("Submissions filings missing 'recent' columnar arrays")

    accession_list = recent.get("accessionNumber", [])
    form_list = recent.get("form", [])
    filing_date_list = recent.get("filingDate", [])
    report_date_list = recent.get("reportDate", [])
    acceptance_dt_list = recent.get("acceptanceDateTime", [])
    primary_doc_list = recent.get("primaryDocument", [])
    primary_desc_list = recent.get("primaryDocDescription", [])
    file_number_list = recent.get("fileNumber", [])

    n_rows = len(accession_list)
    allowed_forms = set(forms)
    results: list[Filing13F] = []

    for i in range(n_rows):
        form_str = str(form_list[i]).strip() if i < len(form_list) else ""
        if form_str not in allowed_forms:
            continue

        accession = str(accession_list[i]).strip()
        filing_date = str(filing_date_list[i]).strip() if i < len(filing_date_list) else ""
        report_period = str(report_date_list[i]).strip() if i < len(report_date_list) else ""
        accepted_at_str = str(acceptance_dt_list[i]).strip() if i < len(acceptance_dt_list) else ""
        primary_doc = str(primary_doc_list[i]).strip() if i < len(primary_doc_list) else ""
        primary_desc = str(primary_desc_list[i]).strip() if i < len(primary_desc_list) else ""
        file_num = str(file_number_list[i]).strip() if i < len(file_number_list) else ""

        # Construct PublicAvailability
        pub: PublicAvailability
        if accepted_at_str:
            try:
                # ISO-8601 parsing with UTC normalization
                dt_iso = accepted_at_str.replace("Z", "+00:00")
                parsed_dt = datetime.fromisoformat(dt_iso)
                pub = PublicAvailability.exact(parsed_dt, locator=f"edgar:{accession}")
            except Exception as exc:
                logger.warning("Failed parsing acceptanceDateTime %r for %s: %s", accepted_at_str, accession, exc)
                if filing_date:
                    pub = PublicAvailability.from_source_date(
                        filing_date, source_timezone="America/New_York", locator=f"edgar:{accession}"
                    )
                else:
                    pub = PublicAvailability(kind=PublicAvailabilityKind.UNKNOWN)
        elif filing_date:
            pub = PublicAvailability.from_source_date(
                filing_date, source_timezone="America/New_York", locator=f"edgar:{accession}"
            )
        else:
            pub = PublicAvailability(kind=PublicAvailabilityKind.UNKNOWN)

        # Form kind
        form_kind: Form13FKind
        if form_str == "13F-HR":
            form_kind = Form13FKind.HR
        elif form_str == "13F-HR/A":
            form_kind = Form13FKind.HR_A
        elif form_str == "13F-NT":
            form_kind = Form13FKind.NT
        else:
            form_kind = Form13FKind(form_str)

        # Amendment detection
        am_type: AmendmentType | None = None
        am_num: int | None = None
        if form_kind == Form13FKind.HR_A:
            desc_upper = primary_desc.upper()
            if "RESTATE" in desc_upper:
                am_type = AmendmentType.RESTATED
            elif "ADD" in desc_upper or "NEW HOLDING" in desc_upper:
                am_type = AmendmentType.ADD_NEW_HOLDINGS

        # Notice status
        notice_status = NoticeStatus.NOTICE_ONLY if form_kind == Form13FKind.NT else NoticeStatus.COMPLETE

        filing = Filing13F(
            filing_id=f"13f:{manager_cik}:{accession}",
            manager_cik=manager_cik,
            manager_name=manager_name,
            form=form_kind,
            accession=accession,
            report_period=report_period,
            filed_date=filing_date,
            public_availability=pub,
            accepted_at=accepted_at_str or None,
            amendment_number=am_num,
            amendment_type=am_type,
            table_locator=primary_doc or None,
            notice_status=notice_status,
        )
        results.append(filing)

    # Return chronological order by acceptanceDateTime / filingDate
    results.sort(
        key=lambda f: (
            f.public_availability.public_available_at or datetime.min.replace(tzinfo=timezone.utc),
            f.filed_date,
            f.accession,
        )
    )
    return results


def parse_information_table_xml(
    xml_content: str | bytes,
    filing: Filing13F,
    *,
    default_scale: Decimal | None = None,
) -> ParsedHoldingSet13F:
    """Parse Form 13F Information Table XML into structured ParsedHoldingSet13F.

    Handles namespace variance across v1/v2 schemas, separates SH vs PRN,
    isolates PUT/CALL options, and applies the 2023-01-03 $1,000 -> $1 scale transition.

    Strict Invariants:
    - Never guess schema vintage from report_period (amendments for past periods may use current schema).
    - Never default to 1 if schema vintage is unknown.
    - If filed_date is missing, invalid, or schema is ambiguous, value_scale=None is assigned,
      raw_value is preserved, total_eligible_value is 0, and value comparison is marked unavailable.
    - Rows missing CUSIP or missing/non-finite values are recorded as skipped with warnings,
      and coverage_status is marked PARTIAL_MISSING_ROWS rather than claiming complete coverage.
    """
    if isinstance(xml_content, str):
        xml_bytes = xml_content.encode("utf-8")
    else:
        xml_bytes = xml_content

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise Sec13FXmlParseError(f"Failed to parse 13F Information Table XML: {exc}") from exc

    # Locate all <infoTable> elements regardless of namespace
    info_table_elems = [elem for elem in root.iter() if _local_tag(elem) == "infotable"]
    if not info_table_elems and _local_tag(root) == "infotable":
        info_table_elems = [root]

    # Value scale detection:
    # Rule: On/after 2023-01-03, values are reported in exact dollars ($1).
    # Prior to 2023-01-03, values were reported in thousands of dollars ($1,000s).
    value_scale: Decimal | None = None
    scale_uncertain = False
    source_vintage = "UNKNOWN"
    parsing_warnings: list[str] = []

    if default_scale is not None:
        value_scale = parse_finite_decimal(default_scale)
        scale_uncertain = False
        source_vintage = "EXPLICIT_OVERRIDE"
    elif filing.filed_date:
        is_valid_date = False
        try:
            datetime.fromisoformat(filing.filed_date)
            is_valid_date = True
        except Exception:
            is_valid_date = False

        if is_valid_date:
            if filing.filed_date < SEC_13F_VALUE_UNIT_CHANGE_DATE:
                value_scale = Decimal("1000")
                source_vintage = "PRE_2023_THOUSANDS"
            else:
                value_scale = Decimal("1")
                source_vintage = "POST_2023_DOLLARS"
        else:
            value_scale = None
            scale_uncertain = True
            source_vintage = "INVALID_FILING_DATE"
            parsing_warnings.append(
                f"Filing filed_date '{filing.filed_date}' is not a valid ISO date; "
                f"value scale cannot be verified from schema vintage"
            )
    else:
        # filed_date is absent. Strictly do NOT guess from report_period.
        value_scale = None
        scale_uncertain = True
        source_vintage = "MISSING_FILING_DATE"
        parsing_warnings.append(
            "Filing lacks filed_date; value scale cannot be determined (report_period is not used for schema vintage)"
        )

    holdings: list[Holding13F] = []
    total_rows = len(info_table_elems)
    missing_row_count = 0

    for index, elem in enumerate(info_table_elems):
        issuer_name = _find_child_text(elem, "nameofissuer", "name_of_issuer") or "UNKNOWN"
        security_class = _find_child_text(elem, "titleofclass", "title_of_class")
        cusip = _find_child_text(elem, "cusip")
        if not cusip:
            missing_row_count += 1
            parsing_warnings.append(f"Row {index}: missing CUSIP; row skipped from holdings")
            continue
        cusip = cusip.upper().strip()

        raw_val_str = _find_child_text(elem, "value")
        if raw_val_str is None or not raw_val_str.strip():
            missing_row_count += 1
            parsing_warnings.append(f"Row {index} ({cusip}): missing value element; row skipped from holdings")
            continue
        try:
            raw_val = parse_finite_decimal(raw_val_str)
        except Exception as exc:
            missing_row_count += 1
            parsing_warnings.append(f"Row {index} ({cusip}): invalid non-finite value '{raw_val_str}': {exc}; row skipped")
            continue

        # Quantity and quantity type
        shrs_elem = _find_child_elem(elem, "shrsorprnamt", "shrs_or_prn_amt")
        raw_qty: Decimal = Decimal("0")
        qty_type = QuantityType.SH
        if shrs_elem is not None:
            raw_qty_str = _find_child_text(shrs_elem, "sshprnamt", "ssh_prn_amt", "shares")
            if raw_qty_str is not None:
                try:
                    raw_qty = parse_finite_decimal(raw_qty_str)
                except Exception:
                    raw_qty = Decimal("0")
            qty_type_str = _find_child_text(shrs_elem, "sshprnamttype", "ssh_prn_amt_type", "type")
            if qty_type_str and qty_type_str.upper() == "PRN":
                qty_type = QuantityType.PRN

        # Put/Call option distinction
        put_call_str = _find_child_text(elem, "putcall", "put_call")
        put_call = PutCall.NONE
        if put_call_str:
            pc_upper = put_call_str.upper()
            if pc_upper == "PUT":
                put_call = PutCall.PUT
            elif pc_upper == "CALL":
                put_call = PutCall.CALL

        # Investment discretion & other manager
        discretion = _find_child_text(elem, "investmentdiscretion", "investment_discretion")
        other_mgr = _find_child_text(elem, "othermanager", "other_manager")

        # Voting authority
        v_sole: Decimal | None = None
        v_shared: Decimal | None = None
        v_none: Decimal | None = None
        voting_elem = _find_child_elem(elem, "votingauthority", "voting_authority")
        if voting_elem is not None:
            s_str = _find_child_text(voting_elem, "sole")
            sh_str = _find_child_text(voting_elem, "shared")
            n_str = _find_child_text(voting_elem, "none")
            if s_str is not None:
                try:
                    v_sole = parse_finite_decimal(s_str)
                except Exception:
                    pass
            if sh_str is not None:
                try:
                    v_shared = parse_finite_decimal(sh_str)
                except Exception:
                    pass
            if n_str is not None:
                try:
                    v_none = parse_finite_decimal(n_str)
                except Exception:
                    pass

        # Normalized values
        # Invariant: Raw value is always preserved in raw_value.
        # If value_scale is known, normalized_value = raw_val * value_scale.
        # If value_scale is unknown (None), normalized_value is Decimal("0") (unscaled) and value_scale is None,
        # indicating value comparison is unavailable.
        if value_scale is not None:
            norm_val = raw_val * value_scale
            h_scale = value_scale
        else:
            norm_val = Decimal("0")
            h_scale = None

        norm_shares = raw_qty
        holding_id = f"{filing.filing_id}:{cusip}:{index}"
        holding = Holding13F(
            holding_id=holding_id,
            filing_id=filing.filing_id,
            cusip=cusip,
            issuer_name=issuer_name,
            raw_quantity=raw_qty,
            raw_value=raw_val,
            normalized_value=norm_val,
            normalized_shares=norm_shares,
            security_class=security_class,
            put_call=put_call,
            quantity_type=qty_type,
            value_currency="USD",
            value_scale=h_scale,
            discretion=discretion,
            voting_sole=v_sole,
            voting_shared=v_shared,
            voting_none=v_none,
        )
        holdings.append(holding)

    # Coverage status determination
    if missing_row_count > 0:
        coverage_status = "PARTIAL_MISSING_ROWS"
        parsing_warnings.append(
            f"Coverage is PARTIAL: {missing_row_count} of {total_rows} rows skipped due to missing/invalid CUSIP or value"
        )
    elif scale_uncertain:
        coverage_status = "UNCERTAIN_SCALE"
        parsing_warnings.append(
            "Coverage status is UNCERTAIN_SCALE: value scale could not be verified; value comparison unavailable"
        )
    else:
        coverage_status = "COMPLETE"

    # Separation of raw values and eligible total:
    # If scale is uncertain, total eligible value is 0; cannot assert total dollar valuation.
    if scale_uncertain:
        total_eligible = Decimal("0")
    else:
        total_eligible = sum((h.normalized_value for h in holdings), Decimal("0"))

    is_amended = filing.form == Form13FKind.HR_A or filing.amendment_type is not None

    return ParsedHoldingSet13F.create_parsed(
        filing_id=filing.filing_id,
        manager_cik=filing.manager_cik,
        report_period=filing.report_period,
        holdings=holdings,
        total_eligible_value=total_eligible,
        is_amended=is_amended,
        parsing_warnings=tuple(parsing_warnings),
        missing_row_count=missing_row_count,
        total_rows_observed=total_rows,
        coverage_status=coverage_status,
        scale_uncertain=scale_uncertain,
        source_vintage=source_vintage,
    )


def filter_filings_by_cutoff(
    filings: Iterable[Filing13F],
    cutoff: datetime,
) -> list[Filing13F]:
    """Strict point-in-time cutoff filter.

    Returns only filings verifiably public at or before cutoff.
    Raises TimezoneValidationError if cutoff is timezone-naive.
    """
    if cutoff.tzinfo is None:
        raise TimezoneValidationError("Cutoff datetime must be timezone-aware")

    eligible = [f for f in filings if f.public_availability.is_point_in_time_available(cutoff)]
    eligible.sort(
        key=lambda f: (
            f.public_availability.public_available_at or datetime.min.replace(tzinfo=timezone.utc),
            f.filed_date,
            f.accession,
        )
    )
    return eligible


@dataclass(slots=True)
class Sec13FAdapter:
    """Network-injectable SEC EDGAR Form 13F provider adapter."""

    transport: Transport = urllib_transport
    timeout: float = 15.0
    user_agent: str = "investment-stack/0.1 (research@example.com)"
    name: str = "sec_13f"

    def fetch_submissions(self, cik: str) -> list[Filing13F]:
        """Fetch and parse submissions JSON for a manager CIK."""
        cik_digits = "".join(c for c in cik if c.isdigit())
        if not cik_digits:
            raise Sec13FSubmissionsError(f"Invalid non-numeric CIK: {cik}")
        padded_cik = cik_digits.zfill(10)
        url = f"https://data.sec.gov/submissions/CIK{padded_cik}.json"
        headers = {
            "User-Agent": self.user_agent,
            "Accept-Encoding": "gzip, deflate",
        }
        data = fetch_json(url, headers=headers, timeout=self.timeout, transport=self.transport)
        return parse_submissions_json(data)

    def fetch_information_table(
        self,
        url: str,
        filing: Filing13F,
        *,
        default_scale: Decimal | None = None,
    ) -> HoldingSet13F:
        """Fetch and parse Information Table XML from a given archive URL."""
        headers = {
            "User-Agent": self.user_agent,
            "Accept-Encoding": "gzip, deflate",
        }
        xml_bytes = self.transport(url, headers, self.timeout)
        return parse_information_table_xml(xml_bytes, filing, default_scale=default_scale)


__all__ = [
    "ParsedHoldingSet13F",
    "SEC_13F_VALUE_UNIT_CHANGE_DATE",
    "Sec13FAdapter",
    "Sec13FError",
    "Sec13FSubmissionsError",
    "Sec13FXmlParseError",
    "filter_filings_by_cutoff",
    "parse_information_table_xml",
    "parse_submissions_json",
]
