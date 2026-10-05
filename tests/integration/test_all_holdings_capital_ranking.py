"""Default configured host, real gate and persisted Phase5 outputs; synthetic data."""
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal as D
import hashlib, json, sqlite3, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

from investment_stack.calculations.capital_competition import CapitalCandidate, DIMENSIONS, analyze_capital_competition
from investment_stack.evidence import RunDatabaseManager
from investment_stack.execution.capital_baseline import import_prior_research, persist_lightweight_baseline
from investment_stack.execution.capital_competition import derive_capital_competition_inputs
from investment_stack.execution.dispatcher import execute_mode
from investment_stack.execution.host import compose_configured_host
from investment_stack.execution.models import ModeRequest
from investment_stack.personal import PersonalDatabaseManager, PersonalLedgerService
from investment_stack.personal.intent import TransactionIntent, TransactionType, ConfirmationState, CostBasisStatus
from investment_stack.providers import ProviderObservation, ProviderCapability, ProviderResult, ProviderStatus
from investment_stack.providers.execution import FallbackResult
from investment_stack.routing import RequestMode

CLOCK = '2026-10-05T00:00:00+00:00'

class FixtureProvider:
    """Public-shaped, explicitly synthetic research; no live provider or policy inputs."""
    def __init__(self, selected, unknown=()):
        self.selected = set(selected)
        self.unknown = set(unknown)
        self.calls = []

    def execute(self, request):
        self.calls.append((request.instrument_id, request.metric))
        iid = request.instrument_id
        def obs(metric, value, evidence_type='financial', **metadata):
            return ProviderObservation(evidence_type, 'Synthetic issuer', 'https://example.test/issuer', 1,
                'synthetic', value=str(value), unit='ratio' if metric.endswith('_score') else None,
                currency='USD' if request.capability != ProviderCapability.FX else None,
                instrument_id=iid, metric=metric, retrieved_at=CLOCK, observed_at=CLOCK, published_at=CLOCK,
                official_confirmation_status='CONFIRMED', metadata=metadata)
        if request.capability == ProviderCapability.CURRENT_PRICE:
            observations = (obs('current_price', '100', 'market'),)
        elif request.capability == ProviderCapability.NEWS:
            observations = (replace(obs('latest_relevant_news', None, 'news', material_event=iid in self.selected,
                event_impact='material'), headline='Synthetic event' if iid in self.selected else 'Synthetic routine update'),)
        elif request.metric == 'capital_lightweight':
            score = D('.2') + D(iid.split('-')[-1]) / 10
            observations = () if iid in self.unknown else (
                *tuple(obs(k+'_score', score, assessment_rationale='Synthetic evidenced assessment, not a production fact')
                       for k in ('business_quality','industry_growth')),
                obs('revenue_growth', score), obs('roe', score), obs('pe', 1 / score), obs('debt_to_equity', 1-score))
        elif request.capability == ProviderCapability.FUNDAMENTALS:
            observations = tuple(obs(k, v, canonical_metric=k, period_end='2026-09-30',
                reporting_period='ANNUAL', flow_basis='ANNUAL') for k,v in
                [('revenue','110'),('prior_revenue','100'),('net_income','10'),('average_equity','50'),
                 ('equity','100'),('total_debt','20'),('eps','5'),('shares_outstanding','10')])
        elif request.capability == ProviderCapability.FX:
            observations = (obs('fx_rate', {'USD/KRW':'1000','JPY/KRW':'10','USD/JPY':'100'}[iid], 'market'),)
        else:
            observations = ()
        result = ProviderResult('synthetic', request.capability, ProviderStatus.AVAILABLE if observations else ProviderStatus.UNAVAILABLE, observations)
        return FallbackResult((result,), result if observations else None)

