import json
import unittest
from dataclasses import replace
from tests.integration import test_r14_equity_mode_bundles as equity_fixtures
from tests.integration import test_analysis_c_selected_asset_research as portfolio_fixtures
from investment_stack.execution import ModeRequest, execute_mode, Availability
from investment_stack.execution.portfolio_thesis_modes import portfolio_thesis_services, SelectedAssetResearchResult
from investment_stack.reporting.portfolio_modes import PortfolioAnalysisRequest, PinnedPortfolioState, PortfolioPosition
from investment_stack.routing import RequestMode
from investment_stack.deep_research import LiveDeepResearchRuntime
from investment_stack.pipelines import PipelineStep


class PipelineExecutionIntegrityTests(unittest.TestCase):
    def single(self):
        fixture = equity_fixtures.R14EquityModeBundleIntegrationTests()
        self.addCleanup(fixture.doCleanups)
        specs = fixture.specs()[:1]
        run, services = fixture.make_services('integrity-single', specs)
        return run, services, ModeRequest(run.run_id, RequestMode.SINGLE_ASSET_ANALYSIS, {'research_specs': specs})

    def test_actual_outputs_are_persisted_consumed_and_run_is_terminal(self):
        run, services, request = self.single()
        result = execute_mode(request, services)
        self.assertTrue(result.report_refs)
        snapshot = run.fetch_phase6_context()
        stages = {r['task_name']: r for r in snapshot['task_states'] if r['task_name'].startswith('stage:')}
        for name in ['fundamental:FANUC', 'valuation:FANUC', 'conditional_review', 'render_partial_aware_report']:
            receipt = json.loads(stages['stage:' + name]['metadata_json'])
            self.assertTrue(receipt['started_at'])
            self.assertTrue(receipt['completed_at'])
            self.assertGreater(receipt['output_count'], 0)
        calc_ids = {r['calculation_id'] for r in snapshot['calculations']}
        sections = snapshot['report_sections']
        self.assertTrue(all(ref in calc_ids for ref in result.calculation_refs))
        self.assertTrue(any(json.loads(s['metadata_json']).get('calculation_ids') for s in sections))
        self.assertEqual(snapshot['run_metadata']['run_status'], result.availability.value)
        self.assertTrue(snapshot['run_metadata']['completed_at'])

    def test_fake_outputs_without_persisted_calculations_fail_before_report(self):
        run, services, request = self.single()
        handler = services.handlers[PipelineStep.DEEP_RESEARCH_REQUESTED_ASSETS]
        deep = next(c.cell_contents for c in handler.__closure__ if isinstance(c.cell_contents, LiveDeepResearchRuntime))
        real = deep.analyze_equity
        def fake(spec):
            outcome = real(spec)
            return replace(outcome, analysis=replace(outcome.analysis,
                fundamental=replace(outcome.analysis.fundamental, metadata={'calculation_id': 'prior-run:calc'}),
                valuation=replace(outcome.analysis.valuation, metadata={'calculation_id': 'prior-run:valuation'})))
        deep.analyze_equity = fake
        result = execute_mode(request, services)
        self.assertEqual(result.availability, Availability.FAILED)
        self.assertFalse(result.report_refs)
        self.assertTrue(any('STAGE_NOT_EXECUTED' in r for r in result.unsupported_reasons))

    def portfolio(self, callback):
        fixture = portfolio_fixtures.SelectedAssetResearchIntegrationTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        run = fixture.run
        state = PinnedPortfolioState(1, 'snapshot:synthetic', fixture.clock, fixture.clock)
        portfolio = PortfolioAnalysisRequest(state, 'JPY', (PortfolioPosition('FANUC', None, 'JPY'),), (), ())
        self.portfolio_callback = callback or fixture.service
        services = portfolio_thesis_services(run_db=run, materiality_selector=lambda p, r: ('FANUC',),
                                            selected_asset_research=callback or fixture.service)
        return run, services, ModeRequest(run.run_id, RequestMode.PERSONAL_PORTFOLIO_ANALYSIS, {'portfolio_request': portfolio})

    def test_selected_task_only_with_data_missing_excuse_is_failure(self):
        run, services, request = self.portfolio(lambda ids, r: SelectedAssetResearchResult((), missing_inputs=('financial_missing',)))
        result = execute_mode(request, services)
        self.assertEqual(result.availability, Availability.FAILED)
        self.assertFalse(result.report_refs)
        self.assertTrue(any('DEEP_RESEARCH_STAGE_NOT_EXECUTED' in r for r in result.unsupported_reasons))

    def test_portfolio_partial_price_still_executes_financials_review_report(self):
        run, services, request = self.portfolio(None)
        result = execute_mode(request, services)
        self.assertTrue(result.report_refs, result.as_dict())
        snapshot = run.fetch_phase6_context()
        self.assertTrue(any(r['calculation_name'] == 'EQUITY_FUNDAMENTAL' for r in snapshot['calculations']))
        self.assertTrue(any(r['calculation_name'] == 'EQUITY_VALUATION' for r in snapshot['calculations']))
        self.assertTrue(any(r['calculation_name'] == 'portfolio_analysis' for r in snapshot['calculations']))
        self.assertTrue(any(s.step == 'conditional_review' for s in result.step_states))

    def test_portfolio_fundamental_without_valuation_receipt_is_failure(self):
        run, services, request = self.portfolio(None)
        callback = self.portfolio_callback
        def incomplete(ids, req):
            result = callback(ids, req)
            excluded = {r['calculation_id'] for r in run.fetch_phase6_context()['calculations'] if r['calculation_name'] == 'EQUITY_VALUATION'}
            return replace(result, calculation_refs=tuple(r for r in result.calculation_refs if r not in excluded))
        replacement = portfolio_thesis_services(run_db=run, materiality_selector=lambda p, r: ('FANUC',), selected_asset_research=incomplete)
        result = execute_mode(request, replacement)
        self.assertEqual(result.availability, Availability.FAILED)
        self.assertFalse(result.report_refs)
