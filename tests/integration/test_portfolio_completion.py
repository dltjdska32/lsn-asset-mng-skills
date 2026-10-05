"""Real configured executors with synthetic providers and disposable ledger only."""
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from decimal import Decimal
from urllib.parse import unquote
from dataclasses import replace
from types import SimpleNamespace

from investment_stack.personal.manager import PersonalDatabaseManager
from investment_stack.personal.ledger import PersonalLedgerService
from investment_stack.personal.intent import TransactionIntent, TransactionType, ConfirmationState, CostBasisStatus
from investment_stack.evidence import RunDatabaseManager
from investment_stack.execution.host import compose_configured_host
from investment_stack.execution.models import ModeRequest
from investment_stack.execution.dispatcher import execute_mode
from investment_stack.routing import RequestMode
from tests.integration.test_generic_instruments import payload
from tests.unit.test_live_portfolio_providers import fx_payload
from investment_stack.calculations.fund import FundAnalysisInput, FundHolding
from investment_stack.execution.fund_outputs import render_portfolio_funds
from investment_stack.reporting.portfolio_modes import PortfolioAnalysisRequest, PinnedPortfolioState, PortfolioPosition
from investment_stack.execution.analysis_modes import equity_analysis_services
from investment_stack.reporting.runtime import Phase6ReportReviewRuntime
from investment_stack.deep_research import LiveDeepResearchRuntime
from investment_stack.pipelines import PipelineStep
from tests.integration import test_r14_equity_mode_bundles as equity_fixtures


