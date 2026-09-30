"""Institutional 13F filing models, holdings, and restatement tracking."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any, Iterable

from investment_stack.contracts.codec import (
    parse_finite_decimal,
    parse_strict_bool,
    register_decoder,
)
from investment_stack.contracts.context import PublicAvailability
from investment_stack.contracts.errors import (
    ContractValidationError,
    DecimalValidationError,
)


class Form13FKind(StrEnum):
    HR = "13F-HR"
    HR_A = "13F-HR/A"
    NT = "13F-NT"


class AmendmentType(StrEnum):
    RESTATED = "RESTATED"
    ADD_NEW_HOLDINGS = "ADD_NEW_HOLDINGS"


class NoticeStatus(StrEnum):
    COMPLETE = "COMPLETE"
    CONFIDENTIAL_OMISSION = "CONFIDENTIAL_OMISSION"
    NOTICE_ONLY = "NOTICE_ONLY"


class PutCall(StrEnum):
    NONE = "NONE"
    PUT = "PUT"
    CALL = "CALL"


class QuantityType(StrEnum):
    SH = "SH"
    PRN = "PRN"


@dataclass(frozen=True, slots=True)
class Filing13F:
    """Institutional investment manager 13F filing header with amendment and access metadata."""

    filing_id: str
    manager_cik: str
    manager_name: str
    form: Form13FKind | str
    accession: str
    report_period: str
    filed_date: str
    public_availability: PublicAvailability
    accepted_at: str | None = None
    amendment_number: int | None = None
    amendment_type: AmendmentType | str | None = None
    base_accession: str | None = None
    table_locator: str | None = None
    notice_status: NoticeStatus | str = NoticeStatus.COMPLETE

    def __post_init__(self) -> None:
        if not self.filing_id or not self.manager_cik or not self.accession:
            raise ContractValidationError("filing_id, manager_cik, accession must be non-empty strings")
        if self.amendment_number is not None and self.amendment_number < 0:
            raise ContractValidationError("amendment_number must be non-negative")


@dataclass(frozen=True, slots=True)
class Holding13F:
    """A single security holding record reported in a 13F information table."""

    holding_id: str
    filing_id: str
    cusip: str
    issuer_name: str
    raw_quantity: Decimal
    raw_value: Decimal
    normalized_value: Decimal
    normalized_shares: Decimal
    security_class: str | None = None
    put_call: PutCall | str = PutCall.NONE
    quantity_type: QuantityType | str = QuantityType.SH
    value_currency: str = "USD"
    value_scale: Decimal | None = None
    mapped_instrument_id: str | None = None
    discretion: str | None = None
    voting_sole: Decimal | None = None
    voting_shared: Decimal | None = None
    voting_none: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.holding_id or not self.filing_id or not self.cusip:
            raise ContractValidationError("holding_id, filing_id, cusip must be non-empty strings")

        rq = parse_finite_decimal(self.raw_quantity)
        rv = parse_finite_decimal(self.raw_value)
        nv = parse_finite_decimal(self.normalized_value)
        ns = parse_finite_decimal(self.normalized_shares)
        vs = parse_finite_decimal(self.value_scale) if self.value_scale is not None else None

        if rq < 0 or rv < 0 or nv < 0 or ns < 0 or (vs is not None and vs <= 0):
            raise DecimalValidationError("Holding quantities and values must be non-negative; scale must be positive")

        if rq != self.raw_quantity:
            object.__setattr__(self, "raw_quantity", rq)
        if rv != self.raw_value:
            object.__setattr__(self, "raw_value", rv)
        if nv != self.normalized_value:
            object.__setattr__(self, "normalized_value", nv)
        if ns != self.normalized_shares:
            object.__setattr__(self, "normalized_shares", ns)
        if vs != self.value_scale:
            object.__setattr__(self, "value_scale", vs)

        for attr in ("voting_sole", "voting_shared", "voting_none"):
            v = getattr(self, attr)
            if v is not None:
                v_finite = parse_finite_decimal(v)
                if v_finite < 0:
                    raise DecimalValidationError(f"{attr} must be non-negative")
                if v_finite != v:
                    object.__setattr__(self, attr, v_finite)


@dataclass(frozen=True, slots=True)
class HoldingSet13F:
    """A complete, coherent snapshot of holdings reported by a manager for a period."""

    filing_id: str
    manager_cik: str
    report_period: str
    holdings: tuple[Holding13F, ...]
    total_eligible_value: Decimal
    is_amended: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.is_amended, bool):
            raise ContractValidationError(f"is_amended must be bool, got {type(self.is_amended).__name__}")

    @classmethod
    def create(
        cls,
        filing_id: str,
        manager_cik: str,
        report_period: str,
        holdings: Iterable[Holding13F],
        *,
        is_amended: bool = False,
    ) -> HoldingSet13F:
        h_list = list(holdings)
        for h in h_list:
            if h.filing_id != filing_id:
                raise ContractValidationError(
                    f"Holding {h.holding_id} filing_id ({h.filing_id}) does not match HoldingSet ({filing_id})"
                )
        sorted_holdings = tuple(
            sorted(
                h_list,
                key=lambda h: (h.cusip, h.security_class or "", str(h.put_call), h.holding_id),
            )
        )
        total_val = sum((h.normalized_value for h in sorted_holdings), Decimal("0"))
        return cls(
            filing_id=filing_id,
            manager_cik=manager_cik,
            report_period=report_period,
            holdings=sorted_holdings,
            total_eligible_value=total_val,
            is_amended=is_amended,
        )


# Decoders
def _decode_filing_13f(payload: dict[str, Any]) -> Filing13F:
    allowed_keys = {
        "filing_id",
        "manager_cik",
        "manager_name",
        "form",
        "accession",
        "report_period",
        "filed_date",
        "public_availability",
        "accepted_at",
        "amendment_number",
        "amendment_type",
        "base_accession",
        "table_locator",
        "notice_status",
    }
    extra = set(payload.keys()) - allowed_keys
    if extra:
        raise ContractValidationError(f"Filing13F payload has extra keys: {sorted(extra)}")

    required_keys = {
        "filing_id",
        "manager_cik",
        "manager_name",
        "form",
        "accession",
        "report_period",
        "filed_date",
        "public_availability",
    }
    missing = required_keys - set(payload.keys())
    if missing:
        raise ContractValidationError(f"Filing13F payload missing required keys: {sorted(missing)}")

    from investment_stack.contracts.codec import decode_contract

    pub = decode_contract(payload["public_availability"], expected_kind="PublicAvailability")
    am_num = int(payload["amendment_number"]) if payload.get("amendment_number") is not None else None
    am_type = AmendmentType(payload["amendment_type"]) if payload.get("amendment_type") else None

    return Filing13F(
        filing_id=payload["filing_id"],
        manager_cik=payload["manager_cik"],
        manager_name=payload["manager_name"],
        form=Form13FKind(payload["form"]),
        accession=payload["accession"],
        report_period=payload["report_period"],
        filed_date=payload["filed_date"],
        public_availability=pub,
        accepted_at=payload.get("accepted_at"),
        amendment_number=am_num,
        amendment_type=am_type,
        base_accession=payload.get("base_accession"),
        table_locator=payload.get("table_locator"),
        notice_status=NoticeStatus(payload.get("notice_status", "COMPLETE")),
    )


def _decode_holding_13f(payload: dict[str, Any]) -> Holding13F:
    allowed_keys = {
        "holding_id",
        "filing_id",
        "cusip",
        "issuer_name",
        "raw_quantity",
        "raw_value",
        "normalized_value",
        "normalized_shares",
        "security_class",
        "put_call",
        "quantity_type",
        "value_currency",
        "value_scale",
        "mapped_instrument_id",
        "discretion",
        "voting_sole",
        "voting_shared",
        "voting_none",
    }
    extra = set(payload.keys()) - allowed_keys
    if extra:
        raise ContractValidationError(f"Holding13F payload has extra keys: {sorted(extra)}")

    required_keys = {
        "holding_id",
        "filing_id",
        "cusip",
        "issuer_name",
        "raw_quantity",
        "raw_value",
        "normalized_value",
        "normalized_shares",
    }
    missing = required_keys - set(payload.keys())
    if missing:
        raise ContractValidationError(f"Holding13F payload missing required keys: {sorted(missing)}")

    vs_raw = payload.get("value_scale")
    vs = parse_finite_decimal(vs_raw) if vs_raw is not None else None

    v_sole = parse_finite_decimal(payload["voting_sole"]) if payload.get("voting_sole") is not None else None
    v_shared = parse_finite_decimal(payload["voting_shared"]) if payload.get("voting_shared") is not None else None
    v_none = parse_finite_decimal(payload["voting_none"]) if payload.get("voting_none") is not None else None

    return Holding13F(
        holding_id=payload["holding_id"],
        filing_id=payload["filing_id"],
        cusip=payload["cusip"],
        issuer_name=payload["issuer_name"],
        raw_quantity=parse_finite_decimal(payload["raw_quantity"]),
        raw_value=parse_finite_decimal(payload["raw_value"]),
        normalized_value=parse_finite_decimal(payload["normalized_value"]),
        normalized_shares=parse_finite_decimal(payload["normalized_shares"]),
        security_class=payload.get("security_class"),
        put_call=PutCall(payload.get("put_call", "NONE")),
        quantity_type=QuantityType(payload.get("quantity_type", "SH")),
        value_currency=payload.get("value_currency", "USD"),
        value_scale=vs,
        mapped_instrument_id=payload.get("mapped_instrument_id"),
        discretion=payload.get("discretion"),
        voting_sole=v_sole,
        voting_shared=v_shared,
        voting_none=v_none,
    )


def _decode_holding_set_13f(payload: dict[str, Any]) -> HoldingSet13F:
    allowed_keys = {
        "filing_id",
        "manager_cik",
        "report_period",
        "holdings",
        "total_eligible_value",
        "is_amended",
    }
    extra = set(payload.keys()) - allowed_keys
    if extra:
        raise ContractValidationError(f"HoldingSet13F payload has extra keys: {sorted(extra)}")

    required_keys = {"filing_id", "manager_cik", "report_period", "holdings"}
    missing = required_keys - set(payload.keys())
    if missing:
        raise ContractValidationError(f"HoldingSet13F payload missing required keys: {sorted(missing)}")

    raw_holdings = payload.get("holdings", [])
    holdings = tuple(_decode_holding_13f(h) for h in raw_holdings)
    is_amended = parse_strict_bool(payload["is_amended"]) if "is_amended" in payload else False
    return HoldingSet13F.create(
        filing_id=payload["filing_id"],
        manager_cik=payload["manager_cik"],
        report_period=payload["report_period"],
        holdings=holdings,
        is_amended=is_amended,
    )


register_decoder("Filing13F", _decode_filing_13f)
register_decoder("Holding13F", _decode_holding_13f)
register_decoder("HoldingSet13F", _decode_holding_set_13f)
