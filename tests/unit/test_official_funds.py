import copy
import json
import unittest
from urllib.parse import parse_qs,urlparse
from investment_stack.providers.official_funds import OfficialFundAdapter
from investment_stack.providers.factory import build_default_provider_executor
from investment_stack.providers.models import ProviderRequest,ProviderStatus
from investment_stack.providers.registry import ProviderCapability


class OfficialFundTests(unittest.TestCase):
    def setUp(self):
        self.calls=[]
        self.directory=[{'stkTicker':'123ABC','fId':'ANYFUND'}]
        self.detail={'info':{'stkCd':'EXPLICITISIN','product':{'fId':'ANYFUND','stkTicker':'123ABC','gijunYMD':'20261002','nav':'5','bosuInfo':'0.25% (other components)','bmIdx':'Test Index','fNm':'Test Fund'}},
                     'suik':{'standardList':[{'EVAL_D':'20261006','F_P':'99'},{'EVAL_D':'20261002','F_P':'101.25'}]},
                     'pdf':{'gijunYMD':'20261006','list':[{'itmNo':'WRONG US Equity','ratio':'100'}]}}
        self.pdf={'pdf':{'gijunYMD':'20261002','totalCnt':3,'list':[{'itmNo':'CASH00000001','ratio':None},{'itmNo':'FIRST US Equity','ratio':'60.25','secNm':'First'},{'itmNo':'SECOND US Equity','ratio':'39.5','secNm':'Second'}]}}
        self.request=ProviderRequest(ProviderCapability.FUND_HOLDINGS,'2026-10-05T12:00:00+09:00','Asia/Seoul','portfolio_alias','fund_structure')
        parent=self
        class Transport:
            def __call__(self,url,headers,timeout):
                parent.calls.append(url)
                if '/product.do?' in url:return json.dumps(parent.directory).encode()
                if '/product-pdf/' in url:return json.dumps(parent.pdf).encode()
                return json.dumps(parent.detail).encode()
            def retrieved_at_for(self,url): return '2026-10-05T12:01:00+09:00'
        self.transport=Transport()
        self.adapter=OfficialFundAdapter(self.transport,listings={'portfolio_alias':'KRX:123ABC'})

    def test_exact_dynamic_directory_nav_and_dated_holdings_are_collected(self):
        result=self.adapter.fetch(self.request)
        self.assertEqual(result.status,ProviderStatus.PARTIAL)
        obs=result.observations[0];md=obs.metadata
        self.assertEqual(md['nav_per_share'],'101.25')
        self.assertEqual(md['aum'],'500000000')
        self.assertEqual(md['expense_ratio'],'0.0025')
        self.assertEqual(md['holdings'][0]['weight'],'0.6025')
        self.assertEqual(md['holdings'][0]['instrument_id'],'US:FIRST')
        self.assertIsNone(md['holdings'][0]['country'])
        self.assertEqual(md['holdings_coverage'],'0.9975')
        self.assertEqual(obs.observed_at,'2026-10-02T23:59:59+09:00')
        self.assertEqual(obs.retrieved_at,'2026-10-05T12:01:00+09:00')
        self.assertEqual(obs.instrument_id,'portfolio_alias')
        self.assertEqual(parse_qs(urlparse(self.calls[0]).query)['srchVal'],['123ABC'])
        self.assertIn('gijunYMD=2026.10.02',self.calls[-1])

    def test_directory_and_detail_share_class_mismatch_is_rejected(self):
        self.detail['info']['product']['stkTicker']='999999'
        result=self.adapter.fetch(self.request)
        self.assertFalse(result.observations)
        self.assertIn('identity mismatch',result.reason)

    def test_ambiguous_directory_listing_is_not_guessed(self):
        self.directory.append({'stkTicker':'123ABC','fId':'DIFFERENT'})
        self.assertFalse(self.adapter.fetch(self.request).observations)
        self.assertEqual(len(self.calls),1)

    def test_future_holdings_are_never_relabelled_to_analysis_date(self):
        self.pdf['pdf']['gijunYMD']='20261006'
        result=self.adapter.fetch(self.request)
        md=result.observations[0].metadata
        self.assertEqual(md['holdings'],[])
        self.assertIsNone(md['holdings_as_of'])
        self.assertIn('dated_holdings',md['missing_inputs'])
        self.assertEqual(md['nav_as_of'],'2026-10-02')

    def test_undated_holdings_and_nav_produce_visible_unavailable(self):
        self.detail['suik']['standardList']=[]
        self.pdf['pdf']['gijunYMD']=None
        result=self.adapter.fetch(self.request)
        self.assertEqual(result.status,ProviderStatus.UNAVAILABLE)
        self.assertIn('dated official',result.reason)

    def test_date_only_data_does_not_claim_intraday_publication(self):
        request=ProviderRequest(ProviderCapability.FUND_HOLDINGS,'2026-10-02T12:00:00+09:00','Asia/Seoul','portfolio_alias','fund_structure')
        result=self.adapter.fetch(request)
        self.assertFalse(result.observations)

    def test_invalid_holdings_are_withheld_while_independent_nav_is_preserved(self):
        for ratio in ('-1','101'):
            self.pdf['pdf']['list'][1]['ratio']=ratio
            result=self.adapter.fetch(self.request)
            self.assertEqual(result.status,ProviderStatus.PARTIAL)
            md=result.observations[0].metadata
            self.assertEqual(md['holdings'],[])
            self.assertEqual(md['nav_per_share'],'101.25')
            self.assertTrue(md['raw_holdings'])
            self.assertIn('weight',md['rounding_issue'])

    def test_rounded_coverage_excess_is_recorded_and_never_rescaled(self):
        self.pdf['pdf']['list'][1]['ratio']='60.51'
        md=self.adapter.fetch(self.request).observations[0].metadata
        self.assertEqual(md['holdings'],[])
        self.assertEqual(md['raw_holdings'][0]['weight'],'0.6051')
        self.assertEqual(md['reported_holdings_coverage'],'1.0001')
        self.assertEqual(md['holdings_calculation_status'],'WITHHELD')

    def test_network_error_is_safe_and_fallback_visible(self):
        from investment_stack.providers.http import ProviderTransportError
        def failed(url,headers,timeout):raise ProviderTransportError('public endpoint unavailable')
        result=OfficialFundAdapter(failed).fetch(ProviderRequest(ProviderCapability.FUND_HOLDINGS,self.request.analysis_as_of,'Asia/Seoul','KRX:123ABC'))
        self.assertEqual(result.status,ProviderStatus.ERROR)
        self.assertFalse(result.observations)

    def test_factory_registers_official_fund_capability_with_mapping(self):
        executor=build_default_provider_executor(transport=self.transport,listings={'portfolio_alias':'KRX:123ABC'})
        result=executor.execute(self.request)
        self.assertEqual(result.selected.provider,'official_funds')
        self.assertEqual(result.selected.observations[0].metadata['listing_id'],'KRX:123ABC')

    def test_configured_arbitrary_issuer_schema_preserves_identity_and_dates(self):
        payload={'listing_id':'OTHER:ABC','metadata':{'nav_per_share':'10','nav_currency':'USD','nav_as_of':'2026-10-02','holdings_as_of':'2026-10-02','holdings':[{'instrument_id':'US:XYZ','weight':'0.4','sector':None,'country':None,'currency':None}]}}
        adapter=OfficialFundAdapter(lambda u,h,t:json.dumps(payload).encode(),source_manifests={'OTHER:ABC':{'url':'https://issuer.example/funds/ABC.json','official_domain':'issuer.example'}})
        result=adapter.fetch(ProviderRequest(ProviderCapability.FUND_HOLDINGS,self.request.analysis_as_of,'Asia/Seoul','OTHER:ABC'))
        self.assertEqual(result.observations[0].metadata['holdings'][0]['weight'],'0.4')
        payload['listing_id']='OTHER:DIFFERENT'
        self.assertFalse(adapter.fetch(ProviderRequest(ProviderCapability.FUND_HOLDINGS,self.request.analysis_as_of,'Asia/Seoul','OTHER:ABC')).observations)

    def test_configured_source_domain_mismatch_does_not_fetch(self):
        called=[]
        adapter=OfficialFundAdapter(lambda u,h,t:called.append(u),source_manifests={'OTHER:ABC':{'url':'https://unapproved.example/data','official_domain':'issuer.example'}})
        result=adapter.fetch(ProviderRequest(ProviderCapability.FUND_HOLDINGS,self.request.analysis_as_of,'Asia/Seoul','OTHER:ABC'))
        self.assertFalse(result.observations)
        self.assertFalse(called)

    def tiger_fixture(self):
        self.tiger_rows=[{'ksdFund':'KR7123ABC001','wkdate':'20261002','code':'US1234567890','stockRate':'60.25','memItemnameEng':'First'},
                         {'ksdFund':'KR7123ABC001','wkdate':'20261002','code':'US0987654321','stockRate':'39.5','memItemnameEng':'Second'}]
        self.tiger_detail='<input name="ksdFund" value="KR7123ABC001"><input name="jongCode" value="123ABC"><div class="amount">999999 intraday NAV</div>'
        self.tiger_price='<caption>\uae30\uc900\uac00\uaca9</caption><tr><td>2026.10.02</td><td>102.5</td><td>1%</td><td>101.25</td><td>1%</td><td>999 tax NAV</td></tr>'
        parent=self
        class TigerTransport:
            def __call__(self,url,headers,timeout):
                parent.calls.append(url)
                if 'samsungfund' in url:
                    if getattr(parent,'fail_samsung',False):
                        from investment_stack.providers.http import ProviderTransportError
                        raise ProviderTransportError('Samsung unavailable')
                    return b'[]'
                if '/search/list.ajax' in url:return b'<div data-ksd-fund="KR7123ABC001"><div class="code">(123ABC)</div></div>'
                if '/detail/index.do' in url:return parent.tiger_detail.encode()
                if '/detail/price.ajax' in url:return parent.tiger_price.encode()
                return json.dumps({'rtnData':parent.tiger_rows}).encode()
            def retrieved_at_for(self,url):return '2026-10-05T12:01:00+09:00'
        return OfficialFundAdapter(TigerTransport(),listings={'portfolio_alias':'KRX:123ABC'})

    def test_tiger_fallback_uses_exact_directory_and_dated_nav_not_intraday_or_tax(self):
        md=self.tiger_fixture().fetch(self.request).observations[0].metadata
        self.assertEqual(md['issuer'],'Mirae Asset TIGER')
        self.assertEqual(md['nav_per_share'],'101.25')
        self.assertEqual(md['official_market_close'],'102.5')
        self.assertEqual(md['holdings_as_of'],'2026-10-02')
        self.assertEqual(md['holdings_coverage'],'0.9975')
        self.assertEqual(md['holdings'][0]['instrument_id'],'ISIN:US1234567890')
        self.assertIsNone(md['holdings'][0]['country'])
        self.assertIn('fixDate=20261002',self.calls[-1])
        self.assertNotIn('/tigeretf/',self.calls[-1])

    def test_tiger_stock_json_cross_fund_identity_is_rejected(self):
        adapter=self.tiger_fixture();self.tiger_rows[0]['ksdFund']='KR7000000001'
        result=adapter.fetch(self.request)
        self.assertFalse(result.observations)
        self.assertIn('fund identity mismatch',result.reason)

    def test_tiger_future_holdings_are_withheld_without_losing_nav(self):
        adapter=self.tiger_fixture()
        for row in self.tiger_rows:row['wkdate']='20261006'
        result=adapter.fetch(self.request)
        md=result.observations[0].metadata
        self.assertEqual(md['holdings'],[])
        self.assertEqual(md['nav_per_share'],'101.25')
        self.assertIn('holding date absent/future',md['rounding_issue'])

    def test_tiger_share_class_detail_mismatch_is_rejected(self):
        adapter=self.tiger_fixture()
        self.tiger_detail=self.tiger_detail.replace('123ABC','999999')
        result=adapter.fetch(self.request)
        self.assertFalse(result.observations)
        self.assertIn('share class mismatch',result.reason)

    def test_tiger_rounded_excess_preserves_raw_weights(self):
        adapter=self.tiger_fixture();self.tiger_rows[0]['stockRate']='60.51'
        md=adapter.fetch(self.request).observations[0].metadata
        self.assertEqual(md['holdings'],[])
        self.assertEqual(md['raw_holdings'][0]['weight'],'0.6051')
        self.assertEqual(md['reported_holdings_coverage'],'1.0001')
        self.assertEqual(md['holdings_calculation_status'],'WITHHELD')

    def test_tiger_mixed_dates_do_not_become_one_invented_as_of(self):
        adapter=self.tiger_fixture();self.tiger_rows[0]['wkdate']='20261001'
        md=adapter.fetch(self.request).observations[0].metadata
        self.assertEqual(md['holdings'],[])
        self.assertIsNone(md['holdings_as_of'])
        self.assertIn('mixed holdings dates',md['rounding_issue'])

    def test_samsung_outage_does_not_block_tiger_official_data(self):
        adapter=self.tiger_fixture();self.fail_samsung=True
        result=adapter.fetch(self.request)
        self.assertEqual(result.observations[0].metadata['issuer'],'Mirae Asset TIGER')
        self.assertEqual(result.observations[0].metadata['nav_per_share'],'101.25')

