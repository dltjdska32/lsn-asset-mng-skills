"""Exercise the seven-stage portfolio mode without capital-input injection."""
import json
import tempfile
import unittest
from decimal import Decimal as D
from pathlib import Path

from investment_stack.asset_analysis import Phase5AssetAnalysisRuntime
from investment_stack.calculations.equity import EquityFundamentalInput
from investment_stack.calculations.valuation import EquityValuationInput, BusinessType
from investment_stack.evidence import RunDatabaseManager
from investment_stack.materiality import MaterialityEngine, MaterialityConfig
from investment_stack.execution.dispatcher import execute_mode
from investment_stack.execution.models import ModeRequest
from investment_stack.execution.portfolio_thesis_modes import portfolio_thesis_services, SelectedAssetResearchResult
from investment_stack.reporting.models import ReportSectionInput
from investment_stack.reporting.portfolio_modes import PortfolioAnalysisRequest, PortfolioPosition, PinnedPortfolioState
from investment_stack.routing import RequestMode

CLOCK = '2026-10-05T00:00:00+00:00'


class AutomaticRankingTests(unittest.TestCase):
    def execute_portfolio(self, count, corrupt=None):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        run = RunDatabaseManager(Path(temp.name) / 'runs', 'auto-ranking')
        self.assertTrue(run.create().valid)
        run.initialize_run_context(request_mode='PERSONAL_PORTFOLIO_ANALYSIS', analysis_as_of=CLOCK,
            analysis_timezone='UTC', state_version=1, personal_db_instance_id='synthetic',
            portfolio_snapshot_id='snapshot', portfolio_data_as_of=CLOCK)
        ids = tuple('SYNTH-' + str(i) for i in range(count))
        portfolio = PortfolioAnalysisRequest(PinnedPortfolioState(1, 'snapshot', CLOCK, CLOCK),
            'USD', tuple(PortfolioPosition(iid, D('100'), 'USD', 'EQUITY') for iid in ids), (), ())

        def research(selected, request):
            calculations, refs = [], []
            for i, iid in enumerate(selected):
                for metric, value in (('financials', '100'), ('business_quality_score', '.8'),
                                      ('industry_growth_rate', '.1'), ('current_price', '20')):
                    eid = iid + ':' + metric
                    run.add_phase4_evidence(evidence_id=eid, evidence_type='synthetic-research',
                        source_uri='https://example.test/filing', retrieved_at=CLOCK, instrument_id=iid,
                        metric=metric, value=value, currency='USD', observed_at=CLOCK, published_at=CLOCK,
                        freshness_status='STALE' if corrupt == 'stale' and i == 0 else 'FRESH',
                        official_confirmation_status='CONFIRMED',
                        metadata={'assessment_rationale': 'Synthetic documented quality assessment'})
                    if not (corrupt == 'unselected' and i == 0):
                        run.mark_evidence_selected(evidence_id=eid, reason='synthetic verified research')
                    refs.append(eid)
                outputs = Phase5AssetAnalysisRuntime(run, materiality=MaterialityEngine(MaterialityConfig("synthetic", D(".1"), D(".1"), D(".1")))).analyze_equity(
                    EquityFundamentalInput(iid, 'USD', revenue=D('110') + i,
                        prior_revenue=D('100'), net_income=D('10') + i, average_equity=D('50'),
                        total_debt=D('20'), equity=D('100'), evidence_ids=(iid + ':financials',)),
                    EquityValuationInput(iid, BusinessType.STABLE_CASH_FLOW,
                        current_price=D('20'), eps=D('1') + D(i) / 10,
                        evidence_ids=(iid + ':financials', iid + ':current_price')))
                calculations.extend((outputs.fundamental.metadata['calculation_id'],
                                     outputs.valuation.metadata['calculation_id']))
            return SelectedAssetResearchResult((ReportSectionInput('research', 'Research', ('Synthetic results',),
                evidence_ids=tuple(refs), calculation_ids=tuple(calculations)),),
                evidence_refs=tuple(refs), calculation_refs=tuple(calculations))

        services = portfolio_thesis_services(run_db=run,
            materiality_selector=lambda p, r: ids, selected_asset_research=research)
        result = execute_mode(ModeRequest(run.run_id, RequestMode.PERSONAL_PORTFOLIO_ANALYSIS,
                              {'portfolio_request': portfolio}), services)
        self.assertEqual(len(result.step_states), 7, result.as_dict())
        self.assertTrue(result.report_refs, result.as_dict())
        rows = run.fetch_phase6_context()['calculations']
        competition = next(r for r in rows if r['calculation_name'] == 'CAPITAL_COMPETITION')
        return run, result, json.loads(competition['result_json']), json.loads(competition['inputs_json'])

    def test_six_and_eight_holdings_rank_automatically_from_actual_phase5_results(self):
        for count in (6, 8):
            with self.subTest(count=count):
                run, result, ranking, inputs = self.execute_portfolio(count)
                self.assertEqual(len(ranking['ranked']), count)
                self.assertEqual(ranking['unranked'], [])
                self.assertEqual(ranking['ranked'][0]['instrument_id'], 'SYNTH-' + str(count - 1))
                self.assertEqual(len(inputs['automatic_input_calculation_ids']), count)
                calculations = {r['calculation_id']: r for r in run.fetch_phase6_context()['calculations']}
                for cid in inputs['automatic_input_calculation_ids']:
                    source = json.loads(calculations[cid]['inputs_json'])
                    self.assertEqual({calculations[r]['calculation_name'] for r in source['source_calculation_ids']},
                                     {'EQUITY_FUNDAMENTAL', 'EQUITY_VALUATION'})
                # No forecast assumptions invented to make ranking succeed.
                self.assertTrue(all(not r['scenario_cagrs'] for r in ranking['ranked']))
                self.assertEqual(result.availability.value, 'PARTIAL')

    def test_stale_or_unselected_research_cannot_enter_ranking(self):
        for corruption in ('stale', 'unselected'):
            with self.subTest(corruption=corruption):
                _, _, ranking, _ = self.execute_portfolio(6, corruption)
                self.assertEqual(len(ranking['ranked']), 5)
                self.assertEqual([r['instrument_id'] for r in ranking['unranked']], ['SYNTH-0'])