def configured_case(root, count, selected_count, *, unknown=()):
    evolving = (root/'personal.db').exists()
    manager = PersonalDatabaseManager(root/'personal.db', backup_directory=root/'backups')
    if not evolving:
        manager.initialize()
    else:
        manager.startup()
    ledger = PersonalLedgerService(manager)
    if not evolving:
        ledger.register_account('test', name='Synthetic', currency='USD', timezone_name='UTC')
    at = datetime(2026,10,4, tzinfo=timezone.utc)
    ids = tuple('SYNTH-'+str(i) for i in range(count))
    with closing(sqlite3.connect(manager.database_path)) as conn:
        previous_ids={r[0] for r in conn.execute('SELECT instrument_id FROM instruments')}
    for i, iid in enumerate(ids):
        if iid in previous_ids:
            continue
        ledger.register_instrument(iid, canonical_name=iid, currency='USD', asset_class='EQUITY',
            identifiers={'listing_id':'NASDAQ:SYN'+str(i)})
        ledger.post(TransactionIntent(TransactionType.INITIAL_POSITION, account_id='test', instrument_id=iid,
            quantity='1', total_cost='100', currency='USD', unit='SHARE', cost_basis_status=CostBasisStatus.USER_PROVIDED,
            occurred_at=at, timezone='UTC', confirmation_state=ConfirmationState.CONFIRMED, idempotency_key=iid))
    snapshot_id='synthetic-'+str(count)
    ledger.create_portfolio_snapshot(snapshot_id=snapshot_id, snapshot_type='BOOK_ONLY', as_of=at, data={})
    before = hashlib.sha256(manager.database_path.read_bytes()).hexdigest()
    run = RunDatabaseManager(root/'runs', 'configured-'+str(count))
    assert run.create().valid
    run.initialize_run_context(request_mode='PERSONAL_PORTFOLIO_ANALYSIS', analysis_as_of=CLOCK,
        analysis_timezone='UTC', state_version=ledger.get_current_state_version(), personal_db_instance_id=manager.instance_id,
        portfolio_snapshot_id=snapshot_id, portfolio_data_as_of=at.isoformat())
    provider = FixtureProvider(ids[:selected_count], unknown)
    def offline(*args, **kwargs):
        raise OSError('synthetic offline')
    with patch('investment_stack.execution.host.build_default_provider_executor', return_value=provider):
        host = compose_configured_host(run, ledger, transport=offline)
        result = execute_mode(ModeRequest(run.run_id, RequestMode.PERSONAL_PORTFOLIO_ANALYSIS,
            {'portfolio_source':'pinned_ledger','evaluation_currency':'USD'}), host)
    assert hashlib.sha256(manager.database_path.read_bytes()).hexdigest() == before
    context = run.fetch_phase6_context()
    competition = next((json.loads(c['result_json']) for c in context['calculations'] if c['calculation_name']=='CAPITAL_COMPETITION'), None)
    return run, result, competition, provider

