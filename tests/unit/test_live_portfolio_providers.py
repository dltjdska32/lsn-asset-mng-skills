from __future__ import annotations
import json, unittest, tempfile, sqlite3
from datetime import datetime,timezone
from decimal import Decimal
from pathlib import Path
from dataclasses import replace
from contextlib import closing
from investment_stack.providers.fx import parse_fx,cross_fx,FXProvider
from investment_stack.providers.models import ProviderRequest,ProviderStatus
from investment_stack.providers import ProviderCapability
from investment_stack.providers.factory import build_default_provider_executor
from investment_stack.providers.market_quotes import MarketQuoteProvider, calendar_aware_freshness_evaluator
from investment_stack.freshness import get_pinned_calendar
from investment_stack.providers.execution import assess_current_price_observation
from investment_stack.web_research import WebResearchAdapter,WebResearchBundleBackend
from investment_stack.execution.alternative_evidence import external_crypto
from investment_stack.evidence import RunDatabaseManager,EvidenceResearchStore

NOW='2026-10-01T11:00:00+00:00'
def fx_payload(pair,price='1360',stamp=NOW):
 symbol,ccy={'USD/KRW':('KRW=X','KRW'),'JPY/KRW':('JPYKRW=X','KRW'),'USD/JPY':('JPY=X','JPY')}[pair]
 return {'chart':{'result':[{'meta':{'symbol':symbol,'currency':ccy,'instrumentType':'CURRENCY','regularMarketPrice':price,'regularMarketTime':int(datetime.fromisoformat(stamp).timestamp())}}]}}
def fx(pair,price,stamp=NOW):return parse_fx(fx_payload(pair,price,stamp),pair,analysis_as_of=NOW,retrieved_at=NOW,source_url='https://query1.finance.yahoo.com/test')
def quote_payload(symbol='6954.T',delay=None,stamp='2026-10-01T06:30:00+00:00'):
 md={'symbol':symbol,'currency':'JPY','exchangeName':'JPX','exchangeTimezoneName':'Asia/Tokyo','regularMarketTime':int(datetime.fromisoformat(stamp).timestamp()),'regularMarketPrice':'6000'}
 if delay is not None:md['exchangeDataDelayedBy']=delay
 return json.dumps({'chart':{'result':[{'meta':md}]}}).encode()

class FXTests(unittest.TestCase):
 def test_direct_pair_and_time_metadata(self):
  o=fx('JPY/KRW','8.6');self.assertEqual(o.value,Decimal('8.6'));self.assertEqual(o.unit,'JPY/KRW');self.assertEqual(o.metadata['rate_type'],'direct');self.assertEqual(o.retrieved_at,NOW)
 def test_cross_formula_and_provenance(self):
  o=cross_fx(fx('USD/KRW','1360'),fx('JPY/KRW','8.5'),fx('USD/JPY','160'));self.assertEqual(o.value,Decimal('160'));self.assertEqual(o.metadata['rate_type'],'cross');self.assertIsNone(o.source_url)
 def test_cross_rejects_conflicting_direct(self):
  with self.assertRaisesRegex(ValueError,'sanity'):cross_fx(fx('USD/KRW','1360'),fx('JPY/KRW','8.5'),fx('USD/JPY','140'))
 def test_cross_rejects_skew(self):
  with self.assertRaisesRegex(ValueError,'timestamps'):cross_fx(fx('USD/KRW','1360'),fx('JPY/KRW','8.5','2026-10-01T10:50:00+00:00'))
 def test_stale_fx_rejected(self):
  with self.assertRaisesRegex(ValueError,'stale'):fx('USD/KRW','1360','2026-10-01T10:44:00+00:00')
 def test_future_fx_rejected(self):
  with self.assertRaisesRegex(ValueError,'future'):fx('USD/KRW','1360','2026-10-01T11:00:01+00:00')
 def test_invalid_values_rejected(self):
  for value in ['0','-1','NaN','Infinity',True,1.2]:
   with self.subTest(value=value),self.assertRaises(ValueError):fx('USD/KRW',value)
 def test_wrong_identity_rejected(self):
  d=fx_payload('USD/KRW');d['chart']['result'][0]['meta']['symbol']='JPY=X'
  with self.assertRaisesRegex(ValueError,'identity'):parse_fx(d,'USD/KRW',analysis_as_of=NOW,retrieved_at=NOW,source_url='u')
 def test_fallback_records_failed_primary(self):
  calls=[]
  def transport(url,headers,timeout):
   calls.append(url)
   if 'query1' in url:raise OSError('offline')
   return json.dumps(fx_payload('USD/KRW')).encode()
  p=FXProvider(transport,clock=lambda:datetime.fromisoformat(NOW));r=p.fetch(ProviderRequest(ProviderCapability.FX,NOW,'UTC','USD/KRW'))
  self.assertEqual(r.status,ProviderStatus.AVAILABLE);self.assertEqual(len(calls),2);self.assertEqual(len(r.metadata['attempts']),1)

