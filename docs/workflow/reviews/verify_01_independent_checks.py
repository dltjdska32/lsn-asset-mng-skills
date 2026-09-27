"""VERIFY-01: real synthetic ledger fault and pinned/default market path checks."""
from pathlib import Path
import sys, importlib.util, json, tempfile
from datetime import datetime, timezone
from decimal import Decimal
from dataclasses import replace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'runtime'),str(ROOT)]
spec=importlib.util.spec_from_file_location('verify_helpers',ROOT/'docs/workflow/reviews/review_code_01_final_probes.py')
h=importlib.util.module_from_spec(spec); spec.loader.exec_module(h)
from investment_stack.execution import ModeRequest, execute_mode, Availability
from investment_stack.pipelines import PipelineStep
from investment_stack.routing import RequestMode
from investment_stack.personal.intent import TransactionIntent, TransactionType, ConfirmationState
from investment_stack.providers import build_default_provider_executor
from investment_stack.providers.credentials import EnvironmentCredentials
from investment_stack.providers.http import urllib_transport
from investment_stack.evidence import RunDatabaseManager, EvidenceResearchStore
from investment_stack.research import Phase4ResearchRuntime
from investment_stack.web_research import WebResearchAdapter
from investment_stack.web_research.models import WebResearchResponse
from investment_stack.asset_analysis import Phase5AssetAnalysisRuntime
from investment_stack.materiality import MaterialityEngine, MaterialityConfig
from investment_stack.deep_research import LiveDeepResearchRuntime, EquityResearchSpec
from investment_stack.calculations import BusinessType
from investment_stack.reporting.runtime import section_from_analysis_result

def receipt_check():
    case=h.FinalReviewProbes(); case.setUp()
    try:
        run,services,ledger,_=case.make('verify-post-fault',RequestMode.ASSET_UPDATE)
        intent=TransactionIntent(TransactionType.DEPOSIT,account_id='cash',cash_amount='1234',currency='USD',occurred_at=datetime(2026,9,27,11),timezone='UTC',confirmation_state=ConfirmationState.CONFIRMED,idempotency_key='verify-post-once')
        request=ModeRequest(run.run_id,RequestMode.ASSET_UPDATE,{'transaction_intent':intent})
        before=ledger.get_current_state_version()
        original=run.record_task_state
        def fail_after_post(*args,**kwargs):
            if str(kwargs.get('task_name','')).endswith(PipelineStep.DECIDE_POSTING.value): raise OSError('synthetic post-commit log fault')
            return original(*args,**kwargs)
        with patch.object(run,'record_task_state',side_effect=fail_after_post):
            result=execute_mode(request,services)
        assert result.availability is Availability.FAILED, result
        assert result.mutation_receipt['status']=='POSTED'
        assert ledger.get_current_state_version()==before+1
        committed=result.mutation_receipt
        retry=execute_mode(request,services)
        assert ledger.get_current_state_version()==before+1
        assert retry.mutation_receipt['status']=='ALREADY_POSTED'
        assert retry.mutation_receipt['transaction_ids']==committed['transaction_ids']
        print(json.dumps({'check':'real-ledger-post-log-failure-retry','status':result.availability.value,'receipt':dict(committed),'retry':dict(retry.mutation_receipt)},default=str),flush=True)
    finally: case.doCleanups()

def market_check(live=False):
    cutoff='2026-09-27T12:00:00+00:00'
    payloads={
      'yahoo': {'chart':{'result':[{'meta':{'currency':'USD','symbol':'AAPL','exchangeName':'NMS','exchangeTimezoneName':'America/New_York','regularMarketPrice':341.07,'regularMarketTime':1790366401}}],'error':None}},
      'naver': {'itemCode':'005930','closePrice':'286,500','localTradedAt':'2026-09-23T20:20:21+09:00','marketSessionType':'afterMarket','stockExchangeType':{'code':'KS','delayTime':0,'endTime':'1530','closePriceSendTime':'1630'}}}
    for instrument,ticker,country,currency,key,session,price in [('NASDAQ:AAPL','AAPL','USA','USD','yahoo','2026-09-25','341.07'),('KRX:005930','005930','KOR','KRW','naver','2026-09-23','286500')]:
        calls=[]
        def transport(url,headers,timeout):
            market=url.startswith('https://query1.finance.yahoo.com/v8/finance/chart/AAPL') or url.startswith('https://m.stock.naver.com/api/stock/005930/basic')
            if market:
                calls.append(url)
                return urllib_transport(url,headers,timeout) if live else json.dumps(payloads[key]).encode()
            return b'{}' # financial/non-market inputs deliberately unavailable; no credentials
        executor=build_default_provider_executor(credentials=EnvironmentCredentials({}),transport=transport)
        with tempfile.TemporaryDirectory(prefix='verify01-market-') as temporary:
            run=RunDatabaseManager(Path(temporary)/'workspace','market')
            assert run.create().valid
            run.initialize_run_context(request_mode='SINGLE_ASSET_ANALYSIS',analysis_as_of=cutoff,analysis_timezone='UTC',state_version=0,personal_db_instance_id='NONE:VERIFY')
            research=Phase4ResearchRuntime(providers=executor,evidence=EvidenceResearchStore(run),web_research=WebResearchAdapter(lambda intent,query,as_of:WebResearchResponse(intent,())))
            analysis=Phase5AssetAnalysisRuntime(run,materiality=MaterialityEngine(MaterialityConfig('VERIFY-SYNTHETIC',Decimal('.05'),Decimal('.2'),Decimal('.8'))))
            observed=[]; original=analysis.analyze_equity
            def capture(fundamental,valuation):
                observed.append(valuation.current_price)
                return original(fundamental,valuation)
            analysis.analyze_equity=capture
            deep=LiveDeepResearchRuntime(research=research,analysis=analysis,analysis_as_of=cutoff,analysis_timezone='UTC')
            outcome=deep.analyze_equity(EquityResearchSpec(instrument_id=instrument,display_name=ticker,ticker=ticker,country=country,currency=currency,business_type=BusinessType.STABLE_CASH_FLOW,market_query=ticker+' price',fundamentals_query=ticker+' fundamentals'))
            selected=outcome.market.selected
            if selected:
                assert selected.freshness.status.value=='LAST_VALID_CLOSE'
                assert selected.freshness.market_session_date==session
                assert observed==[Decimal(str(selected.observation.value))]
                if not live: assert observed==[Decimal(price)]
                text=' '.join(section_from_analysis_result(outcome.analysis.valuation,name='valuation').lines)
                assert '실시간 시세가 아닙니다' in text
                assert session in text
                assert run.fetch_phase6_context()['market_observations']
            elif not live: raise AssertionError('pinned replay not selected')
            else: assert observed==[None],observed
            print(json.dumps({'check':'live-now-pinned-cutoff' if live else 'synthetic-pinned-default-path','retrieved_now':datetime.now(timezone.utc).isoformat(),'cutoff':cutoff,'instrument':instrument,'urls':calls,'selected':bool(selected),'price':str(selected.observation.value) if selected else None,'freshness':selected.freshness.status.value if selected else None,'session':selected.freshness.market_session_date if selected else None,'public_available':selected.freshness.public_available_time if selected else None,'phase5_price':str(observed),'valuation_status':outcome.analysis.valuation.status.value},ensure_ascii=False),flush=True)

if __name__=='__main__':
    if '--live' in sys.argv: market_check(True)
    else: receipt_check(); market_check(False)
