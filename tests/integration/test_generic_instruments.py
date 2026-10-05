from contextlib import closing
"""New securities must work without editing any production ticker list."""
import hashlib,json,sqlite3,tempfile,unittest
from pathlib import Path
from datetime import datetime,timezone
from investment_stack.providers.instruments import InstrumentResolver
from investment_stack.providers.capture import market_urls
from investment_stack.web_research.live_news import LiveNewsBackend
from investment_stack.web_research.models import WebResearchIntent
from investment_stack.personal.manager import PersonalDatabaseManager
from investment_stack.personal.ledger import PersonalLedgerService
from investment_stack.personal.intent import TransactionIntent,TransactionType,ConfirmationState,CostBasisStatus
from investment_stack.evidence import RunDatabaseManager
from investment_stack.execution.host import compose_configured_host
from investment_stack.execution.dispatcher import execute_mode
from investment_stack.execution.models import ModeRequest
from investment_stack.routing import RequestMode

NOW='2026-10-01T11:00:00+00:00'
def payload(symbol='AAPL',exchange='NMS',ccy='USD',kind='EQUITY'):
 return json.dumps({'chart':{'result':[{'meta':{'symbol':symbol,'exchangeName':exchange,
  'currency':ccy,'instrumentType':kind,'regularMarketTime':int(datetime.fromisoformat('2026-09-30T20:00:00+00:00').timestamp()),
  'regularMarketPrice':200,'exchangeTimezoneName':'America/New_York'},
  'timestamp':[int(datetime.fromisoformat('2026-09-30T13:30:00+00:00').timestamp())],
  'indicators':{'quote':[{'close':[200]}]}}]}}).encode()

def row(iid,ccy='USD',asset='EQUITY',ids=None):
 return {'instrument_id':iid,'canonical_name':iid,'currency':ccy,'asset_class':asset,'identifiers_json':json.dumps(ids) if ids else None}

