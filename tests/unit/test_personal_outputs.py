import unittest
from decimal import Decimal as D
from types import SimpleNamespace
import json
from investment_stack.calculations.personal import reconstruct_base_cost, account_buying_power
from investment_stack.execution.personal_outputs import render_personal_outputs
from tests.integration import test_phase3_ledger as fixtures


def entry(delta, *, currency='USD', basis='100', tx='BUY', metadata=None, cash=None):
    return {'status':'POSTED','entry_type':'ASSET','quantity_delta_decimal':delta,
            'currency':currency,'cost_basis_delta_decimal':basis,'cost_basis_status':'WEIGHTED_AVERAGE',
            'transaction_type':tx,'metadata':metadata or {}, 'cash_amount_decimal':cash}


class PersonalOutputsTests(unittest.TestCase):
    def test_weighted_average_partial_sell_uses_historical_fx_and_net_proceeds(self):
        rows=[entry('10',basis='100',metadata={'acquisition_fx':'1300','acquisition_fx_base_currency':'KRW'}),
              entry('10',basis='200',metadata={'acquisition_fx':'1400','acquisition_fx_base_currency':'KRW'}),
              entry('-5',tx='SELL',cash='80',metadata={'execution_fx':'1500','execution_fx_base_currency':'KRW'})]
        result=reconstruct_base_cost(rows,base_currency='KRW')
        self.assertEqual(result.quantity,D('15'))
        self.assertEqual(result.base_cost,D('307500'))
        self.assertEqual(result.realized_gain,D('17500'))

    def test_unknown_opening_propagates_despite_later_known_buy(self):
        rows=[entry('5',tx='INITIAL_POSITION',basis=None),
              entry('5',metadata={'base_currency':'KRW','actual_base_cost':'15000'})]
        result=reconstruct_base_cost(rows,base_currency='KRW')
        self.assertIsNone(result.base_cost)

    def test_same_currency_includes_buy_tax_and_net_sell_fee_tax(self):
        buy=entry('10',currency='KRW',basis='1000');buy['tax_amount_decimal']='10'
        sell=entry('-5',currency='KRW',tx='SELL',cash='600')
        result=reconstruct_base_cost([buy,sell],base_currency='KRW')
        self.assertEqual(result.base_cost,D('505'))
        self.assertEqual(result.realized_gain,D('95'))

    def test_cash_reservations_are_not_double_counted(self):
        details={'deposit':'1000','settled_cash':'900','buying_power':'700','withdrawable':'500','collateral':'200','reservations_in_buying_power':True}
        result=account_buying_power(ledger_balance=D('1000'),details=details,reservation_amount=D('100'),reservation_coverage=True,snapshot_aligned=True)
        self.assertEqual(result['available_for_purchase'],D('700'))
        self.assertEqual(result['collateral'],D('200'))
        details['reservations_in_buying_power']=False
        self.assertEqual(account_buying_power(ledger_balance=D('1000'),details=details,reservation_amount=D('100'),reservation_coverage=True,snapshot_aligned=True)['available_for_purchase'],D('600'))

    def test_cash_conflict_and_unknown_settlement_withhold_buying_power(self):
        for details in ({'deposit':'999','settled_cash':'900','buying_power':'700','reservations_in_buying_power':False},{'deposit':'1000'}):
            result=account_buying_power(ledger_balance=D('1000'),details=details,reservation_amount=D('0'),reservation_coverage=True,snapshot_aligned=True)
            self.assertIsNone(result['available_for_purchase'])
            self.assertEqual(result['status'],'UNAVAILABLE')

    def test_real_posted_ledger_reaches_calculation_and_section_without_mutation(self):
        fixture=fixtures.Phase3LedgerTests();fixture.setUp();self.addCleanup(fixture.tearDown)
        fixture.opening_cash('10000')
        fixture.ledger.post(fixture.intent(fixtures.TransactionType.BUY,account_id='a',instrument_id='fanuc',quantity='10',unit_price='100',currency='JPY'))
        version=fixture.ledger.get_current_state_version()
        projection=fixture.ledger.get_projection_as_of_state_version(version)
        class Run:
            def __init__(self): self.evidence=[];self.calcs=[]
            def fetch_phase6_context(self): return {'pinned_personal_state':{'state_version':version,'portfolio_snapshot_id':'synthetic'}}
            def add_evidence(self,**kwargs): self.evidence.append(kwargs)
            def add_calculation(self,**kwargs): self.calcs.append(kwargs)
        run=Run()
        result=render_personal_outputs(run,fixture.ledger,projection,{}, {}, {'state_version':version,'cash_details':{}},'JPY','2026-08-12T00:00:00+09:00')
        self.assertEqual(len(run.calcs),2)
        self.assertEqual(run.calcs[0]['result']['base_cost'],D('1000'))
        self.assertIsNone(run.calcs[0]['result']['unrealized_gain'])
        self.assertTrue(result.sections[0].calculation_ids)
        self.assertEqual(run.calcs[1]['result']['status'],'UNAVAILABLE')
        self.assertEqual(fixture.ledger.get_current_state_version(),version)
        self.assertTrue(all(run.evidence[0]['evidence_id'] in c['inputs']['evidence_ids'] for c in run.calcs))

    def make_output_fixture(self, *, sell=False, two_accounts=False, reservations=()):
        fixture=fixtures.Phase3LedgerTests();fixture.setUp();self.addCleanup(fixture.tearDown)
        fixture.opening_cash('10000')
        fixture.ledger.post(fixture.intent(fixtures.TransactionType.BUY,account_id='a',instrument_id='fanuc',quantity='10',unit_price='100',currency='JPY'))
        if sell:
            fixture.ledger.post(fixture.intent(fixtures.TransactionType.SELL,account_id='a',instrument_id='fanuc',quantity='5',unit_price='150',fee_amount='10',tax_amount='5',currency='JPY',occurred_at=fixtures.WHEN.replace(hour=13)))
        if two_accounts: fixture.opening_cash('2000',account='b')
        version=fixture.ledger.get_current_state_version()
        fixture.ledger.declare_cash_reservations(expected_state_version=version,reservations=reservations)
        projection=fixture.ledger.get_projection_as_of_state_version(version)
        class Run:
            def __init__(self): self.evidence=[];self.calcs=[];self.market=[]
            def fetch_phase6_context(self): return {'pinned_personal_state':{'state_version':version,'portfolio_snapshot_id':'synthetic'},'evidence':self.market}
            def add_evidence(self,**kwargs): self.evidence.append(kwargs)
            def add_calculation(self,**kwargs): self.calcs.append(kwargs)
        return fixture,projection,Run()

    def quote(self, *, evidence_id='quote:current',observed='2026-08-12T08:59:00+09:00',retrieved='2026-08-12T09:01:00+09:00'):
        return SimpleNamespace(evidence_id=evidence_id,
            freshness=SimpleNamespace(status=SimpleNamespace(value='FRESH')),
            observation=SimpleNamespace(instrument_id='fanuc',metric='current_price',currency='JPY',value=D('120'),observed_at=observed,retrieved_at=retrieved))

    def persisted_quote(self):
        obs=self.quote().observation
        return {'evidence_id':'quote:current','instrument_id':obs.instrument_id,
                'metric':obs.metric,'currency':obs.currency,'value_text':json.dumps(str(obs.value)),
                'observed_at':obs.observed_at,'retrieved_at':obs.retrieved_at,
                'selection_state':'SELECTED','freshness_status':'FRESH'}

    def test_posted_cash_leg_supplies_net_proceeds_when_intent_omits_cash(self):
        fixture,projection,run=self.make_output_fixture(sell=True)
        render_personal_outputs(run,fixture.ledger,projection,{}, {}, {},'JPY','2026-08-12T09:00:00+09:00')
        self.assertEqual(run.calcs[0]['result']['base_cost'],D('500'))
        self.assertEqual(run.calcs[0]['result']['realized_gain'],D('235'))

    def test_same_run_quote_retrieved_after_pinned_clock_values_portfolio(self):
        fixture,projection,run=self.make_output_fixture()
        run.market=[self.persisted_quote()]
        render_personal_outputs(run,fixture.ledger,projection,{'fanuc':self.quote()}, {}, {},'JPY','2026-08-12T09:00:00+09:00')
        self.assertEqual(run.calcs[0]['result']['unrealized_gain'],D('200'))
        self.assertIn('quote:current',run.calcs[0]['inputs']['evidence_ids'])

    def test_prior_run_future_and_impossible_timestamp_quotes_are_rejected(self):
        fixture,projection,run=self.make_output_fixture()
        run.market=[self.persisted_quote()]
        for quote in (self.quote(evidence_id='quote:previous'),self.quote(observed='2026-08-12T10:00:00+09:00'),self.quote(retrieved='2026-08-12T08:58:00+09:00')):
            render_personal_outputs(run,fixture.ledger,projection,{'fanuc':quote}, {}, {},'JPY','2026-08-12T09:00:00+09:00')
            result=run.calcs[-2]
            self.assertIsNone(result['result']['current_value'])
            self.assertEqual(len(result['inputs']['evidence_ids']),1)

    def test_existing_evidence_id_cannot_bind_other_asset_value_or_rejected_fact(self):
        fixture,projection,run=self.make_output_fixture()
        for key,value in [('instrument_id','other'),('value_text','"999"'),('currency','USD'),('selection_state','REJECTED')]:
            persisted=self.persisted_quote();persisted[key]=value;run.market=[persisted]
            render_personal_outputs(run,fixture.ledger,projection,{'fanuc':self.quote()}, {}, {},'JPY','2026-08-12T09:00:00+09:00')
            self.assertIsNone(run.calcs[-2]['result']['current_value'])

    def test_fresh_reconciled_snapshot_cash_runs_and_stale_future_cash_withheld(self):
        fixture,projection,run=self.make_output_fixture()
        details={'a_JPY':{'deposit':'9000','settled_cash':'8000','buying_power':'7500','withdrawable':'7000','collateral':'500','reservations_in_buying_power':False}}
        for date,expected in (('2026-08-12T08:00:00+09:00',D('7500')),('2026-08-10T08:00:00+09:00',None),('2026-08-12T10:00:00+09:00',None)):
            snapshot={'state_version':projection.state_version,'data_as_of':date,'cash_details':details}
            result=render_personal_outputs(run,fixture.ledger,projection,{}, {}, snapshot,'JPY','2026-08-12T09:00:00+09:00')
            self.assertEqual(run.calcs[-1]['result']['available_for_purchase'],expected)
            self.assertTrue(result.sections[1].calculation_ids)

    def test_accountless_reservation_cannot_be_assigned_to_two_accounts(self):
        from investment_stack.personal.reserves import CashReservationDraft
        fixture,projection,run=self.make_output_fixture(two_accounts=True,reservations=(CashReservationDraft('PENDING_ORDER','JPY',D('100')),))
        details={a+'_JPY':{'deposit':amount,'settled_cash':amount,'buying_power':amount,'reservations_in_buying_power':False} for a,amount in [('a','9000'),('b','2000')]}
        snapshot={'state_version':projection.state_version,'data_as_of':'2026-08-12T08:00:00+09:00','cash_details':details}
        render_personal_outputs(run,fixture.ledger,projection,{}, {},snapshot,'JPY','2026-08-12T09:00:00+09:00')
        for calculation in run.calcs[1:]:
            self.assertIsNone(calculation['result']['available_for_purchase'])
            self.assertIn('account-specific reservation',calculation['result']['reason'])

    def test_fully_closed_position_keeps_realized_pnl_in_report(self):
        fixture,projection,run=self.make_output_fixture()
        fixture.ledger.post(fixture.intent(fixtures.TransactionType.SELL,account_id='a',instrument_id='fanuc',quantity='10',unit_price='150',fee_amount='10',tax_amount='5',currency='JPY',occurred_at=fixtures.WHEN.replace(hour=13)))
        version=fixture.ledger.get_current_state_version()
        projection=fixture.ledger.get_projection_as_of_state_version(version)
        run.fetch_phase6_context=lambda: {'pinned_personal_state':{'state_version':version,'portfolio_snapshot_id':'synthetic'},'evidence':[]}
        result=render_personal_outputs(run,fixture.ledger,projection,{}, {},{},'JPY','2026-08-12T09:00:00+09:00')
        self.assertFalse(projection.positions)
        self.assertEqual(run.calcs[0]['result']['realized_gain'],D('485'))
        self.assertEqual(run.calcs[0]['result']['quantity'],D('0'))
        self.assertEqual(run.calcs[0]['result']['status'],'AVAILABLE')
        self.assertTrue(result.sections[0].lines)
        self.assertNotEqual(result.sections[0].calculation_ids,result.sections[1].calculation_ids)

    def test_posted_reversal_cancels_sell_without_inventing_new_disposal(self):
        fixture,projection,run=self.make_output_fixture(sell=True)
        sale=next(t for t in fixture.ledger.list_transactions() if t['transaction_type']=='SELL')
        fixture.ledger.reverse(sale['transaction_id'],occurred_at=fixtures.WHEN.replace(hour=14),timezone_name='Asia/Tokyo')
        version=fixture.ledger.get_current_state_version()
        projection=fixture.ledger.get_projection_as_of_state_version(version)
        run.fetch_phase6_context=lambda: {'pinned_personal_state':{'state_version':version,'portfolio_snapshot_id':'synthetic'},'evidence':[]}
        render_personal_outputs(run,fixture.ledger,projection,{}, {},{},'JPY','2026-08-12T09:00:00+09:00')
        self.assertEqual(run.calcs[0]['result']['base_cost'],D('1000'))
        self.assertEqual(run.calcs[0]['result']['realized_gain'],D('0'))
        self.assertEqual(run.calcs[0]['result']['quantity'],D('10'))
        self.assertIn(sale['transaction_id'],run.evidence[0]['metadata']['reversed_transaction_ids'])

    def test_negative_cash_reservations_fail_validation(self):
        with self.assertRaises(ValueError):
            account_buying_power(ledger_balance=D('1000'),details={},reservation_amount=D('-1'),reservation_coverage=True,snapshot_aligned=True)
