"""Pure personal calculations; no market FX is substituted for acquisition FX."""
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class CostBasisResult:
    native_cost: Decimal | None
    base_cost: Decimal | None
    base_gain: Decimal | None
    status: str
    reason: str | None = None


def actual_cost_basis(*, native_cost: Decimal | None, native_currency: str,
                      base_currency: str, current_base_value: Decimal | None = None,
                      actual_base_cost: Decimal | None = None,
                      acquisition_fx: Decimal | None = None) -> CostBasisResult:
    """acquisition_fx is an explicitly supplied actual base/native execution rate.

    A recorded base cost takes precedence; today's FX is deliberately not an input.
    """
    for value in (native_cost, current_base_value, actual_base_cost, acquisition_fx):
        if value is not None and (not value.is_finite() or value < 0):
            raise ValueError("cost, value and FX must be finite and nonnegative")
    if acquisition_fx == 0:
        raise ValueError("acquisition FX must be positive")
    base = actual_base_cost
    if base is None and native_currency == base_currency:
        base = native_cost
    elif base is None and native_cost is not None and acquisition_fx is not None:
        base = native_cost * acquisition_fx
    if base is None:
        return CostBasisResult(native_cost, None, None, "UNAVAILABLE",
                               "actual acquisition FX or recorded base cost unavailable")
    return CostBasisResult(native_cost, base,
                           None if current_base_value is None else current_base_value - base,
                           "AVAILABLE")


@dataclass(frozen=True, slots=True)
class CashProjection:
    available_cash: Decimal | None
    projected_cash: Decimal | None
    monthly_net_flow: Decimal
    months: int
    status: str
    reason: str | None = None


def project_cash(*, confirmed_cash: Decimal | None, monthly_income: Decimal,
                 monthly_expense: Decimal, months: int,
                 reserved_cash: Decimal = Decimal("0")) -> CashProjection:
    """Expense is a positive outflow; future income never increases today's cash."""
    if isinstance(months, bool) or not isinstance(months, int) or months < 0:
        raise ValueError("months must be a nonnegative integer")
    for value in (confirmed_cash, monthly_income, monthly_expense, reserved_cash):
        if value is not None and (not value.is_finite() or value < 0):
            raise ValueError("cash, income, expense and reserves must be finite and nonnegative")
    net = monthly_income - monthly_expense
    if confirmed_cash is None:
        return CashProjection(None, None, net, months, "UNAVAILABLE", "confirmed cash unavailable")
    return CashProjection(max(Decimal("0"), confirmed_cash - reserved_cash),
                          confirmed_cash + net * months - reserved_cash, net, months, "CONDITIONAL")

@dataclass(frozen=True, slots=True)
class LedgerBasis:
    quantity: Decimal
    base_cost: Decimal | None
    realized_gain: Decimal | None
    status: str
    reason: str | None = None