class GenericIdentityTests(unittest.TestCase):
 def test_bare_new_ticker_resolves_from_actual_metadata_contract(self):
  r=InstrumentResolver([row('AAPL')],transport=lambda *a:payload())
  x=r.resolve('AAPL');self.assertEqual(x.listing_id,'NASDAQ:AAPL');self.assertEqual(x.equity_spec().country,'USA')
  self.assertIn('content_sha256',x.provenance)
 def test_new_explicit_markets_no_network(self):
  rows=[row('SAMSUNG','KRW',ids={'ticker':'005930','exchange':'KRX'}),
        row('TOYOTA','JPY',ids={'listing_id':'JPX:7203'}),row('NEW_US',ids={'listing_id':'NYSE:IBM'})]
  r=InstrumentResolver(rows);self.assertEqual({x.listing_id for x in r.portfolio(tuple(r.rows)).values()},{'KRX:005930','JPX:7203','NYSE:IBM'})
 def test_type_and_currency_conflicts_fail_closed(self):
  for ccy,kind in [('JPY','EQUITY'),('USD','FUND')]:
   with self.subTest(ccy=ccy,kind=kind),self.assertRaises(ValueError):
    InstrumentResolver([row('AAPL',ccy,kind)],transport=lambda *a:payload()).resolve('AAPL')
 def test_provider_wrong_symbol_not_accepted(self):
  with self.assertRaisesRegex(ValueError,'mismatch'):
   InstrumentResolver([row('AAPL')],transport=lambda *a:payload('MSFT')).resolve('AAPL')
 def test_internal_name_without_identifiers_is_not_guessed(self):
  with self.assertRaisesRegex(ValueError,'ambiguous'):
   InstrumentResolver([row('SOME_COMPANY')],transport=lambda *a:payload()).resolve('SOME_COMPANY')
 def test_registry_does_not_override_db_identity(self):
  r=InstrumentResolver([row('X',ids={'listing_id':'NASDAQ:MSFT'})],registry={'X':{'listing_id':'NYSE:IBM'}})
  self.assertEqual(r.resolve('X').listing_id,'NASDAQ:MSFT')
 def test_invalid_listing_conflicts_and_paths(self):
  for ids in [{'listing_id':'NASDAQ:AAPL','ticker':'MSFT'},{'listing_id':'NYSE:AAPL','exchange':'NASDAQ'},
              {'listing_id':'NASDAQ:../../oops'},{'listing_id':'UNKNOWN:ABC'}]:
   with self.subTest(ids=ids),self.assertRaises(ValueError):InstrumentResolver([row('X',ids=ids)]).resolve('X')
 def test_fund_is_not_an_equity_spec(self):
  x=InstrumentResolver([row('NEW_FUND','KRW','FUND',{'listing_id':'KRX:999999'})]).resolve('NEW_FUND')
  with self.assertRaisesRegex(ValueError,'cannot use'):x.equity_spec()
 def test_capture_universe_is_supplied_not_a_fixed_portfolio(self):
  urls=market_urls({'new':'NASDAQ:AAPL','japan':'JPX:7203','fund':'KRX:999999'})
  self.assertTrue(any('/AAPL?' in u for u in urls));self.assertTrue(any('/7203.T?' in u for u in urls))
  self.assertFalse(any('ORCL' in u or '042660' in u for u in urls))
 def test_business_type_and_sec_identity_are_generic(self):
  from investment_stack.providers.adapters import SecCompanyFactsAdapter
  from investment_stack.providers.models import ProviderRequest
  from investment_stack.providers.registry import ProviderCapability
  x=InstrumentResolver([row('NEW_BANK',ids={'listing_id':'NYSE:JPM','business_type':'FINANCIAL','cik':'19617'})]).resolve('NEW_BANK')
  self.assertEqual(x.equity_spec().business_type.value,'FINANCIAL')
  calls=[]
  def transport(url,*a):
   calls.append(url)
   if 'company_tickers_exchange.json' in url:
    return json.dumps({'fields':['cik','name','ticker','exchange'],'data':[[320193,'Apple','AAPL','Nasdaq']]}).encode()
   return json.dumps({'facts':{}}).encode()
  SecCompanyFactsAdapter(transport=transport).fetch(ProviderRequest(ProviderCapability.FUNDAMENTALS,NOW,'UTC','AAPL','fundamentals',{'ticker':'AAPL','exchange':'NASDAQ'}))
  self.assertEqual(len(calls),2);self.assertIn('CIK0000320193.json',calls[1])
 def test_sec_ambiguous_identity_does_not_fetch_facts(self):
  from investment_stack.providers.adapters import SecCompanyFactsAdapter
  from investment_stack.providers.models import ProviderRequest,ProviderStatus
  from investment_stack.providers.registry import ProviderCapability
  calls=[]
  def transport(url,*a):
   calls.append(url);return json.dumps({'fields':['cik','ticker','exchange'],'data':[[1,'NEW','NYSE'],[2,'NEW','NYSE']]}).encode()
  result=SecCompanyFactsAdapter(transport=transport).fetch(ProviderRequest(ProviderCapability.FUNDAMENTALS,NOW,'UTC','NEW','fundamentals',{'ticker':'NEW','exchange':'NYSE'}))
  self.assertEqual(result.status,ProviderStatus.UNAVAILABLE);self.assertEqual(len(calls),1)
 def test_private_metadata_cannot_enter_market_request(self):
  public={'PRIVATE_ACCOUNT_LABEL':'NASDAQ:AAPL'}
  urls=market_urls(public)
  self.assertTrue(any('/AAPL?' in u for u in urls))
  self.assertFalse(any('PRIVATE_ACCOUNT_LABEL' in u for u in urls))
  for listing in ['NASDAQ:AAPL?quantity=12','KRX:account-secret','NYSE:../private','NYSE:AAPL#cash=100']:
   with self.subTest(listing=listing),self.assertRaises(ValueError):market_urls({'id':listing})
 def test_live_news_is_bound_reported_and_dated(self):
  r=InstrumentResolver([row('AAPL',ids={'listing_id':'NASDAQ:AAPL'})]);r.resolve('AAPL')
  response={'news':[{'title':'Apple major AI contract','link':'https://example.com/article','publisher':'Example',
   'providerPublishTime':int(datetime.fromisoformat(NOW).timestamp()),'relatedTickers':['AAPL']},
   {'title':'Unrelated news','link':'https://example.com/other','providerPublishTime':1,'relatedTickers':['MSFT']}]}
  b=LiveNewsBackend(r,lambda *a:json.dumps(response).encode());out=b(WebResearchIntent.LATEST_RELEVANT_NEWS,'AAPL recent material events',NOW)
  self.assertEqual(len(out.hits),1);h=out.hits[0];self.assertEqual(h.official_confirmation_status,'NEWS_REPORTED')
  self.assertFalse(h.metadata['article_content_verified']);self.assertFalse(h.metadata['calculation_input_approved']);self.assertFalse(h.metadata['material_event']);self.assertTrue(h.metadata['potential_material_event'])