class QuoteTests(unittest.TestCase):
 def test_japan_listing_calendar_and_canonical_bridge(self):
  executor=build_default_provider_executor(transport=lambda u,h,t:quote_payload(),listings={'FANUC_6954':'JPX:6954'})
  r=executor.execute(ProviderRequest(ProviderCapability.CURRENT_PRICE,NOW,'UTC','FANUC_6954'))
  self.assertIsNotNone(r.selected);obs=r.selected.observations[0]
  self.assertEqual(obs.instrument_id,'FANUC_6954');self.assertEqual(obs.metadata['quote_listing_id'],'JPX:6954')
  self.assertEqual(assess_current_price_observation(obs,analysis_as_of=NOW).status.value,'LAST_VALID_CLOSE')
  self.assertNotEqual(obs.official_confirmation_status,'EXCHANGE_CONFIRMED')
 def test_delayed_quote_remains_rejected_with_metadata(self):
  p=MarketQuoteProvider(transport=lambda u,h,t:(200,quote_payload(delay=20),{}),clock=lambda:datetime.fromisoformat(NOW))
  result=p.fetch_current('JPX:6954',analysis_as_of=NOW,eligibility_evaluator=calendar_aware_freshness_evaluator(get_pinned_calendar('JPX')))
  self.assertEqual(result.status,ProviderStatus.UNAVAILABLE);self.assertEqual(result.observations[0].metadata['delay_minutes'],20);self.assertFalse(result.observations[0].metadata['calculation_input_approved'])
 def test_stale_close_rejected(self):
  p=MarketQuoteProvider(transport=lambda u,h,t:(200,quote_payload(stamp='2026-09-30T06:30:00+00:00'),{}))
  r=p.fetch_current('JPX:6954',analysis_as_of=NOW,eligibility_evaluator=calendar_aware_freshness_evaluator(get_pinned_calendar('JPX')))
  self.assertEqual(r.status,ProviderStatus.UNAVAILABLE)
 def test_secondary_preserves_exact_source(self):
  calls=[]
  def transport(u,h,t):
   calls.append(u)
   if 'query1' in u:return 503,b'',{}
   return 200,json.dumps({'chart':{'result':[{'meta':{'symbol':'ORCL','currency':'USD','exchangeName':'NYQ','exchangeTimezoneName':'America/New_York','regularMarketPrice':'100','regularMarketTime':int(datetime.fromisoformat('2026-09-30T20:00:00+00:00').timestamp())}}]}}).encode(),{}
  p=MarketQuoteProvider(transport=transport,enable_secondary=True)
  r=p.fetch_current('NYSE:ORCL',analysis_as_of=NOW,eligibility_evaluator=calendar_aware_freshness_evaluator(get_pinned_calendar('NYSE')))
  self.assertEqual(r.status,ProviderStatus.AVAILABLE);self.assertIn('query2',r.observations[0].source_url);self.assertEqual(len(calls),2)

class NewsAndAlternativeTests(unittest.TestCase):
 def backend(self,**overrides):
  hit={'source_name':'Reuters','source_url':'https://www.reuters.com/test','title':'reported contract','published_at':'2026-10-01T10:00:00+00:00','source_tier':2,'source_kind':'news_article','official_confirmation_status':'CONFIRMED'};hit.update(overrides)
  return WebResearchAdapter(WebResearchBundleBackend({'responses':[{'intent':'LATEST_RELEVANT_NEWS','query':'event','hits':[hit]}]}))
 def test_media_cannot_claim_official_confirmation(self):
  r=self.backend().fetch_news('event',analysis_as_of=NOW,instrument_id='ORCL');self.assertEqual(r.observations[0].official_confirmation_status,'NEWS_REPORTED')
 def test_old_event_does_not_hide_future_publication(self):
  r=self.backend(event_time='2026-09-30T10:00:00+00:00',published_at='2026-10-01T11:01:00+00:00').fetch_news('event',analysis_as_of=NOW);self.assertFalse(r.observations)
 def test_news_publication_and_retrieval_are_separate(self):
  obs=self.backend().fetch_news('event',analysis_as_of=NOW).observations[0];self.assertNotEqual(obs.published_at,obs.retrieved_at)
 def test_quote_from_web_is_never_verified(self):
  r=self.backend().fetch_current('event',analysis_as_of=NOW);self.assertEqual(r.status,ProviderStatus.UNAVAILABLE)
 def test_research_persisted_confirmation(self):
  with tempfile.TemporaryDirectory() as tmp:
   run=RunDatabaseManager(Path(tmp),'test');self.assertTrue(run.create().valid)
   result=self.backend().fetch_news('event',analysis_as_of=NOW,instrument_id='ORCL');selected=EvidenceResearchStore(run).persist_and_select((result,),analysis_as_of=NOW)
   self.assertIsNotNone(selected.evidence_id)
   with closing(sqlite3.connect(run.database_path)) as c:
    row=c.execute('select official_confirmation_status,published_at,retrieved_at from evidence').fetchone()
   self.assertEqual(row[0],'NEWS_REPORTED');self.assertNotEqual(row[1],row[2])
 def test_eth_explicit_external_identity_and_complete_history(self):
  d={'chart':{'result':[{'meta':{'symbol':'ETH-USD','currency':'USD','instrumentType':'CRYPTOCURRENCY','regularMarketPrice':'2700','regularMarketTime':int(datetime.fromisoformat(NOW).timestamp())},'timestamp':[int(datetime.fromisoformat('2026-09-30T00:00:00+00:00').timestamp()),int(datetime.fromisoformat('2026-10-01T00:00:00+00:00').timestamp())],'indicators':{'quote':[{'close':['2600','2700']}]}}]}}
  obs,history=external_crypto(d,'ETH',cutoff=NOW,retrieved=NOW,url='https://query1.finance.yahoo.com/test');self.assertFalse(obs.metadata['native_support']);self.assertEqual(len(history),1);self.assertTrue(history[0].metadata['derived_interval_end'])
 def test_eth_wrong_currency_rejected(self):
  d={'chart':{'result':[{'meta':{'symbol':'ETH-USD','currency':'JPY','instrumentType':'CRYPTOCURRENCY'}}]}}
  with self.assertRaisesRegex(ValueError,'identity'):external_crypto(d,'ETH',cutoff=NOW,retrieved=NOW,url='x')

if __name__=='__main__':unittest.main()