def reconstruct_base_cost(entries, *, base_currency: str) -> LedgerBasis:
    """Replay posted ASSET entries using ledger's weighted-average policy.

    Required acquisition metadata: actual_base_cost (including fees/taxes) and
    base_currency, or acquisition_fx plus acquisition_fx_base_currency. FX trade
    rates are never implicitly attached to unrelated security purchases.
    """
    quantity = Decimal('0'); cost = Decimal('0'); realized = Decimal('0')
    known = True; realized_known = True; reasons = set()
    for row in entries:
        if row.get('status') != 'POSTED' or row.get('entry_type') != 'ASSET':
            continue
        delta = Decimal(str(row.get('quantity_delta_decimal') or '0'))
        if not delta.is_finite(): raise ValueError('nonfinite quantity')
        tx = row.get('transaction_type')
        md = row.get('metadata') or {}
        if quantity + delta < 0: raise ValueError('negative reconstructed quantity')
        if tx in {'REVERSAL', 'ASSET_ADJUSTMENT'}:
            known = False; realized_known = False; reasons.add('unsupported disposal/rebaseline')
            quantity += delta
            if quantity == 0: cost = Decimal('0'); known = True
            continue
        if tx in {'SPLIT', 'REVERSE_SPLIT'}:
            quantity += delta
            continue
        if delta > 0:
            base = None
            if md.get('base_currency') == base_currency and md.get('actual_base_cost') is not None:
                base = Decimal(str(md['actual_base_cost']))
            elif row.get('currency') == base_currency and row.get('cost_basis_delta_decimal') is not None:
                base = Decimal(str(row['cost_basis_delta_decimal']))
                # Ledger basis excludes acquisition tax; economic P&L includes it.
                base += Decimal(str(row.get('tax_amount_decimal') or '0'))
            elif md.get('acquisition_fx_base_currency') == base_currency and md.get('acquisition_fx') is not None and row.get('cost_basis_delta_decimal') is not None:
                rate = Decimal(str(md['acquisition_fx']))
                if not rate.is_finite() or rate <= 0: raise ValueError('invalid acquisition FX')
                base = (Decimal(str(row['cost_basis_delta_decimal'])) + Decimal(str(row.get('tax_amount_decimal') or '0'))) * rate
            if base is None or row.get('cost_basis_status') == 'UNAVAILABLE':
                known = False; reasons.add('acquisition base cost/FX unavailable')
            elif not base.is_finite() or base < 0:
                raise ValueError('invalid acquisition cost')
            elif known: cost += base
        elif delta < 0:
            if tx != 'SELL':
                known = False; realized_known = False; reasons.add('unsupported disposal/rebaseline')
            elif known:
                removed = cost * (-delta) / quantity
                cost -= removed
                proceeds = None
                if md.get('base_currency') == base_currency and md.get('actual_base_proceeds') is not None:
                    proceeds = Decimal(str(md['actual_base_proceeds']))
                elif row.get('currency') == base_currency and row.get('cash_amount_decimal') is not None:
                    proceeds = Decimal(str(row['cash_amount_decimal']))
                elif md.get('execution_fx_base_currency') == base_currency and md.get('execution_fx') is not None and row.get('cash_amount_decimal') is not None:
                    rate = Decimal(str(md['execution_fx']))
                    if not rate.is_finite() or rate <= 0: raise ValueError('invalid disposal FX')
                    proceeds = Decimal(str(row['cash_amount_decimal'])) * rate
                if proceeds is None:
                    realized_known = False; reasons.add('disposal base proceeds unavailable')
                elif not proceeds.is_finite() or proceeds < 0: raise ValueError('invalid proceeds')
                else: realized += proceeds - removed
            else: realized_known = False
        quantity += delta
        if quantity == 0:
            cost = Decimal('0'); known = True
    return LedgerBasis(quantity, cost if known else None, realized if realized_known else None,
                       'AVAILABLE' if known and realized_known else 'PARTIAL', '; '.join(sorted(reasons)) or None)


def account_buying_power(*, ledger_balance, details, reservation_amount,
                         reservation_coverage, snapshot_aligned):
    """Account/currency-specific broker balance, not a summed cash projection."""
    for value in (ledger_balance, reservation_amount):
        if value is not None and (not isinstance(value, Decimal) or not value.is_finite() or value < 0):
            raise ValueError('ledger cash and reservations require finite nonnegative decimals')
    def decimal(key):
        value = details.get(key)
        if value is None: return None
        if isinstance(value, (bool, float)): raise ValueError('exact cash decimal required')
        result = Decimal(str(value))
        if not result.is_finite() or result < 0: raise ValueError('invalid cash amount')
        return result
    result = {key: decimal(key) for key in ('settled_cash', 'buying_power', 'withdrawable', 'collateral')}
    result.update(ledger_balance=ledger_balance, reserved_cash=reservation_amount,
                  available_for_purchase=None, status='UNAVAILABLE', reason=None)
    deposit = decimal('deposit')
    if not snapshot_aligned or deposit != ledger_balance:
        result['reason'] = 'snapshot/posted ledger reconciliation unavailable or conflicting'
    elif not reservation_coverage or reservation_amount is None:
        result['reason'] = 'account-specific reservation coverage unavailable'
    elif result['settled_cash'] is None or result['buying_power'] is None:
        result['reason'] = 'settled cash or broker buying power unavailable'
    elif not isinstance(details.get('reservations_in_buying_power'), bool):
        result['reason'] = 'broker buying-power reservation inclusion unknown'
    elif result['settled_cash'] > ledger_balance:
        result['reason'] = 'settled cash exceeds reconciled ledger deposit'
    else:
        free_settled = max(Decimal('0'), result['settled_cash'] - reservation_amount)
        free_power = result['buying_power'] if details['reservations_in_buying_power'] else max(Decimal('0'), result['buying_power'] - reservation_amount)
        result.update(available_for_purchase=min(free_settled, free_power), status='AVAILABLE', reason=None)
    return result