class GenericPipelineTests(unittest.TestCase):
 def setup_run(self,root,mode,hold=True):
  manager=PersonalDatabaseManager(root/'personal.db',backup_directory=root/'backups');self.assertEqual(manager.initialize().status.value,'VALID')
  ledger=PersonalLedgerService(manager);ledger.register_account('CMA',name='Synthetic',currency='USD',timezone_name='UTC')
  at=datetime(2026,10,1,8,tzinfo=timezone.utc)
  ledger.register_instrument('AAPL',canonical_name='Apple',currency='USD',identifiers={'exchange':'NASDAQ','ticker':'AAPL'})
  if hold:
   ledger.post(TransactionIntent(TransactionType.INITIAL_POSITION,account_id='CMA',instrument_id='AAPL',quantity='3',total_cost='500',currency='USD',unit='SHARE',cost_basis_status=CostBasisStatus.USER_PROVIDED,occurred_at=at,timezone='UTC',confirmation_state=ConfirmationState.CONFIRMED,idempotency_key='apple'))
  ledger.create_portfolio_snapshot(snapshot_id='synthetic',snapshot_type='BOOK_ONLY',as_of=at,data={})
  run=RunDatabaseManager(root/'runs',mode);self.assertTrue(run.create().valid)
  run.initialize_run_context(request_mode=mode,analysis_as_of=NOW,analysis_timezone='UTC',state_version=ledger.get_current_state_version(),personal_db_instance_id=manager.instance_id,portfolio_snapshot_id='synthetic',portfolio_data_as_of=at.isoformat())
  return ledger,run
 def test_new_holding_runs_quote_and_deep_without_runtime_changes(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);ledger,run=self.setup_run(root,'PERSONAL_PORTFOLIO_ANALYSIS');before=hashlib.sha256(ledger.manager.database_path.read_bytes()).hexdigest()
   def transport(url,*a):
    if '/AAPL?' in url:return payload()
    raise OSError('other sources deliberately absent')
   services=compose_configured_host(run,ledger,transport=transport,research_all_held=True)
   result=execute_mode(ModeRequest(run.run_id,RequestMode.PERSONAL_PORTFOLIO_ANALYSIS,{'portfolio_source':'pinned_ledger','evaluation_currency':'USD'}),services)
   self.assertFalse(any(s.availability.value=='FAILED' for s in result.step_states));self.assertEqual(len(result.step_states),7)
   with closing(sqlite3.connect(run.database_path)) as c, c:
    self.assertGreater(c.execute("select count(*) from evidence where instrument_id='AAPL' and metric='current_price' and selection_state='SELECTED'").fetchone()[0],0)
    self.assertGreater(c.execute("select count(*) from task_states where task_name='deep_research:AAPL'").fetchone()[0],0)
   self.assertNotIn('AAPL:unsupported_asset_framework',result.missing_inputs)
   self.assertEqual(hashlib.sha256(ledger.manager.database_path.read_bytes()).hexdigest(),before)
 def test_unheld_single_asset_and_comparison_share_resolver(self):
  for mode,assets in [('SINGLE_ASSET_ANALYSIS',[{'instrument_id':'UNHELD','listing_id':'NASDAQ:MSFT','currency':'USD','asset_class':'EQUITY'}]),
                       ('ASSET_COMPARISON',[{'instrument_id':'AAPL'},{'instrument_id':'UNHELD','listing_id':'NASDAQ:MSFT','currency':'USD','asset_class':'EQUITY'}])]:
   with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp:
    ledger,run=self.setup_run(Path(tmp),mode,False)
    def transport(url,*a):
     if '/AAPL?' in url:return payload()
     if '/MSFT?' in url:return payload('MSFT')
     raise OSError('other sources absent')
    services=compose_configured_host(run,ledger,transport=transport)
    result=execute_mode(ModeRequest(run.run_id,RequestMode(mode),{'assets':assets}),services)
    self.assertEqual(result.step_states[0].availability.value,'COMPLETE')
    self.assertFalse(any(s.availability.value in {'FAILED','UNSUPPORTED'} for s in result.step_states))
    with closing(sqlite3.connect(run.database_path)) as c, c:self.assertGreater(c.execute("select count(*) from task_states where task_name='deep_research:UNHELD'").fetchone()[0],0)
 def test_offline_capture_never_calls_network_for_missing_data(self):
  from investment_stack.providers.capture import CapturedMarketTransport
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'manifest.json').write_text(json.dumps({'schema_version':1,'records':[]}))
   calls=[];transport=CapturedMarketTransport(root,fallback=lambda *a:calls.append(a),allow_live_fallback=False)
   with self.assertRaisesRegex(ValueError,'offline'):transport('https://example.com/private',{},1)
   self.assertEqual(calls,[])
 def test_sibling_legacy_registry_without_database_rewrite(self):
  with tempfile.TemporaryDirectory() as tmp:
   ledger,run=self.setup_run(Path(tmp),'PERSONAL_PORTFOLIO_ANALYSIS',False)
   with closing(sqlite3.connect(ledger.manager.database_path)) as c, c:c.execute("update instruments set identifiers_json=NULL where instrument_id='AAPL'")
   before=hashlib.sha256(ledger.manager.database_path.read_bytes()).hexdigest()
   (Path(tmp)/'instrument-registry.json').write_text(json.dumps({'schema_version':1,'instruments':{'AAPL':{'listing_id':'NASDAQ:AAPL'}}}))
   resolver=InstrumentResolver.from_database(ledger.manager.database_path)
   self.assertEqual(resolver.resolve('AAPL').listing_id,'NASDAQ:AAPL')
   self.assertEqual(hashlib.sha256(ledger.manager.database_path.read_bytes()).hexdigest(),before)
 def test_registration_rejects_identity_conflict_before_write(self):
  with tempfile.TemporaryDirectory() as tmp:
   manager=PersonalDatabaseManager(Path(tmp)/'personal.db');manager.initialize();ledger=PersonalLedgerService(manager)
   with self.assertRaises(ValueError):ledger.register_instrument('BAD',canonical_name='Bad',currency='JPY',identifiers={'listing_id':'NASDAQ:AAPL'})
   with closing(sqlite3.connect(manager.database_path)) as c, c:self.assertEqual(c.execute("select count(*) from instruments where instrument_id='BAD'").fetchone()[0],0)

if __name__=='__main__':unittest.main()
