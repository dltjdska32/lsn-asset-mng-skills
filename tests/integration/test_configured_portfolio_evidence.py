from contextlib import closing
"""Synthetic regression for the configured fixed pipeline; no real personal DB."""
import unittest,tempfile,sqlite3,json,hashlib
from pathlib import Path
from datetime import datetime,timezone
from investment_stack.personal.manager import PersonalDatabaseManager
from investment_stack.personal.ledger import PersonalLedgerService
from investment_stack.personal.intent import TransactionIntent,TransactionType,ConfirmationState,CostBasisStatus
from investment_stack.evidence import RunDatabaseManager
from investment_stack.execution.host import compose_configured_host
from investment_stack.execution.models import ModeRequest
from investment_stack.execution.dispatcher import execute_mode
from investment_stack.routing import RequestMode

class ConfiguredPortfolioEvidenceTests(unittest.TestCase):
 def test_real_handlers_pin_discover_gate_deep_fund_and_preserve_personal(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);manager=PersonalDatabaseManager(root/'personal.db',backup_directory=root/'backups');self.assertEqual(manager.initialize().status.value,'VALID')
   ledger=PersonalLedgerService(manager);ledger.register_account('CMA',name='Test',currency='USD',timezone_name='UTC')
   at=datetime(2026,10,1,8,tzinfo=timezone.utc)
   for iid,cls,ccy in [('ORCL','EQUITY','USD'),('KODEX_US_NASDAQ100','FUND','KRW')]:
    ledger.register_instrument(iid,canonical_name=iid,currency=ccy,asset_class=cls,identifiers={"listing_id":"NYSE:ORCL" if cls=="EQUITY" else "KRX:379810"})
    outcome=ledger.post(TransactionIntent(TransactionType.INITIAL_POSITION,account_id='CMA',instrument_id=iid,quantity='2',total_cost='100',currency=ccy,unit='SHARE',cost_basis_status=CostBasisStatus.USER_PROVIDED,occurred_at=at,timezone='UTC',confirmation_state=ConfirmationState.CONFIRMED,idempotency_key=iid))
   for ccy in ['JPY','USD']:
    ledger.post(TransactionIntent(TransactionType.DEPOSIT,account_id='CMA',cash_amount='100',currency=ccy,occurred_at=at,timezone='UTC',confirmation_state=ConfirmationState.CONFIRMED,idempotency_key=ccy))
   ledger.create_portfolio_snapshot(snapshot_id='synthetic',snapshot_type='BOOK_ONLY',as_of=at,data={})
   before=hashlib.sha256(manager.database_path.read_bytes()).hexdigest();state=ledger.get_current_state_version()
   run=RunDatabaseManager(root/'workspace','test');self.assertTrue(run.create().valid)
   run.initialize_run_context(request_mode='PERSONAL_PORTFOLIO_ANALYSIS',analysis_as_of='2026-10-01T11:00:00+00:00',analysis_timezone='UTC',state_version=state,personal_db_instance_id=manager.instance_id,portfolio_snapshot_id='synthetic',portfolio_data_as_of=at.isoformat())
   bundle={'responses':[{'intent':'LATEST_RELEVANT_NEWS','query':'ORCL recent material events','hits':[{'source_name':'Reuters','source_url':'https://www.reuters.com/test','title':'Reported major contract','published_at':'2026-10-01T10:00:00+00:00','source_kind':'news_article','source_tier':2,'official_confirmation_status':'NEWS_REPORTED','metadata':{'material_event':True,'independent_verification':False}}]}]}
   path=root/'bundle.json';path.write_text(json.dumps(bundle))
   def offline(url,headers,timeout):raise OSError('synthetic offline')
   host=compose_configured_host(run,ledger,transport=offline,web_research_bundle=path)
   result=execute_mode(ModeRequest('test',RequestMode.PERSONAL_PORTFOLIO_ANALYSIS,{'portfolio_source':'pinned_ledger','evaluation_currency':'KRW'}),host)
   self.assertEqual(result.availability.value,'PARTIAL');self.assertEqual(len(result.step_states),7)
   self.assertEqual(result.step_states[0].availability.value,'COMPLETE');self.assertEqual(result.step_states[2].availability.value,'COMPLETE')
   pin=result.step_states[0].result.output['portfolio_request'];self.assertEqual(len(pin.positions),2)
   self.assertEqual({b.balance_id for b in pin.cash},{'CMA:JPY','CMA:USD'})
   self.assertTrue(any('fund_structure' in s or 'look_through' in s for s in result.missing_inputs))
   with closing(sqlite3.connect(run.database_path)) as c, c:
    c.row_factory=sqlite3.Row
    tasks=[dict(row) for row in c.execute('select * from task_states')]
    names={row['task_name'] for row in tasks}
    self.assertIn('recent_event_discovery:ORCL',names);self.assertIn('deep_research:ORCL',names)
    types={row[0] for row in c.execute('select calculation_name from calculations')};self.assertIn('FUND',types)
    confirmation=c.execute("select official_confirmation_status from evidence where evidence_type='news' limit 1").fetchone();self.assertEqual(confirmation[0],'NEWS_REPORTED')
   self.assertEqual(hashlib.sha256(manager.database_path.read_bytes()).hexdigest(),before)
   # Report references are actual run.db rows; renderer receives partial evidence.
   report=result.step_states[-1].result.output['report'];self.assertEqual(report.availability.value,'PARTIAL')
   self.assertIn('FUND',report.markdown)

if __name__=='__main__':unittest.main()