class AllHoldingsTests(unittest.TestCase):
    def test_real_default_gate_two_of_six_three_of_eight(self):
        for count, selected in ((6,2),(8,3)):
            with self.subTest(count=count), tempfile.TemporaryDirectory() as tmp:
                run, result, output, provider = configured_case(Path(tmp), count, selected)
                self.assertEqual(len(result.step_states),7,result.as_dict())
                self.assertTrue(result.report_refs,result.as_dict())
                self.assertIsNotNone(output,result.as_dict())
                context=run.fetch_phase6_context()
                gate=[r for r in context['materiality_decisions'] if r['decision']!='FAIL']
                self.assertEqual(len(gate), selected)
                self.assertEqual(len(output['ranking']), count)
                self.assertEqual({r['instrument_id'] for r in output['ranking']},{'SYNTH-'+str(i) for i in range(count)})
                self.assertEqual(len([c for c in context['calculations'] if c['calculation_name']=='PORTFOLIO_LIGHTWEIGHT']),count)
                self.assertEqual(len([c for c in context['calculations'] if c['calculation_name']=='EQUITY_FUNDAMENTAL']),selected)
                self.assertEqual(len([c for c in context['calculations'] if c['calculation_name']=='EQUITY_VALUATION']),selected)
                inputs={c['calculation_id']:c for c in context['calculations']}
                for row in output['ranking']:
                    for dimension in ('growth','valuation','financial_quality','risk_downside'):
                        prov=row['score_provenance'][dimension]
                        self.assertEqual(set(prov['normalization_cohort']),{'SYNTH-'+str(i) for i in range(count)})
                        metric={'growth':'revenue_growth','valuation':'pe','financial_quality':'roe','risk_downside':'debt_to_equity'}[dimension]
                        has_deep=any(c['calculation_name'] in {'EQUITY_FUNDAMENTAL','EQUITY_VALUATION'}
                            and json.loads(c['result_json']).get('subject')==row['instrument_id']
                            and any(m['name']==metric and m['value'] is not None and m['status']=='COMPLETE'
                                    for m in json.loads(c['result_json']).get('metrics',()))
                            for c in context['calculations'])
                        expected={'EQUITY_FUNDAMENTAL','EQUITY_VALUATION'} if has_deep else {'PORTFOLIO_LIGHTWEIGHT'}
                        self.assertTrue(prov['source_calculation_ids'])
                        self.assertTrue({inputs[c]['calculation_name'] for c in prov['source_calculation_ids']} <= expected,(row['instrument_id'],dimension,prov))
                self.assertEqual(len(output['rotations']),count-1)
                self.assertTrue(all(r['status']=='EXPECTED_RETURN_UNAVAILABLE' for r in output['rotations']))
                self.assertTrue(all(not r['automatic_reduce'] for r in output['ranking']))

    def test_new_holdings_six_seven_eight_dynamic_universe(self):
        with tempfile.TemporaryDirectory() as tmp:
            identity=None
            for count in (6,7,8):
                run,result,output,_=configured_case(Path(tmp),count,2)
                current=run.fetch_phase6_context()['pinned_personal_state']['personal_db_instance_id']
                if identity is not None:self.assertEqual(identity,current)
                identity=current
                self.assertEqual(len(output['ranking']),count)
                self.assertIn('SYNTH-'+str(count-1),[r['instrument_id'] for r in output['ranking']])
                self.assertTrue(output['rotations'])

    def test_unknown_asset_keeps_numbered_null_low_confidence_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            _,result,output,_=configured_case(Path(tmp),6,2,unknown=('SYNTH-5',))
            row=next(r for r in output['ranking'] if r['instrument_id']=='SYNTH-5')
            self.assertIsNone(row['capital_score'])
            self.assertEqual(row['ranking_confidence'],'LOW')
            self.assertEqual(row['capital_role'],'WATCH')
            self.assertEqual(row['data_quality'],'UNKNOWN')
            self.assertEqual(row['rank_basis'],'UNKNOWN_PRESENTATION_ORDER')
            self.assertEqual(result.availability.value,'PARTIAL')

    def test_partial_scores_are_evidence_coverage_normalized(self):
        c=CapitalCandidate('A', scores={'growth':D('.7')},score_evidence={'growth':'e'})
        row=analyze_capital_competition((c,)).ranking[0]
        self.assertEqual(row['capital_score'],D('.7'))
        self.assertEqual(row['evidence_coverage'],D('.30'))
        self.assertIsNone(row['valuation_score'])
        self.assertEqual(row['capital_role'],'WATCH')

    def test_latest_evidence_time_orders_actual_instants_across_offsets(self):
        c=CapitalCandidate('A',scores={'growth':D('.7'),'valuation':D('.8')},
            score_evidence={'growth':'g','valuation':'v'},score_provenance={
                'growth':{'observed_at':'2026-10-05T08:00:00+09:00'},
                'valuation':{'observed_at':'2026-10-05T00:00:00+00:00'}})
        self.assertEqual(analyze_capital_competition((c,)).ranking[0]['latest_evidence_time'],'2026-10-05T00:00:00+00:00')

    def test_concentration_32_percent_review_not_auto_reduce_and_weak_five_percent(self):
        strong=CapitalCandidate('strong',weight=D('.32'),scores={k:D('.9') for k in DIMENSIONS},score_evidence={k:'s' for k in DIMENSIONS})
        weak=CapitalCandidate('weak',weight=D('.05'),scores={k:D('.1') for k in DIMENSIONS},score_evidence={k:'w' for k in DIMENSIONS})
        result=analyze_capital_competition((strong,weak))
        self.assertEqual(result.ranking[0]['concentration_risk'],'HIGH')
        self.assertEqual(result.ranking[1]['capital_role'],'REDUCE')
        self.assertIn('SINGLE_ASSET_OVER_30_PERCENT',result.review_triggers)
        self.assertTrue(all(not r['automatic_reduce'] for r in result.ranking))

    def test_legacy_runtime_concentration_policy_removed(self):
        root=Path(__file__).resolve().parents[2]/'runtime'
        for p in root.rglob('*.py'):
            text=p.read_text(encoding='utf-8')
            self.assertNotIn('개별 주식 8% 한도',text,str(p))
            self.assertNotIn('비중 10% 초과',text,str(p))
            self.assertNotIn('종목 8%',text,str(p))

