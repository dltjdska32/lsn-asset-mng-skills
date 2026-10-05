"""Read-only pinned ledger reconstruction persisted only in run.db."""
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime, timedelta
import json
from uuid import uuid4
from zoneinfo import ZoneInfo
from types import SimpleNamespace
from investment_stack.storage.sqlite import sqlite_readonly_connection
from investment_stack.calculations.personal import reconstruct_base_cost, account_buying_power
from investment_stack.reporting.models import ReportSectionInput, Availability


@dataclass(frozen=True, slots=True)
class PersonalOutputs:
    sections: tuple
    evidence_refs: tuple
    calculation_refs: tuple
    missing_inputs: tuple


def render_personal_outputs(run, ledger, projection, quotes, fx, snapshot,
                            evaluation_currency, analysis_as_of):
    """Return sections + refs; caller merges into SelectedAssetResearchResult.

    snapshot must declare state_version matching projection, data_as_of within
    the prior 24 hours, and cash_details keyed
    account_id_currency. details fields: deposit, settled_cash, buying_power,
    withdrawable, collateral, reservations_in_buying_power (bool).
    Existing deposit-only snapshots intentionally cannot prove spendable cash.
    """
    context = run.fetch_phase6_context()
    pinned = context['pinned_personal_state']
    run_evidence = {r['evidence_id']: r for r in context.get('evidence', ())}
    if int(pinned['state_version']) != projection.state_version:
        raise ValueError('personal outputs projection is not pinned')
    cutoff = datetime.fromisoformat(analysis_as_of.replace('Z', '+00:00'))
    with sqlite_readonly_connection(ledger.manager.database_path) as connection:
        rows = [dict(row) for row in connection.execute(
            'SELECT e.*, t.status, t.transaction_type, t.occurred_at, t.occurred_timezone AS timezone, '
            't.cash_amount_decimal, t.tax_amount_decimal, t.reversal_of, t.metadata_json AS trade_metadata '
            'FROM transaction_entries e JOIN transactions t USING(transaction_id) '
            "WHERE t.status='POSTED' AND e.state_version<=? ORDER BY e.state_version,t.operation_sequence,e.entry_sequence",
            (projection.state_version,))]
    def in_time(row):
        if row['occurred_at'] is None: return True
        at = datetime.fromisoformat(row['occurred_at'].replace('Z','+00:00'))
        if at.tzinfo is None:
            if not row['timezone']: return False
            at = at.replace(tzinfo=ZoneInfo(row['timezone']))
        return at <= cutoff
    rows = [r for r in rows if in_time(r)]
    source_entry_ids = [r['entry_id'] for r in rows]
    reversed_transactions = {r['reversal_of'] for r in rows if r['transaction_type']=='REVERSAL' and r['reversal_of']}
    reversal_transactions = {r['transaction_id'] for r in rows if r['transaction_type']=='REVERSAL' and r['reversal_of']}
    # Canonical reversals cancel their original transaction at this pinned state.
    # Both immutable entries remain referenced in evidence; replay the effective
    # trades instead of mistaking corrective reversal legs for new disposals.
    rows = [r for r in rows if r['transaction_id'] not in reversed_transactions | reversal_transactions]
    cash_entries = {}
    for row in rows:
        if row['entry_type'] == 'CASH':
            key = (row['transaction_id'], row['account_id'], row['currency'])
            cash_entries[key] = cash_entries.get(key, Decimal('0')) + Decimal(str(row['amount_delta_decimal'] or '0'))
    for row in rows:
        row['metadata'] = {**json.loads(row.get('metadata_json') or '{}'), **json.loads(row.get('trade_metadata') or '{}')}
        if row['transaction_type'] == 'SELL' and row['entry_type'] == 'ASSET' and row['cash_amount_decimal'] is None:
            # The posted CASH leg records net sale proceeds even when the intent
            # omitted cash_amount. Never reconstruct proceeds from a gross quote.
            row['cash_amount_decimal'] = cash_entries.get((row['transaction_id'], row['account_id'], row['currency']))
    eid = 'personal-ledger:' + uuid4().hex
    run.add_evidence(evidence_id=eid, evidence_type='posted_ledger_projection',
                     metadata={'state_version':projection.state_version,'analysis_as_of':analysis_as_of,
                               'entry_ids':source_entry_ids, 'reversed_transaction_ids':sorted(reversed_transactions),
                               'snapshot_id':pinned['portfolio_snapshot_id']})
    lines=[]; cash_lines=[]; missing=[]; refs=[eid]; calcs=[]; pnl_calcs=[]; cash_calcs=[]
    def persist(name, key, result, market_refs=()):
        cid='personal:'+name+':'+uuid4().hex
        run.add_calculation(calculation_id=cid,calculation_name=name,
                            formula='posted ledger weighted average including recorded transaction costs' if name=='PERSONAL_ACTUAL_PNL' else 'min(unreserved settled cash, unreserved broker buying power)',
                            inputs={'evidence_ids':[eid,*market_refs], 'state_version':projection.state_version,
                                    'subject':key,'policy':'WEIGHTED_AVERAGE','analysis_as_of':analysis_as_of},result=result)
        calcs.append(cid)
        return cid
    positions = list(projection.positions)
    held_keys = {(p.account_id, p.instrument_id) for p in positions}
    historical_keys = {(r['account_id'], r['instrument_id']) for r in rows if r['entry_type']=='ASSET'}
    for account_id, instrument_id in sorted(historical_keys-held_keys):
        positions.append(SimpleNamespace(account_id=account_id, instrument_id=instrument_id, quantity=Decimal('0')))
    for position in positions:
        group=[r for r in rows if r['account_id']==position.account_id and r['instrument_id']==position.instrument_id and r['entry_type']=='ASSET']
        basis=reconstruct_base_cost(group,base_currency=evaluation_currency)
        value=Decimal('0') if position.quantity==0 else None
        market_refs=[]; value_reason=None if position.quantity==0 else 'eligible quote/FX unavailable'
        quote=quotes.get(position.instrument_id)
        def eligible(selected, subject, metric):
            if selected is None or selected.observation is None or selected.freshness is None: return False
            try:
                observed=datetime.fromisoformat(selected.observation.observed_at.replace('Z','+00:00'))
                retrieved=datetime.fromisoformat(selected.observation.retrieved_at.replace('Z','+00:00'))
                row = run_evidence.get(selected.evidence_id, {})
                obs = selected.observation
                value = Decimal(str(obs.value))
                # An object carrying an existing ID must match the persisted
                # selected fact, not merely point to any evidence in this run.
                valid = (selected.freshness.status.value in {'FRESH','LAST_VALID_CLOSE'}
                    and observed <= cutoff and retrieved >= observed
                    and row.get('selection_state') == 'SELECTED'
                    and row.get('instrument_id') == subject == obs.instrument_id
                    and row.get('metric') == metric == obs.metric
                    and row.get('currency') == obs.currency
                    and row.get('observed_at') == obs.observed_at
                    and row.get('retrieved_at') == obs.retrieved_at
                    and row.get('freshness_status') == selected.freshness.status.value
                    and Decimal(str(json.loads(row['value_text']))) == value
                    and value.is_finite() and value > 0)
                published = row.get('published_at')
                if published:
                    valid = valid and datetime.fromisoformat(published.replace('Z','+00:00')) <= cutoff
                return valid
            except (ValueError, TypeError, AttributeError, KeyError, ArithmeticError): return False
        if eligible(quote, position.instrument_id, 'current_price'):
            obs=quote.observation
            rate=Decimal('1') if obs.currency==evaluation_currency else None
            exchange=fx.get(str(obs.currency)+'/'+evaluation_currency)
            if rate is None and eligible(exchange, str(obs.currency)+'/'+evaluation_currency, 'fx_rate') and exchange.freshness.status.value=='FRESH':
                rate=Decimal(str(exchange.observation.value)); market_refs.append(exchange.evidence_id)
            if rate is not None and rate>0:
                value=position.quantity*Decimal(str(obs.value))*rate; market_refs.append(quote.evidence_id); value_reason=None
        aligned=basis.quantity==position.quantity
        base_cost=basis.base_cost if aligned else None
        pnl=None if value is None or base_cost is None else value-base_cost
        result={'account_id':position.account_id,'instrument_id':position.instrument_id,'currency':evaluation_currency,
                'quantity':position.quantity,'base_cost':base_cost,'current_value':value,'unrealized_gain':pnl,
                'realized_gain':basis.realized_gain if aligned else None,
                'status':'AVAILABLE' if aligned and pnl is not None and basis.realized_gain is not None else 'PARTIAL',
                'reason':basis.reason or (None if aligned else 'ledger/as-of projection quantity mismatch') or value_reason}
        pnl_calcs.append(persist('PERSONAL_ACTUAL_PNL',position.account_id+':'+position.instrument_id,result,market_refs))
        refs.extend(market_refs)
        lines.append(json.dumps(result,default=str,ensure_ascii=False))
        if result['status']!='AVAILABLE': missing.append(position.account_id+':'+position.instrument_id+':actual_pnl')
    covered,reservations=ledger.list_cash_reservations(projection.state_version)
    amounts={}
    for reservation in reservations:
        amounts[reservation.currency]=amounts.get(reservation.currency,Decimal('0'))+reservation.amount
    aligned=snapshot.get('state_version')==projection.state_version
    try:
        cash_as_of=datetime.fromisoformat(str(snapshot['data_as_of']).replace('Z','+00:00'))
        aligned = aligned and timedelta(0) <= cutoff-cash_as_of <= timedelta(days=1)
    except (KeyError, ValueError, TypeError): aligned=False
    details=snapshot.get('cash_details',{})
    for balance in projection.cash_balances:
        peers=[b for b in projection.cash_balances if b.currency==balance.currency]
        # v7 reservation rows lack account_id. Only single-account currencies can be assigned.
        reserved=amounts.get(balance.currency,Decimal('0')) if len(peers)==1 else (Decimal('0') if covered and not amounts.get(balance.currency) else None)
        result=account_buying_power(ledger_balance=balance.balance,
                    details=details.get(balance.account_id+'_'+balance.currency,{}),reservation_amount=reserved,
                    reservation_coverage=covered,snapshot_aligned=aligned)
        result.update(account_id=balance.account_id,currency=balance.currency)
        result.update(snapshot_data_as_of=snapshot.get('data_as_of'), max_snapshot_age_hours=24)
        if not aligned:
            result['reason']='snapshot state version/as-of not verified within prior 24 hours'
        cash_calcs.append(persist('PERSONAL_BUYING_POWER',balance.account_id+':'+balance.currency,result))
        cash_lines.append(json.dumps(result,default=str,ensure_ascii=False))
        if result['status']!='AVAILABLE': missing.append(balance.account_id+':'+balance.currency+':buying_power')
    sections=(ReportSectionInput('actual_transaction_pnl','Transaction FX and actual P&L',tuple(lines) or ('No posted positions.',),
                      status=Availability.PARTIAL if any(':actual_pnl' in m for m in missing) else Availability.AVAILABLE,
                      evidence_ids=tuple(dict.fromkeys(refs)),calculation_ids=tuple(pnl_calcs)),
              ReportSectionInput('account_buying_power','Account cash and buying power',tuple(cash_lines) or ('No posted cash balances.',),
                      status=Availability.PARTIAL if any(':buying_power' in m for m in missing) else Availability.AVAILABLE,
                      evidence_ids=(eid,),calculation_ids=tuple(cash_calcs),metadata={'accounts_and_currencies_aggregated':False}))
    return PersonalOutputs(sections,tuple(dict.fromkeys(refs)),tuple(calcs),tuple(missing))
