"""Canonical Decimal handling for SQLite TEXT columns."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import TypeAlias

from investment_stack.personal.errors import IntentValidationError


DecimalInput: TypeAlias = Decimal | int | str
ZERO = Decimal("0")


def exact_decimal(value: DecimalInput | None, *, field: str) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool) or isinstance(value, float):
        raise IntentValidationError(f"{field} must not use binary float")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise IntentValidationError(f"{field} is not a valid decimal") from exc
    if not result.is_finite():
        raise IntentValidationError(f"{field} must be finite")
    return result


def encode_decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if not value.is_finite():
        raise ValueError("cannot encode a non-finite decimal")
    normalized = value.normalize()
    if normalized == ZERO:
        return "0"
    return format(normalized, "f")


def decode_decimal(value: object | None) -> Decimal | None:
    if value is None:
        return None
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("stored decimal is not finite")
    return result
