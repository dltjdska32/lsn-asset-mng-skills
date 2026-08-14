"""Typed transaction intent and deterministic confirmation policy."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from investment_stack.personal.decimal import DecimalInput, encode_decimal, exact_decimal


class TransactionType(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    TRANSFER = "TRANSFER"
    DIVIDEND = "DIVIDEND"
    INTEREST = "INTEREST"
    FEE = "FEE"
    FX_BUY = "FX_BUY"
    FX_SELL = "FX_SELL"
    LOAN_DRAW = "LOAN_DRAW"
    LOAN_PAYMENT = "LOAN_PAYMENT"
    ASSET_ADJUSTMENT = "ASSET_ADJUSTMENT"
    REVERSAL = "REVERSAL"
    OPENING_BALANCE = "OPENING_BALANCE"
    INITIAL_POSITION = "INITIAL_POSITION"
    SPLIT = "SPLIT"
    REVERSE_SPLIT = "REVERSE_SPLIT"
    TICKER_CHANGE = "TICKER_CHANGE"


class IntentState(StrEnum):
    PARSED = "PARSED"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"
    READY_TO_POST = "READY_TO_POST"
    POSTED = "POSTED"
    REJECTED = "REJECTED"
    UNSUPPORTED = "UNSUPPORTED"


class ConfirmationState(StrEnum):
    UNCONFIRMED = "UNCONFIRMED"
    CONFIRMED = "CONFIRMED"


class CostBasisStatus(StrEnum):
    USER_PROVIDED = "USER_PROVIDED"
    WEIGHTED_AVERAGE = "WEIGHTED_AVERAGE"
    UNAVAILABLE = "UNAVAILABLE"


class OpeningBalanceKind(StrEnum):
    CASH = "CASH"
    LIABILITY = "LIABILITY"


DECIMAL_FIELDS = (
    "quantity",
    "unit_price",
    "gross_amount",
    "fee_amount",
    "tax_amount",
    "cash_amount",
    "source_amount",
    "target_amount",
    "fx_rate",
    "principal_amount",
    "interest_amount",
    "total_cost",
    "average_unit_cost",
    "split_numerator",
    "split_denominator",
)


@dataclass(frozen=True, slots=True)
class TransactionIntent:
    transaction_type: TransactionType
    intent_id: str = field(default_factory=lambda: uuid4().hex)
    account_id: str | None = None
    instrument_id: str | None = None
    source_account_id: str | None = None
    destination_account_id: str | None = None
    liability_id: str | None = None
    quantity: DecimalInput | None = None
    unit_price: DecimalInput | None = None
    gross_amount: DecimalInput | None = None
    fee_amount: DecimalInput | None = None
    tax_amount: DecimalInput | None = None
    cash_amount: DecimalInput | None = None
    source_amount: DecimalInput | None = None
    target_amount: DecimalInput | None = None
    fx_rate: DecimalInput | None = None
    principal_amount: DecimalInput | None = None
    interest_amount: DecimalInput | None = None
    total_cost: DecimalInput | None = None
    average_unit_cost: DecimalInput | None = None
    split_numerator: DecimalInput | None = None
    split_denominator: DecimalInput | None = None
    currency: str | None = None
    source_currency: str | None = None
    target_currency: str | None = None
    unit: str | None = None
    occurred_at: datetime | None = None
    timezone: str | None = None
    external_reference: str | None = None
    idempotency_key: str | None = None
    reversal_of_transaction_id: str | None = None
    replacement_for_transaction_id: str | None = None
    notes: str | None = None
    confirmation_state: ConfirmationState = ConfirmationState.UNCONFIRMED
    cost_basis_status: CostBasisStatus | None = None
    opening_balance_kind: OpeningBalanceKind | None = None
    new_ticker: str | None = None
    quantity_only: bool = False
    in_kind_transfer: bool = False
    account_ambiguous: bool = False
    instrument_ambiguous: bool = False
    custody_ambiguous: bool = False
    net_worth_ambiguous: bool = False
    high_impact: bool = False
    ambiguity_metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.transaction_type, TransactionType):
            object.__setattr__(self, "transaction_type", TransactionType(self.transaction_type))
        if not isinstance(self.confirmation_state, ConfirmationState):
            object.__setattr__(self, "confirmation_state", ConfirmationState(self.confirmation_state))
        if self.cost_basis_status is not None and not isinstance(
            self.cost_basis_status, CostBasisStatus
        ):
            object.__setattr__(self, "cost_basis_status", CostBasisStatus(self.cost_basis_status))
        if self.opening_balance_kind is not None and not isinstance(
            self.opening_balance_kind, OpeningBalanceKind
        ):
            object.__setattr__(
                self, "opening_balance_kind", OpeningBalanceKind(self.opening_balance_kind)
            )
        for name in DECIMAL_FIELDS:
            object.__setattr__(self, name, exact_decimal(getattr(self, name), field=name))
        object.__setattr__(self, "ambiguity_metadata", MappingProxyType(dict(self.ambiguity_metadata)))


@dataclass(frozen=True, slots=True)
class IntentValidationContext:
    account_timezone: str | None = None
    user_default_timezone: str | None = None
    account_exists: bool = True
    instrument_exists: bool = True
    duplicate_suspected: bool = False
    high_impact: bool = False


@dataclass(frozen=True, slots=True)
class IntentDecision:
    state: IntentState
    intent: TransactionIntent
    missing_fields: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()


ALWAYS_CONFIRM = frozenset(
    {
        TransactionType.ASSET_ADJUSTMENT,
        TransactionType.OPENING_BALANCE,
        TransactionType.INITIAL_POSITION,
    }
)


def _required_fields(intent: TransactionIntent) -> tuple[str, ...]:
    tx = intent.transaction_type
    common: tuple[str, ...] = ()
    if tx in {TransactionType.BUY, TransactionType.SELL}:
        common = ("account_id", "instrument_id", "quantity", "unit_price", "currency")
    elif tx in {TransactionType.DEPOSIT, TransactionType.WITHDRAWAL, TransactionType.DIVIDEND, TransactionType.FEE}:
        common = ("account_id", "cash_amount", "currency")
    elif tx is TransactionType.TRANSFER:
        common = ("source_account_id", "destination_account_id", "cash_amount", "currency")
    elif tx is TransactionType.INTEREST:
        common = ("account_id", "cash_amount", "currency")
        if intent.ambiguity_metadata.get("interest_direction") not in {"INCOME", "EXPENSE"}:
            common += ("interest_direction",)
    elif tx in {TransactionType.FX_BUY, TransactionType.FX_SELL}:
        common = (
            "account_id",
            "source_amount",
            "target_amount",
            "source_currency",
            "target_currency",
            "fx_rate",
        )
    elif tx is TransactionType.LOAN_DRAW:
        common = ("account_id", "liability_id", "principal_amount", "currency")
    elif tx is TransactionType.LOAN_PAYMENT:
        common = (
            "account_id",
            "liability_id",
            "principal_amount",
            "interest_amount",
            "currency",
        )
    elif tx is TransactionType.ASSET_ADJUSTMENT:
        common = ("account_id", "instrument_id", "quantity", "unit")
    elif tx is TransactionType.REVERSAL:
        common = ("reversal_of_transaction_id",)
    elif tx is TransactionType.OPENING_BALANCE:
        common = ("account_id", "cash_amount", "currency", "opening_balance_kind")
        if intent.opening_balance_kind is OpeningBalanceKind.LIABILITY:
            common += ("liability_id",)
    elif tx is TransactionType.INITIAL_POSITION:
        common = ("account_id", "instrument_id", "quantity", "unit", "cost_basis_status")
        if intent.cost_basis_status is CostBasisStatus.USER_PROVIDED:
            if intent.total_cost is None and intent.average_unit_cost is None:
                common += ("total_cost_or_average_unit_cost",)
    elif tx in {TransactionType.SPLIT, TransactionType.REVERSE_SPLIT}:
        common = (
            "account_id",
            "instrument_id",
            "split_numerator",
            "split_denominator",
        )
    elif tx is TransactionType.TICKER_CHANGE:
        common = ("instrument_id", "new_ticker")
    return common + ("occurred_at", "timezone")


def _valid_timezone(name: str) -> bool:
    if name == "UTC":
        return True
    try:
        ZoneInfo(name)
        return True
    except (ZoneInfoNotFoundError, ValueError):
        # Windows Python may not have the optional IANA tzdata package. Keep the
        # policy deterministic and syntactically strict without consulting a network.
        return bool(
            re.fullmatch(
                r"(?:Africa|America|Antarctica|Arctic|Asia|Atlantic|Australia|Europe|Indian|Pacific)/[A-Za-z0-9_+.-]+(?:/[A-Za-z0-9_+.-]+)?",
                name,
            )
        )


def resolve_timezone(
    intent: TransactionIntent, context: IntentValidationContext
) -> TransactionIntent:
    timezone = intent.timezone or context.account_timezone or context.user_default_timezone
    return intent if timezone == intent.timezone else replace(intent, timezone=timezone)


def evaluate_intent(
    intent: TransactionIntent,
    *,
    context: IntentValidationContext | None = None,
) -> IntentDecision:
    context = context or IntentValidationContext()
    normalized = resolve_timezone(intent, context)
    if normalized.in_kind_transfer:
        return IntentDecision(
            IntentState.UNSUPPORTED,
            normalized,
            reasons=("in-kind asset transfer is outside the MVP",),
        )

    missing = tuple(
        name
        for name in _required_fields(normalized)
        if name in {"interest_direction", "total_cost_or_average_unit_cost"}
        or getattr(normalized, name, None) is None
    )
    reasons: list[str] = []
    if normalized.timezone is not None and not _valid_timezone(normalized.timezone):
        missing = tuple(dict.fromkeys((*missing, "timezone")))
        reasons.append("timezone is invalid")
    if normalized.quantity_only:
        reasons.append("quantity-only input cannot be posted")
    if normalized.account_ambiguous:
        reasons.append("account ambiguity must be resolved")
    if not context.account_exists:
        reasons.append("account does not exist")
    if normalized.instrument_ambiguous:
        reasons.append("instrument ambiguity must be resolved")
    if not context.instrument_exists:
        reasons.append("instrument does not exist")
    if normalized.custody_ambiguous:
        reasons.append("asset custody is ambiguous")
    if normalized.net_worth_ambiguous:
        reasons.append("net worth impact is ambiguous")
    if normalized.high_impact or context.high_impact:
        reasons.append("high-impact transaction requires confirmation")
    if context.duplicate_suspected and not normalized.ambiguity_metadata.get(
        "duplicate_confirmed", False
    ):
        reasons.append("a duplicate transaction is suspected")

    positive = (
        "unit_price",
        "cash_amount",
        "source_amount",
        "target_amount",
        "principal_amount",
        "split_numerator",
        "split_denominator",
    )
    if normalized.quantity is not None:
        if normalized.transaction_type is TransactionType.ASSET_ADJUSTMENT:
            if normalized.quantity == 0:
                reasons.append("quantity must not be zero")
        elif normalized.quantity <= 0:
            reasons.append("quantity must be greater than zero")
    for name in positive:
        value = getattr(normalized, name)
        if value is not None and value <= 0:
            reasons.append(f"{name} must be greater than zero")
    for name in ("fee_amount", "tax_amount", "interest_amount", "total_cost", "average_unit_cost"):
        value = getattr(normalized, name)
        if value is not None and value < 0:
            reasons.append(f"{name} must not be negative")
    if normalized.transaction_type in {TransactionType.SPLIT, TransactionType.REVERSE_SPLIT}:
        if normalized.split_numerator == normalized.split_denominator:
            reasons.append("split ratio must change quantity")
        if normalized.transaction_type is TransactionType.SPLIT and (
            normalized.split_numerator is not None
            and normalized.split_denominator is not None
            and normalized.split_numerator <= normalized.split_denominator
        ):
            reasons.append("SPLIT ratio must increase quantity")
        if normalized.transaction_type is TransactionType.REVERSE_SPLIT and (
            normalized.split_numerator is not None
            and normalized.split_denominator is not None
            and normalized.split_numerator >= normalized.split_denominator
        ):
            reasons.append("REVERSE_SPLIT ratio must decrease quantity")

    confirmation_needed = bool(missing or reasons) or normalized.transaction_type in ALWAYS_CONFIRM
    if confirmation_needed and normalized.confirmation_state is not ConfirmationState.CONFIRMED:
        return IntentDecision(IntentState.NEEDS_CONFIRMATION, normalized, missing, tuple(reasons))
    if missing or any(
        token in reason
        for reason in reasons
        for token in ("must", "invalid", "does not exist")
    ):
        return IntentDecision(IntentState.REJECTED, normalized, missing, tuple(reasons))
    return IntentDecision(IntentState.READY_TO_POST, normalized, (), tuple(reasons))


def transaction_fingerprint(intent: TransactionIntent) -> str:
    material = {
        "type": intent.transaction_type.value,
        "account": intent.account_id,
        "source_account": intent.source_account_id,
        "destination_account": intent.destination_account_id,
        "instrument": intent.instrument_id,
        "quantity": encode_decimal(intent.quantity),
        "unit_price": encode_decimal(intent.unit_price),
        "gross_amount": encode_decimal(intent.gross_amount),
        "fee_amount": encode_decimal(intent.fee_amount),
        "currency": intent.currency,
        "cash_amount": encode_decimal(intent.cash_amount),
        "source_amount": encode_decimal(intent.source_amount),
        "target_amount": encode_decimal(intent.target_amount),
        "occurred_at": intent.occurred_at.isoformat() if intent.occurred_at else None,
        "timezone": intent.timezone,
        "external_reference": intent.external_reference,
    }
    if intent.external_reference:
        material = {
            "type": intent.transaction_type.value,
            "external_reference": intent.external_reference,
        }
    payload = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
