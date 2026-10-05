from contextlib import closing
"""Regression coverage for real payload shapes, distinct data times and provenance."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from investment_stack.providers.capture import capture_market_data, CapturedMarketTransport
from investment_stack.providers.factory import build_default_provider_executor
from investment_stack.providers.market_quotes import parse_yahoo_quote, parse_naver_basic_quote
from investment_stack.providers.models import ProviderRequest
from investment_stack.providers.registry import ProviderCapability
from investment_stack.web_research import WebResearchAdapter, WebResearchBundleBackend
from investment_stack.evidence import RunDatabaseManager, EvidenceResearchStore
import sqlite3
from types import SimpleNamespace
from decimal import Decimal
from investment_stack.execution.portfolio_evidence import PortfolioEvidence
from investment_stack.materiality import MaterialityEngine, MaterialityConfig

NOW = datetime(2026, 10, 1, 11, tzinfo=timezone.utc)
TRADE = datetime(2026, 9, 30, 20, 4, 47, tzinfo=timezone.utc)

def daily_payload(price="137.3", close="137.3000030517578", stamp=TRADE):
    return {"chart": {"result": [{"meta": {
        "symbol": "ORCL", "currency": "USD", "exchangeName": "NYQ",
        "exchangeTimezoneName": "America/New_York", "dataGranularity": "1d",
        "regularMarketPrice": price, "regularMarketTime": int(stamp.timestamp())},
        "timestamp": [int(datetime(2026, 9, 30, 13, 30, tzinfo=timezone.utc).timestamp())],
        "indicators": {"quote": [{"close": [close]}]}}]}}

class CompletedCloseTests(unittest.TestCase):
    def test_completed_daily_close_preserves_provider_and_publication_time(self):
        parsed = parse_yahoo_quote(daily_payload(), instrument_id="NYSE:ORCL", retrieved_at=NOW)
        self.assertTrue(parsed.is_usable)
        obs = parsed.observation
        self.assertEqual(obs.observed_at, "2026-09-30T16:00:00-04:00")
        self.assertEqual(obs.published_at, "2026-09-30T16:04:47-04:00")
        self.assertEqual(obs.metadata["original_provider_timestamp"], obs.published_at)
        self.assertEqual(obs.metadata["quote_kind"], "LAST_VALID_CLOSE")

    def test_candle_price_disagreement_cannot_change_timestamp(self):
        parsed = parse_yahoo_quote(daily_payload(close="130"), instrument_id="NYSE:ORCL", retrieved_at=NOW)
        self.assertEqual(parsed.observation.observed_at, "2026-09-30T16:04:47-04:00")
        self.assertIsNone(parsed.observation.metadata["timestamp_derivation"])

    def test_intraday_bar_cannot_be_promoted_to_close(self):
        data = daily_payload(); data["chart"]["result"][0]["meta"]["dataGranularity"] = "1m"
        parsed = parse_yahoo_quote(data, instrument_id="NYSE:ORCL", retrieved_at=NOW)
        self.assertEqual(parsed.observation.metadata["quote_kind"], "REGULAR")

    def test_daily_close_before_session_end_is_not_complete(self):
        parsed = parse_yahoo_quote(daily_payload(stamp=datetime(2026,9,30,19,59,tzinfo=timezone.utc)), instrument_id="NYSE:ORCL", retrieved_at=NOW)
        self.assertEqual(parsed.observation.metadata["quote_kind"], "REGULAR")

    def test_nyq_alias_survives_all_provider_selection_layers(self):
        transport = lambda u,h,t: json.dumps(daily_payload()).encode()
        executor = build_default_provider_executor(transport=transport,listings={"ORCL":"NYSE:ORCL"})
        selected = executor.execute(ProviderRequest(ProviderCapability.CURRENT_PRICE,NOW.isoformat(),"UTC","ORCL")).selected
        self.assertIsNotNone(selected)
        self.assertEqual(selected.observations[0].metadata["quote_listing_id"],"NYSE:ORCL")

    def test_stale_daily_close_cannot_pass_today_session(self):
        data = daily_payload(stamp=datetime(2026,9,29,20,0,3,tzinfo=timezone.utc))
        data["chart"]["result"][0]["timestamp"]=[int(datetime(2026,9,29,13,30,tzinfo=timezone.utc).timestamp())]
        executor = build_default_provider_executor(transport=lambda u,h,t:json.dumps(data).encode(),listings={"ORCL":"NYSE:ORCL"})
        self.assertIsNone(executor.execute(ProviderRequest(ProviderCapability.CURRENT_PRICE,NOW.isoformat(),"UTC","ORCL")).selected)

    def test_boolean_and_fractional_epoch_are_invalid(self):
        for stamp in (True,1790798687.5):
            data=daily_payload();data["chart"]["result"][0]["meta"]["regularMarketTime"]=stamp
            self.assertFalse(parse_yahoo_quote(data,instrument_id="NYSE:ORCL",retrieved_at=NOW).is_usable)

    def test_closed_naver_regular_etf_uses_dated_close_with_raw_update(self):
        data={"itemCode":"379810","stockExchangeType":{"code":"KS","endTime":"1530","closePriceSendTime":"1630","delayTime":0},
            "closePrice":"27755","localTradedAt":"2026-10-01T19:20:00+09:00","marketStatus":"CLOSE","marketSessionType":"regularMarket"}
        obs=parse_naver_basic_quote(data,instrument_id="KRX:379810",retrieved_at=NOW).observation
        self.assertEqual(obs.observed_at,"2026-10-01T15:30:00+09:00")
        self.assertEqual(obs.metadata["original_provider_timestamp"],data["localTradedAt"])
        self.assertEqual(obs.official_confirmation_status,"PROVIDER_REPORTED")

class CaptureAndSearchTests(unittest.TestCase):
    def test_material_event_drives_gate_without_hardcoded_symbol_or_user_override(self):
        live=PortfolioEvidence.__new__(PortfolioEvidence)
        live.quantities={'ORCL':Decimal('1')};live.instruments={'ORCL':{'asset_class':'EQUITY'}}
        live.research_all_held=False;live.events={}
        decisions=[]
        live.analysis=SimpleNamespace(materiality=MaterialityEngine(MaterialityConfig('test',Decimal('1'),Decimal('1'),Decimal('1'))),_persist_materiality=decisions.append)
        portfolio=SimpleNamespace(positions=(SimpleNamespace(instrument_id='ORCL',market_value=Decimal('100')),))
        self.assertEqual(live.select(portfolio,None),())
        live.events={'ORCL':(object(),)}
        self.assertEqual(live.select(portfolio,None),('ORCL',))
        self.assertEqual(decisions[-1].decision.value,'PASS')
        self.assertIn('strategic relevance',decisions[-1].reasons)

    def test_http_html_is_unavailable_not_captured_market_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest=capture_market_data(tmp,transport=lambda u,h,t:b'<html>Site Unavailable</html>')
            self.assertTrue(all(r["status"]=="UNAVAILABLE" for r in manifest["records"]))
            self.assertTrue(all(r["reason"]=="INVALID_JSON_RESPONSE" for r in manifest["records"]))

    def test_capture_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest=capture_market_data(tmp,transport=lambda u,h,t:b'{}')
            record=manifest['records'][0];(Path(tmp)/record['file']).write_text('{"changed":true}')
            with self.assertRaisesRegex(ValueError,'hash mismatch'):
                CapturedMarketTransport(tmp)(record['url'],{},10)

    def test_web_bundle_preserves_actual_search_time(self):
        hit={"source_name":"Reuters","source_url":"https://www.reuters.com/test","title":"Reported event",
            "published_at":"2026-10-01T03:12:00+00:00","retrieved_at":"2026-10-01T10:30:00+00:00",
            "source_kind":"news_article","source_tier":2,"official_confirmation_status":"CONFIRMED"}
        adapter=WebResearchAdapter(WebResearchBundleBackend({"responses":[{"intent":"LATEST_RELEVANT_NEWS","query":"event","hits":[hit]}]}))
        obs=adapter.fetch_news('event',analysis_as_of=NOW.isoformat()).observations[0]
        self.assertEqual(obs.retrieved_at,hit['retrieved_at'])
        self.assertEqual(obs.official_confirmation_status,'NEWS_REPORTED')

    def test_undated_fund_source_is_persisted_without_selection_or_data_time(self):
        hit={'source_name':'Fund source','source_url':'https://m.stock.naver.com/test',
            'title':'Fund structure','retrieved_at':NOW.isoformat(),
            'metadata':{'benchmark':'INDEX','expense_ratio':'0.001'}}
        adapter=WebResearchAdapter(WebResearchBundleBackend({'responses':[{'intent':'LATEST_CURRENT_DATA','query':'fund','hits':[hit]}]}))
        result=adapter.fetch_latest_data('fund',capability=ProviderCapability.FUND_HOLDINGS,
            analysis_as_of=NOW.isoformat(),instrument_id='FUND',metric='fund_structure')
        with tempfile.TemporaryDirectory() as tmp:
            run=RunDatabaseManager(Path(tmp),'undated');self.assertTrue(run.create().valid)
            selected=EvidenceResearchStore(run).persist_and_select((result,),analysis_as_of=NOW.isoformat())
            self.assertIsNone(selected.observation)
            with closing(sqlite3.connect(run.database_path)) as c, c:
                row=c.execute('select observed_at,published_at,retrieved_at,selection_state,metadata_json from evidence').fetchone()
            self.assertIsNone(row[0]);self.assertIsNone(row[1]);self.assertEqual(row[2],NOW.isoformat())
            self.assertNotEqual(row[3],'SELECTED');self.assertFalse(json.loads(row[4])['calculation_input_approved'])

if __name__ == '__main__': unittest.main()
