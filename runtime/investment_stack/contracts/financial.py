"""Financial fact models, period bundles, and standardized accounting definitions."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any, Iterable

from investment_stack.contracts.codec import (
    parse_finite_decimal,
    parse_iso_date,
    register_decoder,
)
from investment_stack.contracts.context import PublicAvailability
from investment_stack.contracts.errors import (
    ContractValidationError,
    DecimalValidationError,
)
from investment_stack.contracts.slots import DimensionKind


class ScaleStatus(StrEnum):
    ABSENT = "ABSENT"
    VALID = "VALID"
    INVALID = "INVALID"


class PeriodType(StrEnum):
    INSTANT = "INSTANT"
    DURATION = "DURATION"


class ReportingFrequency(StrEnum):
    ANNUAL = "ANNUAL"
    QUARTER = "QUARTER"
    YTD = "YTD"
    TTM = "TTM"


class AccountingStandard(StrEnum):
    US_GAAP = "US-GAAP"
    IFRS = "IFRS"
    LOCAL_GAAP = "LOCAL-GAAP"
    OTHER = "OTHER"


class ConsolidationKind(StrEnum):
    CONSOLIDATED = "CONSOLIDATED"
    UNCONSOLIDATED = "UNCONSOLIDATED"


class AdjustmentBasis(StrEnum):
    REPORTED = "REPORTED"
    ADJUSTED = "ADJUSTED"


class ShareBasis(StrEnum):
    END = "END"
    BASIC_WEIGHTED = "BASIC_WEIGHTED"
    DILUTED_WEIGHTED = "DILUTED_WEIGHTED"


@dataclass(frozen=True, slots=True)
class FinancialFact:
    """A single normalized, lineage-tracked financial fact extracted from filings."""

    fact_id: str
    evidence_id: str
    instrument_id: str
    taxonomy: str
    original_tag: str
    canonical_metric: str
    raw_value: Decimal
    raw_unit: str
    explicit_scale: ScaleStatus
    scale_multiplier: Decimal
    normalized_value: Decimal
    dimension: DimensionKind | str
    currency: str | None
    period_type: PeriodType | str
    period_start: str | None
    period_end: str
    duration_days: int | None
    fiscal_year: int | None
    fiscal_period: str | None
    reporting_frequency: ReportingFrequency | str
    consolidation: ConsolidationKind | str
    accounting_standard: AccountingStandard | str
    adjustment_basis: AdjustmentBasis | str
    public_availability: PublicAvailability
    share_basis: ShareBasis | str | None = None
    form: str | None = None
    accession: str | None = None
    filed_date: str | None = None
    accepted_at: str | None = None
    restatement_of: str | None = None
    source_locator: str | None = None

    def __post_init__(self) -> None:
        if not self.fact_id or not self.evidence_id or not self.instrument_id:
            raise ContractValidationError("fact_id, evidence_id, instrument_id must be non-empty strings")
        if not self.period_end:
            raise ContractValidationError("period_end must be specified")

        raw_finite = parse_finite_decimal(self.raw_value)
        mult_finite = parse_finite_decimal(self.scale_multiplier)
        norm_finite = parse_finite_decimal(self.normalized_value)
        if mult_finite <= 0:
            raise DecimalValidationError(f"scale_multiplier must be strictly positive, got: {mult_finite}")
        if raw_finite != self.raw_value:
            object.__setattr__(self, "raw_value", raw_finite)
        if mult_finite != self.scale_multiplier:
            object.__setattr__(self, "scale_multiplier", mult_finite)
        if norm_finite != self.normalized_value:
            object.__setattr__(self, "normalized_value", norm_finite)

        if self.period_start is not None and self.period_end is not None:
            if self.period_start > self.period_end:
                raise ContractValidationError(
                    f"FinancialFact {self.fact_id}: period_start ({self.period_start}) cannot exceed period_end ({self.period_end})"
                )


@dataclass(frozen=True, slots=True)
class FinancialSet:
    """A coherent, validated collection of FinancialFacts for an instrument."""

    set_id: str
    instrument_id: str
    reporting_currency: str
    facts: tuple[FinancialFact, ...]
    fiscal_calendar_id: str | None = None
    covered_metrics: tuple[str, ...] = ()

    @classmethod
    def create(
        cls,
        set_id: str,
        instrument_id: str,
        reporting_currency: str,
        facts: Iterable[FinancialFact],
        *,
        fiscal_calendar_id: str | None = None,
    ) -> FinancialSet:
        fact_list = list(facts)
        for f in fact_list:
            if f.instrument_id != instrument_id:
                raise ContractValidationError(
                    f"FinancialFact {f.fact_id} instrument_id ({f.instrument_id}) does not match FinancialSet instrument ({instrument_id})"
                )
        sorted_facts = tuple(
            sorted(
                fact_list,
                key=lambda f: (f.canonical_metric, f.period_end, f.accession or "", f.fact_id),
            )
        )
        def _is_coherent_fact(fact: FinancialFact) -> bool:
            if fact.explicit_scale == ScaleStatus.INVALID:
                return False
            if fact.currency and fact.currency != reporting_currency:
                return False
            try:
                parse_iso_date(fact.period_end)
                if fact.period_start:
                    parse_iso_date(fact.period_start)
            except Exception:
                return False
            if fact.duration_days is not None and fact.duration_days <= 0:
                return False
            if fact.explicit_scale == ScaleStatus.VALID:
                if fact.raw_value * fact.scale_multiplier != fact.normalized_value:
                    return False
            return True

        covered = tuple(
            sorted({f.canonical_metric for f in sorted_facts if _is_coherent_fact(f)})
        )
        return cls(
            set_id=set_id,
            instrument_id=instrument_id,
            reporting_currency=reporting_currency,
            facts=sorted_facts,
            fiscal_calendar_id=fiscal_calendar_id,
            covered_metrics=covered,
        )

    def find_facts(self, metric: str) -> tuple[FinancialFact, ...]:
        return tuple(f for f in self.facts if f.canonical_metric == metric)


# Decoders
def _decode_financial_fact(payload: dict[str, Any]) -> FinancialFact:
    allowed_keys = {
        "fact_id",
        "evidence_id",
        "instrument_id",
        "taxonomy",
        "original_tag",
        "canonical_metric",
        "raw_value",
        "raw_unit",
        "explicit_scale",
        "scale_multiplier",
        "normalized_value",
        "dimension",
        "currency",
        "period_type",
        "period_start",
        "period_end",
        "duration_days",
        "fiscal_year",
        "fiscal_period",
        "reporting_frequency",
        "consolidation",
        "accounting_standard",
        "adjustment_basis",
        "public_availability",
        "share_basis",
        "form",
        "accession",
        "filed_date",
        "accepted_at",
        "restatement_of",
        "source_locator",
    }
    extra = set(payload.keys()) - allowed_keys
    if extra:
        raise ContractValidationError(f"FinancialFact payload has extra keys: {sorted(extra)}")

    required_keys = {
        "fact_id",
        "evidence_id",
        "instrument_id",
        "taxonomy",
        "original_tag",
        "canonical_metric",
        "raw_value",
        "raw_unit",
        "explicit_scale",
        "scale_multiplier",
        "normalized_value",
        "dimension",
        "period_type",
        "period_end",
        "reporting_frequency",
        "consolidation",
        "accounting_standard",
        "adjustment_basis",
        "public_availability",
    }
    missing = required_keys - set(payload.keys())
    if missing:
        raise ContractValidationError(f"FinancialFact payload missing required keys: {sorted(missing)}")

    from investment_stack.contracts.codec import decode_contract

    pub = decode_contract(payload["public_availability"], expected_kind="PublicAvailability")
    dur = int(payload["duration_days"]) if payload.get("duration_days") is not None else None
    fy = int(payload["fiscal_year"]) if payload.get("fiscal_year") is not None else None

    return FinancialFact(
        fact_id=payload["fact_id"],
        evidence_id=payload["evidence_id"],
        instrument_id=payload["instrument_id"],
        taxonomy=payload["taxonomy"],
        original_tag=payload["original_tag"],
        canonical_metric=payload["canonical_metric"],
        raw_value=parse_finite_decimal(payload["raw_value"]),
        raw_unit=payload["raw_unit"],
        explicit_scale=ScaleStatus(payload["explicit_scale"]),
        scale_multiplier=parse_finite_decimal(payload["scale_multiplier"]),
        normalized_value=parse_finite_decimal(payload["normalized_value"]),
        dimension=DimensionKind(payload["dimension"]),
        currency=payload.get("currency"),
        period_type=PeriodType(payload["period_type"]),
        period_start=payload.get("period_start"),
        period_end=payload["period_end"],
        duration_days=dur,
        fiscal_year=fy,
        fiscal_period=payload.get("fiscal_period"),
        reporting_frequency=ReportingFrequency(payload["reporting_frequency"]),
        consolidation=ConsolidationKind(payload["consolidation"]),
        accounting_standard=AccountingStandard(payload["accounting_standard"]),
        adjustment_basis=AdjustmentBasis(payload["adjustment_basis"]),
        public_availability=pub,
        share_basis=ShareBasis(payload["share_basis"]) if payload.get("share_basis") else None,
        form=payload.get("form"),
        accession=payload.get("accession"),
        filed_date=payload.get("filed_date"),
        accepted_at=payload.get("accepted_at"),
        restatement_of=payload.get("restatement_of"),
        source_locator=payload.get("source_locator"),
    )


def _decode_financial_set(payload: dict[str, Any]) -> FinancialSet:
    allowed_keys = {
        "set_id",
        "instrument_id",
        "reporting_currency",
        "facts",
        "fiscal_calendar_id",
        "covered_metrics",
    }
    extra = set(payload.keys()) - allowed_keys
    if extra:
        raise ContractValidationError(f"FinancialSet payload has extra keys: {sorted(extra)}")

    required_keys = {"set_id", "instrument_id", "reporting_currency", "facts"}
    missing = required_keys - set(payload.keys())
    if missing:
        raise ContractValidationError(f"FinancialSet payload missing required keys: {sorted(missing)}")

    raw_facts = payload.get("facts", [])
    facts = tuple(_decode_financial_fact(f) for f in raw_facts)
    return FinancialSet.create(
        set_id=payload["set_id"],
        instrument_id=payload["instrument_id"],
        reporting_currency=payload["reporting_currency"],
        facts=facts,
        fiscal_calendar_id=payload.get("fiscal_calendar_id"),
    )


register_decoder("FinancialFact", _decode_financial_fact)
register_decoder("FinancialSet", _decode_financial_set)