class PriorImportTests(unittest.TestCase):
    def make_run(self,root,name,clock,identity='synthetic'):
        run=RunDatabaseManager(root,name)
        run.create()
        run.initialize_run_context(request_mode='PERSONAL_PORTFOLIO_ANALYSIS',analysis_as_of=clock,
            analysis_timezone='UTC',state_version=1,personal_db_instance_id=identity,
            portfolio_snapshot_id='s',portfolio_data_as_of=clock)
        return run

    def seed(self,run,valid_until,wrong=False):
        clock=run.fetch_phase6_context()['run_metadata']['analysis_as_of']
        run.add_phase4_evidence(evidence_id='score',evidence_type='financial',source_uri='https://example.test/issuer',
            retrieved_at=clock,instrument_id='wrong' if wrong else 'A',metric='growth_score',value='.8',
            observed_at=clock,published_at=clock,freshness_status='FRESH',official_confirmation_status='CONFIRMED',
            metadata={'assessment_rationale':'Synthetic assessment','research_valid_until':valid_until})
        run.mark_evidence_selected(evidence_id='score',reason='synthetic')
        run.add_calculation(calculation_id='light',calculation_name='PORTFOLIO_LIGHTWEIGHT',formula='fixture',
            inputs={'evidence_ids':['score']},result={'subject':'A','metrics':[{'name':'growth_score','value':'.8',
                'status':'COMPLETE','evidence_ids':['score']}]})

    def test_fresh_prior_explicit_import_and_original_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            prior=self.make_run(Path(tmp),'prior','2026-10-04T00:00:00+00:00')
            self.seed(prior,'2026-10-06T00:00:00+00:00')
            run=self.make_run(Path(tmp),'current',CLOCK)
            self.assertEqual(len(import_prior_research(run,prior.database_path,('A',))),1)
            candidate=derive_capital_competition_inputs(run,('A',)).assets[0].candidate
            self.assertEqual(candidate.scores['growth'],D('.8'))
            self.assertEqual(candidate.score_provenance['growth']['source_run_id'],'prior')
            self.assertEqual(candidate.score_provenance['growth']['observed_at'],'2026-10-04T00:00:00+00:00')

    def test_stale_wrong_instrument_and_identity_excluded(self):
        for reason in ('stale','instrument','identity'):
            with self.subTest(reason=reason),tempfile.TemporaryDirectory() as tmp:
                prior=self.make_run(Path(tmp),'prior','2026-10-04T00:00:00+00:00')
                self.seed(prior,'2026-10-04T01:00:00+00:00' if reason=='stale' else '2026-10-06T00:00:00+00:00',wrong=reason=='instrument')
                run=self.make_run(Path(tmp),'current',CLOCK,'other' if reason=='identity' else 'synthetic')
                if reason=='identity':
                    with self.assertRaises(ValueError):import_prior_research(run,prior.database_path,('A',))
                else:
                    self.assertEqual(import_prior_research(run,prior.database_path,('A',)),())
                    self.assertFalse(derive_capital_competition_inputs(run,('A',)).assets[0].candidate.scores)

class SourcePriorityTests(unittest.TestCase):
    def fixture(self):
        from tests.unit.test_capital_competition import SyntheticRun
        return SyntheticRun()

    def add(self,run,iid,cid,stage,name,value):
        eid=cid+':evidence'
        run.snapshot['evidence'].append({'evidence_id':eid,'run_id':run.run_id,'instrument_id':iid,
            'metric':name,'value_text':json.dumps(str(value)),'selection_state':'SELECTED','freshness_status':'FRESH',
            'observed_at':CLOCK,'published_at':CLOCK,'retrieved_at':CLOCK,'official_confirmation_status':'CONFIRMED',
            'source_uri':'https://example.test/research','metadata_json':json.dumps({'assessment_rationale':'synthetic assessment'})})
        run.add_calculation(calculation_id=cid,calculation_name=stage,formula='synthetic',
            inputs={'evidence_ids':[eid]},result={'subject':iid,'metrics':[{'name':name,'value':str(value),
                'status':'COMPLETE','evidence_ids':[eid]}]})

    def test_deep_proxy_wins_over_light_direct_score_at_dimension_level(self):
        run=self.fixture()
        self.add(run,'A','light','PORTFOLIO_LIGHTWEIGHT','growth_score','.9')
        self.add(run,'A','deep','EQUITY_FUNDAMENTAL','revenue_growth','.1')
        self.add(run,'B','peer','PORTFOLIO_LIGHTWEIGHT','revenue_growth','.2')
        a=derive_capital_competition_inputs(run,('A','B')).assets[0].candidate
        self.assertEqual(a.scores['growth'],D('.25'))
        self.assertEqual(a.score_provenance['growth']['source_calculation_ids'],['deep'])
        self.assertEqual(a.score_provenance['growth']['input_priority'],3)

    def test_conflicting_high_priority_proxy_cannot_fall_back_to_light_score(self):
        run=self.fixture()
        self.add(run,'A','light','PORTFOLIO_LIGHTWEIGHT','growth_score','.9')
        self.add(run,'A','deep1','EQUITY_FUNDAMENTAL','revenue_growth','.1')
        self.add(run,'A','deep2','EQUITY_FUNDAMENTAL','revenue_growth','.2')
        self.add(run,'B','peer','PORTFOLIO_LIGHTWEIGHT','revenue_growth','.3')
        a=derive_capital_competition_inputs(run,('A','B')).assets[0].candidate
        self.assertNotIn('growth',a.scores)

    def test_one_peer_does_not_generate_neutral_midrank_for_missing_universe(self):
        run=self.fixture()
        self.add(run,'A','deep','EQUITY_FUNDAMENTAL','revenue_growth','.1')
        assets=derive_capital_competition_inputs(run,('A','B')).assets
        self.assertTrue(all(not a.candidate.scores for a in assets))

if __name__=='__main__':unittest.main()
