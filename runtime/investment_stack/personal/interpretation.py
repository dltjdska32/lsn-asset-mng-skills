"""Small non-mutating natural-language boundary for typed intent fixtures."""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal

from investment_stack.personal.intent import TransactionIntent, TransactionType


QUANTITY = re.compile(r"(?P<quantity>\d+(?:\.\d+)?)\s*(?:주|shares?|개)", re.IGNORECASE)
PRICE = re.compile(
    r"(?:@|주당\s*)?(?P<price>\d+(?:\.\d+)?)\s*(?:엔|원|JPY|KRW|USD)",
    re.IGNORECASE,
)


def parse_transaction_request(
    raw_request: str,
    *,
    account_id: str | None = None,
    instrument_id: str | None = None,
    occurred_at: datetime | None = None,
    timezone_name: str | None = None,
    currency: str | None = None,
) -> TransactionIntent:
    """Parse obvious structure without resolving entities or touching storage."""

    text = raw_request.strip()
    lowered = text.casefold()
    in_kind = any(token in lowered for token in ("옮겼", "moved", "transfer shares"))
    if in_kind and any(
        token in lowered for token in ("주식", "fanuc", "btc", "gold", "금")
    ):
        return TransactionIntent(
            TransactionType.TRANSFER,
            account_id=account_id,
            instrument_id=instrument_id,
            occurred_at=occurred_at,
            timezone=timezone_name,
            in_kind_transfer=True,
            notes=text,
        )
    if any(token in lowered for token in ("샀", "buy", "bought", "추가매수")):
        tx_type = TransactionType.BUY
    elif any(token in lowered for token in ("팔", "sell", "sold")):
        tx_type = TransactionType.SELL
    elif any(token in lowered for token in ("입금", "deposit")):
        tx_type = TransactionType.DEPOSIT
    elif any(token in lowered for token in ("출금", "withdraw")):
        tx_type = TransactionType.WITHDRAWAL
    else:
        raise ValueError("request does not contain an unambiguous supported transaction verb")
    quantity_match = QUANTITY.search(text)
    price_match = PRICE.search(text)
    quantity = Decimal(quantity_match.group("quantity")) if quantity_match else None
    price = Decimal(price_match.group("price")) if price_match else None
    return TransactionIntent(
        tx_type,
        account_id=account_id,
        instrument_id=instrument_id,
        quantity=quantity,
        unit_price=price,
        currency=currency,
        occurred_at=occurred_at,
        timezone=timezone_name,
        quantity_only=quantity is not None and price is None,
        notes=text,
    )