class PortfolioCompletionTests(unittest.TestCase):
    def setup_run(self, *, second_account=False):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        manager = PersonalDatabaseManager(root / 'synthetic-personal.db', backup_directory=root / 'backups')
        self.assertEqual(manager.initialize().status.value, 'VALID')
        ledger = PersonalLedgerService(manager)
        at = datetime(2026, 10, 1, 8, tzinfo=timezone.utc)
        ledger.register_account('A', name='Synthetic A', currency='USD', timezone_name='UTC')
        for iid, asset_class, listing in [('ORCL', 'EQUITY', 'NYSE:ORCL'), ('QQQ', 'FUND', 'NASDAQ:QQQ')]:
            ledger.register_instrument(iid, canonical_name=iid, currency='USD', asset_class=asset_class,
                                       identifiers={'listing_id': listing})
            ledger.post(TransactionIntent(TransactionType.INITIAL_POSITION, account_id='A', instrument_id=iid,
                quantity='2', total_cost='100', currency='USD', unit='SHARE', cost_basis_status=CostBasisStatus.USER_PROVIDED,
                occurred_at=at, timezone='UTC', confirmation_state=ConfirmationState.CONFIRMED, idempotency_key=iid))
        ledger.post(TransactionIntent(TransactionType.DEPOSIT, account_id='A', cash_amount='20', currency='USD',
            occurred_at=at, timezone='UTC', confirmation_state=ConfirmationState.CONFIRMED, idempotency_key='cash'))
        if second_account:
            ledger.register_account('B', name='Synthetic B', currency='USD', timezone_name='UTC')
            ledger.post(TransactionIntent(TransactionType.INITIAL_POSITION, account_id='B', instrument_id='ORCL',
                quantity='1', total_cost='50', currency='USD', unit='SHARE', cost_basis_status=CostBasisStatus.USER_PROVIDED,
                occurred_at=at, timezone='UTC', confirmation_state=ConfirmationState.CONFIRMED, idempotency_key='B-ORCL'))
        ledger.create_portfolio_snapshot(snapshot_id='synthetic-pin', snapshot_type='BOOK_ONLY', as_of=at, data={})
        run = RunDatabaseManager(root / 'runs', 'synthetic-completion')
        self.assertTrue(run.create().valid)
        run.initialize_run_context(request_mode='PERSONAL_PORTFOLIO_ANALYSIS', analysis_as_of='2026-10-01T11:00:00+00:00',
            analysis_timezone='UTC', state_version=ledger.get_current_state_version(), personal_db_instance_id=manager.instance_id,
            portfolio_snapshot_id='synthetic-pin', portfolio_data_as_of=at.isoformat())
        def transport(url, headers, timeout):
            decoded = unquote(url)
            for symbol, exchange, kind, price in [('ORCL', 'NYQ', 'EQUITY', '100'), ('QQQ', 'NMS', 'ETF', '25')]:
                if '/chart/' + symbol in decoded:
                    data = json.loads(payload(symbol, exchange, kind=kind))
                    data['chart']['result'][0]['meta']['regularMarketPrice'] = price
                    return json.dumps(data).encode()
            for symbol, pair, rate in [('JPYKRW=X', 'JPY/KRW', '8.5'), ('KRW=X', 'USD/KRW', '1360'), ('JPY=X', 'USD/JPY', '160')]:
                if '/chart/' + symbol in decoded:
                    return json.dumps(fx_payload(pair, rate)).encode()
            raise OSError('synthetic unavailable source')
        services = compose_configured_host(run, ledger, transport=transport, research_all_held=True)
        return manager, run, services

    def execute(self, run, services):
        return execute_mode(ModeRequest(run.run_id, RequestMode.PERSONAL_PORTFOLIO_ANALYSIS,
            {'portfolio_source': 'pinned_ledger', 'evaluation_currency': 'USD'}), services)

    def test_actual_seven_stages_consume_partial_outputs_and_concentration_reviews(self):
        manager, run, services = self.setup_run()
        before = hashlib.sha256(manager.database_path.read_bytes()).hexdigest()
        result = self.execute(run, services)
        self.assertEqual(len(result.step_states), 7)
        self.assertTrue(result.report_refs, result.as_dict())
        context = run.fetch_phase6_context()
        calculations = {row['calculation_id']: row for row in context['calculations']}
        evidence = {row['evidence_id'] for row in context['evidence']}
        required = {'EQUITY_FUNDAMENTAL', 'EQUITY_VALUATION', 'FUND', 'portfolio_analysis',
                    'PERSONAL_ACTUAL_PNL', 'PERSONAL_BUYING_POWER', 'portfolio_risk_proxy',
                    'PORTFOLIO_FUND_LOOKTHROUGH', 'CAPITAL_COMPETITION', 'adversarial_review'}
        self.assertTrue(required <= {row['calculation_name'] for row in calculations.values()})
        for row in calculations.values():
            inputs = json.loads(row['inputs_json'])
            self.assertTrue(set(inputs.get('evidence_ids', ())) <= evidence)
            self.assertTrue(set(inputs.get('source_calculation_ids', ())) <= calculations.keys())
        competition = next(json.loads(row['result_json']) for row in calculations.values() if row['calculation_name'] == 'CAPITAL_COMPETITION')
        self.assertIn('SINGLE_ASSET_OVER_30_PERCENT', competition['review_triggers'])
        review = [json.loads(row['result_json']) for row in calculations.values() if row['calculation_name'] == 'adversarial_review']
        self.assertTrue(any(row['subject'] == 'ORCL' and row['review_level'] == 3
            and 'SINGLE_ASSET_OVER_30_PERCENT' in row['review_triggers'] for row in review))
        self.assertTrue(all(row['status'] == 'PARTIAL' for row in review))
        stage = next(step for step in result.step_states if step.step == 'conditional_review')
        self.assertEqual(stage.availability.value, 'PARTIAL')
        report = result.step_states[-1].result.output['report']
        sections = report.sections
        self.assertEqual([section.name for section in sections[:10]], ['capital_competition_' + str(i) for i in range(1, 11)])
        consumed = {ref for section in sections for ref in section.calculation_ids}
        for name in required - {'CAPITAL_COMPETITION', 'EQUITY_FUNDAMENTAL', 'EQUITY_VALUATION'}:
            self.assertTrue(any(row['calculation_id'] in consumed for row in calculations.values() if row['calculation_name'] == name), name)
        self.assertIn('descriptive only', report.markdown)
        self.assertEqual(hashlib.sha256(manager.database_path.read_bytes()).hexdigest(), before)

    def test_same_instrument_in_multiple_accounts_aggregates_for_analysis(self):
        manager, run, services = self.setup_run(second_account=True)
        before = hashlib.sha256(manager.database_path.read_bytes()).hexdigest()
        result = self.execute(run, services)
        self.assertTrue(result.report_refs, result.as_dict())
        context = run.fetch_phase6_context()
        rows = [json.loads(row['result_json']) for row in context['calculations'] if row['calculation_name'] == 'PERSONAL_ACTUAL_PNL']
        self.assertEqual({row['account_id'] for row in rows if row['instrument_id'] == 'ORCL'}, {'A', 'B'})
        portfolio = next(step.result.output['analysis'] for step in result.step_states if step.result and 'analysis' in step.result.output)
        self.assertEqual(portfolio.gross_assets, Decimal('370'))
        self.assertEqual(hashlib.sha256(manager.database_path.read_bytes()).hexdigest(), before)

    def test_official_fund_inputs_match_saved_holdings_and_publication_cutoff(self):
        cutoff = '2026-10-01T11:00:00+00:00'
        request = PortfolioAnalysisRequest(PinnedPortfolioState(1, 'synthetic', cutoff, cutoff), 'USD',
            (PortfolioPosition('QQQ', Decimal('100'), 'USD', 'FUND'),), (), ())
        result = SimpleNamespace(gross_assets=Decimal('200'), state_version=1, snapshot_ref='synthetic')
        data = FundAnalysisInput('QQQ', None, None, None, None, None,
            (FundHolding('A', Decimal('.5'), 'TECH', 'US', 'USD'),), '2026-10-01',
            evidence_ids=('synthetic-official-holdings',), analysis_as_of=cutoff)
        row = {'run_id': 'synthetic', 'evidence_id': 'synthetic-official-holdings', 'instrument_id': 'QQQ',
            'metric': 'fund_structure', 'selection_state': 'SELECTED', 'source_tier': 1, 'freshness_status': 'FRESH',
            'observed_at': '2026-10-01T08:00:00+00:00', 'published_at': '2026-10-01T08:00:00+00:00',
            'retrieved_at': '2026-10-02T08:00:00+00:00', 'metadata_json': json.dumps({'holdings_as_of': '2026-10-01',
                'holdings': [{'instrument_id': 'A', 'weight': '.5', 'sector': 'TECH', 'country': 'US', 'currency': 'USD'}]})}
        class SyntheticRun:
            def __init__(self, evidence): self.evidence=evidence; self.calcs=[]
            def fetch_phase6_context(self): return {'evidence': [self.evidence], 'calculations': []}
            def add_calculation(self, **kwargs): self.calcs.append(kwargs)
        for label, supplied, persisted, expected in (
            ('bound', data, row, ['QQQ']),
            ('changed holdings', replace(data, holdings=(FundHolding('A', Decimal('.9'), 'TECH', 'US', 'USD'),)), row, []),
            ('future publication', data, {**row, 'published_at': '2026-10-02T08:00:00+00:00'}, []),
        ):
            with self.subTest(label=label):
                run = SyntheticRun(persisted)
                output = render_portfolio_funds(run, request, result, {'QQQ': supplied})
                payload = run.calcs[0]['result']
                self.assertEqual(payload['official_funds'], expected)
                if expected:
                    self.assertEqual(Decimal(payload['holding_exposure']['A']), Decimal('.25'))
                    self.assertIn('synthetic-official-holdings', output.evidence_refs)
                else:
                    self.assertEqual(payload['status'], 'UNAVAILABLE')
                    self.assertEqual(payload['holding_exposure'], {})

    def test_single_asset_capital_context_runs_only_when_explicitly_requested(self):
        for requested in (False, True):
            with self.subTest(requested=requested):
                fixture = equity_fixtures.R14EquityModeBundleIntegrationTests()
                self.addCleanup(fixture.doCleanups)
                specs = fixture.specs()[:1]
                run, services = fixture.make_services('synthetic-optional-' + str(requested), specs,
                    state_version=1, snapshot_ref='synthetic-optional-pin')
                handler = services.handlers[PipelineStep.DEEP_RESEARCH_REQUESTED_ASSETS]
                deep = next(cell.cell_contents for cell in handler.__closure__ if isinstance(cell.cell_contents, LiveDeepResearchRuntime))
                calls = []
                def loader(request):
                    calls.append(request.run_id)
                    return PortfolioAnalysisRequest(PinnedPortfolioState(1, 'synthetic-optional-pin',
                        equity_fixtures.CUTOFF, equity_fixtures.CUTOFF), 'JPY',
                        (PortfolioPosition('HELD', Decimal('100'), 'JPY', 'EQUITY'),), (), ())
                services = equity_analysis_services(deep_research=deep, phase6=Phase6ReportReviewRuntime(run),
                    run_db=run, portfolio_context_loader=loader)
                result = execute_mode(ModeRequest(run.run_id, RequestMode.SINGLE_ASSET_ANALYSIS,
                    {'research_specs': specs, 'portfolio_context': requested}), services)
                self.assertTrue(result.report_refs, result.as_dict())
                self.assertEqual(len(calls), int(requested))
                context = run.fetch_phase6_context()
                capital = [row for row in context['calculations'] if row['calculation_name'] == 'CAPITAL_COMPETITION']
                self.assertEqual(len(capital), int(requested))
                if requested:
                    output = json.loads(capital[0]['result_json'])
                    candidate = next(row for row in output['unranked'] if row['instrument_id'] == specs[0].instrument_id)
                    self.assertFalse(candidate['held'])
                    self.assertIsNone(candidate['score'])
                    refs = json.loads(capital[0]['inputs_json'])['source_calculation_ids']
                    ids = {row['calculation_id'] for row in context['calculations']}
                    self.assertTrue(refs and set(refs) <= ids)
                    sections = result.step_states[-1].result.output['report'].sections
                    self.assertEqual([section.name for section in sections[:10]],
                        ['capital_competition_' + str(i) for i in range(1, 11)])


if __name__ == '__main__':
    unittest.main()
