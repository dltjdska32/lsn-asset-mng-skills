"""Dated official ETF structure collection; no ticker-specific fund mappings."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
import re
import html
from urllib.parse import quote, urlencode, urlparse
from zoneinfo import ZoneInfo
from investment_stack.providers.http import fetch_json, urllib_transport, ProviderTransportError
from investment_stack.providers.models import ProviderObservation, ProviderResult, ProviderStatus
from investment_stack.providers.registry import ProviderCapability


def _date(value):
    text=str(value or '').strip().replace('.','').replace('-','')
    if not re.fullmatch(r'\d{8}',text): return None
    try: return datetime.strptime(text,'%Y%m%d').date().isoformat()
    except ValueError: return None


def _decimal(value):
    if value is None or value=='': return None
    if isinstance(value,(bool,float)): raise ValueError('exact official decimal required')
    result=Decimal(str(value).replace(',',''))
    if not result.is_finite(): raise ValueError('nonfinite official data')
    return result


def _stamp(day):
    # Source has a date, not an intraday publication time. Use its upper bound.
    return day+'T23:59:59+09:00'


def _holding_id(raw):
    raw=str(raw or '').strip()
    match=re.fullmatch(r'([^ ]+) US Equity',raw,re.I)
    if match: return 'US:'+match.group(1)
    if re.fullmatch(r'KR7[0-9A-Z]{9}',raw): return 'ISIN:'+raw
    return 'ISSUER:'+raw


def _exact_json(value):
    if isinstance(value, Decimal): return str(value)
    if isinstance(value, dict): return {key:_exact_json(item) for key,item in value.items()}
    if isinstance(value, list): return [_exact_json(item) for item in value]
    return value


def _text(value):
    return html.unescape(re.sub(r'<[^>]+>','',value)).strip()


def _table_rows(value):
    return [[_text(cell) for cell in re.findall(r'<td\b[^>]*>(.*?)</td>',row,re.S|re.I)]
            for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>',value,re.S|re.I)]


class OfficialFundAdapter:
    name='official_funds'
    capabilities=frozenset({ProviderCapability.FUND_HOLDINGS})
    def __init__(self,transport=urllib_transport,*,listings=None,resolver=None,source_manifests=None,timeout=8):
        self.transport=transport;self.listings=dict(listings or {});self.resolver=resolver
        self.source_manifests=dict(source_manifests or {});self.timeout=timeout

    def _listing(self,iid):
        listing=self.listings.get(iid)
        if not listing and self.resolver is not None:
            listing=self.resolver.resolve(iid).listing_id
        return listing or iid

    def _fetch(self,url,sources):
        data=fetch_json(url,headers={'User-Agent':'Mozilla/5.0','Accept':'application/json'},timeout=self.timeout,transport=self.transport)
        captured=self.transport.retrieved_at_for(url) if hasattr(self.transport,'retrieved_at_for') else None
        retrieved=captured or datetime.now(timezone.utc).isoformat()
        if datetime.fromisoformat(retrieved.replace('Z','+00:00')).tzinfo is None:
            raise ValueError('retrieved_at must carry timezone')
        sources.append({'url':url,'retrieved_at':retrieved})
        return data

    def _fetch_text(self,url,sources):
        data=self.transport(url,{'User-Agent':'Mozilla/5.0','Accept':'text/html'},self.timeout).decode('utf-8')
        captured=self.transport.retrieved_at_for(url) if hasattr(self.transport,'retrieved_at_for') else None
        retrieved=captured or datetime.now(timezone.utc).isoformat()
        if datetime.fromisoformat(retrieved.replace('Z','+00:00')).tzinfo is None:
            raise ValueError('retrieved_at must carry timezone')
        sources.append({'url':url,'retrieved_at':retrieved})
        return data

    def fetch(self,request):
        if request.capability not in self.capabilities:
            return ProviderResult(self.name,request.capability,ProviderStatus.UNAVAILABLE,reason='capability unsupported')
        sources=[]
        try:
            listing=self._listing(request.instrument_id)
            cutoff=datetime.fromisoformat(request.analysis_as_of.replace('Z','+00:00'))
            if cutoff.tzinfo is None: raise ValueError('analysis_as_of must carry timezone')
            manifest=self.source_manifests.get(listing)
            if manifest is not None:
                return self._manifest(request,listing,manifest,cutoff,sources)
            if not re.fullmatch(r'KRX:[0-9A-Z]{6}',str(listing)):
                return ProviderResult(self.name,request.capability,ProviderStatus.UNAVAILABLE,reason='official issuer source unavailable for listing')
            try:
                result=self._samsung(request,listing,cutoff,sources)
            except ProviderTransportError as samsung_error:
                # A Samsung outage must not suppress another issuer's exact
                # directory match. The outer executor still bounds total time.
                try: return self._tiger(request,listing,cutoff,sources)
                except ProviderTransportError: raise samsung_error
            if not result.observations and result.reason=='exact Samsung issuer listing match unavailable':
                return self._tiger(request,listing,cutoff,sources)
            return result
        except ProviderTransportError as exc:
            return ProviderResult(self.name,request.capability,ProviderStatus.ERROR,reason=str(exc),metadata={'sources':sources})
        except (ValueError,TypeError,KeyError,InvalidOperation,UnicodeDecodeError) as exc:
            return ProviderResult(self.name,request.capability,ProviderStatus.UNAVAILABLE,reason='official fund validation failed: '+str(exc),metadata={'sources':sources})

    def _tiger(self,request,listing,cutoff,sources):
        """Resolve the issuer directory first; never derive or hardcode an ISIN."""
        base='https://www.tigeretf.com';ticker=listing.split(':',1)[1]
        directory_url=base+'/ko/product/search/list.ajax?'+urlencode({'q':ticker,'listType':'table','pageIndex':'1','listCnt':'20'})
        directory=self._fetch_text(directory_url,sources)
        blocks=list(re.finditer(r'data-ksd-fund=["\']([^"\']+)["\']',directory))
        matches=[]
        for index,match in enumerate(blocks):
            block=directory[match.end():blocks[index+1].start() if index+1<len(blocks) else len(directory)]
            if re.search(r'class=["\']code["\'][^>]*>\s*\('+re.escape(ticker)+r'\)',block): matches.append(match.group(1))
        if len(matches)!=1:
            return ProviderResult(self.name,request.capability,ProviderStatus.UNAVAILABLE,reason='exact official Samsung/TIGER issuer listing match unavailable',metadata={'sources':sources})
        isin=matches[0]
        if not re.fullmatch(r'KR[0-9A-Z]{10}',isin): raise ValueError('invalid TIGER issuer fund identity')
        detail_url=base+'/ko/product/search/detail/index.do?'+urlencode({'ksdFund':isin})
        detail=self._fetch_text(detail_url,sources)
        def input_value(name):
            tag=re.search(r'<input\b[^>]*\bname=["\']'+re.escape(name)+r'["\'][^>]*>',detail,re.I)
            value=re.search(r'\bvalue=["\']([^"\']*)["\']',tag.group(0)) if tag else None
            return value.group(1) if value else None
        if input_value('ksdFund')!=isin or input_value('jongCode')!=ticker:
            raise ValueError('TIGER directory/detail share class mismatch')
        local_day=cutoff.astimezone(ZoneInfo('Asia/Seoul')).date()
        price_url=base+'/ko/product/search/detail/price.ajax?'+urlencode({'ksdFund':isin,'startDate':(local_day-timedelta(days=31)).strftime('%Y%m%d'),'endDate':local_day.strftime('%Y%m%d'),'period':'Month01'})
        price=self._fetch_text(price_url,sources)
        navs=[]
        if '기준가격' in price:
            for row in _table_rows(price):
                day=_date(row[0]) if row else None
                if len(row)>=4 and day and datetime.fromisoformat(_stamp(day))<=cutoff:
                    nav=_decimal(row[3]);close=_decimal(row[1])
                    if nav is not None and nav>0: navs.append((day,nav,close))
        navs.sort(reverse=True,key=lambda row:row[0])
        nav_day,nav,close=navs[0] if navs else (None,None,None)
        target=nav_day or (local_day-timedelta(days=1)).isoformat()
        holdings_url=base+'/ko/product/chart/prdct-item-list.ajax?'+urlencode({'ksdFund':isin,'fixDate':target.replace('-',''),'prfPrd':'Week01','listCnt':'1000'})
        data=self._fetch(holdings_url,sources)
        rows=data.get('rtnData',[]) if isinstance(data,dict) else []
        holdings=[];days=set();issues=[]
        for row in rows:
            if row.get('ksdFund')!=isin: raise ValueError('TIGER holding fund identity mismatch')
            day=_date(row.get('wkdate'))
            if not day or datetime.fromisoformat(_stamp(day))>cutoff:
                issues.append('holding date absent/future');continue
            days.add(day)
            weight=_decimal(row.get('stockRate'))
            if weight is None: issues.append('holding weight unavailable');continue
            weight/=Decimal('100')
            if not Decimal('0')<=weight<=1: issues.append('signed/leveraged holding weight unsupported')
            raw=str(row.get('code') or '')
            if not raw: issues.append('holding identifier absent');continue
            identity='ISIN:'+raw if row.get('memItemgb')!='0' and re.fullmatch(r'[A-Z]{2}[0-9A-Z]{10}',raw) else 'ISSUER:'+raw
            holdings.append({'instrument_id':identity,'raw_identifier':raw,'name':row.get('memItemnameEng') or row.get('memItemname'),
                             'weight':str(weight),'sector':None,'country':None,'currency':None,'issuer_asset_type':row.get('memItemgb')})
        if len(days)>1: issues.append('mixed holdings dates')
        total=sum((Decimal(h['weight']) for h in holdings),Decimal('0'))
        if total>1: issues.append('holdings exceed full fund weight; rounding unresolved')
        if len({h['instrument_id'] for h in holdings})!=len(holdings): issues.append('duplicate holding identifiers')
        holding_day=next(iter(days)) if len(days)==1 else None
        md={'issuer':'Mirae Asset TIGER','listing_id':listing,'share_class_identity':isin,
            'nav_per_share':str(nav) if nav is not None else None,'nav_as_of':nav_day,'nav_currency':'KRW','nav_source_url':price_url,
            'official_market_close':str(close) if close is not None else None,'official_market_close_as_of':nav_day,
            'holdings':holdings if not issues else [],'holdings_as_of':holding_day,'holdings_source_url':holdings_url,
            'holdings_coverage':str(total) if not issues else '0','holdings_received_count':len(rows),
            'classification_status':'UNKNOWN','sources':sources,'source_date_precision':'DAY',
            'observed_time_is_conservative_upper_bound':True,'expense_ratio':None,'aum':None,
            'average_daily_value':None,'tracking_difference':None,'all_in_expense_ratio':None,
            'missing_inputs':['holdings_sector_country_currency','aum_as_of','average_daily_value','tracking_difference','all_in_expense_ratio','fees_effective_date']}
        if issues: md.update(raw_holdings=holdings,reported_holdings_coverage=str(total),rounding_issue='; '.join(issues),holdings_calculation_status='WITHHELD')
        fee=re.search(r'총보수</div>\s*<div[^>]*>\s*<p>(.*?)</p>',detail,re.S)
        percent=re.search(r'([0-9]+(?:\.[0-9]+)?)\s*%',_text(fee.group(1))) if fee else None
        if percent:
            md.update(expense_ratio=str(Decimal(percent.group(1))/100),expense_ratio_basis='ISSUER_STATED_TOTAL_MANAGEMENT_FEE',fees_effective_date_status='UNKNOWN',fees_source_url=detail_url)
        def labelled(label):
            match=re.search(r'<div[^>]*class=["\']title["\'][^>]*>\s*'+re.escape(label)+r'\s*</div>\s*<div[^>]*class=["\']value[^"\']*["\'][^>]*>(.*?)</div>',detail,re.S)
            return _text(match.group(1)) if match else None
        md.update(fund_name=labelled('ETF명칭'),benchmark=labelled('기초지수'),undated_aum_display=labelled('순자산총액'))
        if nav is None:md['missing_inputs'].append('dated_nav_per_share')
        if not md['holdings']:md['missing_inputs'].append('dated_holdings')
        dates=[d for d in (nav_day,holding_day if md['holdings'] else None) if d]
        if not dates:return ProviderResult(self.name,request.capability,ProviderStatus.UNAVAILABLE,reason='TIGER dated official data unavailable',metadata={'sources':sources})
        obs=ProviderObservation(evidence_type='financial',source_name='Mirae Asset TIGER',source_url=detail_url,
            source_tier=1,provider_id=self.name,instrument_id=request.instrument_id,metric=request.metric or 'fund_structure',
            value=str(nav) if nav is not None else None,unit='KRW/share',currency='KRW',
            observed_at=_stamp(max(dates)),retrieved_at=sources[-1]['retrieved_at'],metadata=md)
        return ProviderResult(self.name,request.capability,ProviderStatus.PARTIAL,(obs,),reason='official TIGER dated NAV/basket collected; classification and ancillary data partial',metadata={'sources':sources})

    def _samsung(self,request,listing,cutoff,sources):
        base='https://www.samsungfund.com'
        ticker=listing.split(':',1)[1]
        directory_url=base+'/api/v1/kodex/product.do?'+urlencode({'ordrColm':'YIELD_WEEK','ordrSort':'DESC','pageNo':'1','srchTerm':'w','srchVal':ticker})
        directory=self._fetch(directory_url,sources)
        matches=[row for row in directory if str(row.get('stkTicker'))==ticker] if isinstance(directory,list) else []
        if len(matches)!=1:
            return ProviderResult(self.name,request.capability,ProviderStatus.UNAVAILABLE,reason='ambiguous Samsung issuer listing' if matches else 'exact Samsung issuer listing match unavailable',metadata={'sources':sources})
        fid=str(matches[0]['fId'])
        if not re.fullmatch(r'[0-9A-Za-z]+',fid): raise ValueError('invalid issuer fund identity')
        detail_url=base+'/api/v1/kodex/product/'+quote(fid)+'.do'
        data=self._fetch(detail_url,sources)
        product=data.get('info',{}).get('product',{})
        if product.get('fId')!=fid or str(product.get('stkTicker'))!=ticker:
            raise ValueError('directory/detail fund identity mismatch')
        cutoff_day=cutoff.astimezone(ZoneInfo('Asia/Seoul')).date().isoformat()
        eligible=[]
        for row in data.get('suik',{}).get('standardList',[]):
            day=_date(row.get('EVAL_D'))
            if day and datetime.fromisoformat(_stamp(day))<=cutoff and _decimal(row.get('F_P')) is not None:
                eligible.append((day,row))
        eligible.sort(reverse=True,key=lambda item:item[0])
        nav_day,nav_row=eligible[0] if eligible else (None,{})
        nav=_decimal(nav_row.get('F_P'))
        if nav is not None and nav<=0: raise ValueError('NAV/share must be positive')
        product_day=_date(product.get('gijunYMD'))
        metadata={'issuer':'Samsung Asset Management','fund_name':product.get('fNm'),
                  'issuer_fund_id':fid,'listing_id':listing,'share_class_identity':data.get('info',{}).get('stkCd'),
                  'nav_per_share':str(nav) if nav is not None else None,'nav_as_of':nav_day,
                  'nav_currency':'KRW','nav_source_url':detail_url,
                  'benchmark':product.get('bmIdx'),'distribution_policy':product.get('dividRemark'),
                  'holdings':[],'holdings_as_of':None,'classification_status':'UNKNOWN',
                  'source_date_precision':'DAY','observed_time_is_conservative_upper_bound':True,
                  'fees_effective_as_of':None,'expense_ratio':None,'aum':None,'aum_currency':'KRW',
                  'average_daily_value':None,'tracking_difference':None,
                  'missing_inputs':[]}
        fee=re.match(r'^\s*([0-9]+(?:\.[0-9]+)?)\s*%',str(product.get('bosuInfo') or ''))
        if fee:
            metadata['expense_ratio']=str(Decimal(fee.group(1))/Decimal('100'))
            metadata['fees_source_url']=detail_url;metadata['fees_effective_date_status']='UNKNOWN'
            metadata['expense_ratio_basis']='ISSUER_STATED_TOTAL_MANAGEMENT_FEE'
            metadata['all_in_expense_ratio']=None
        if product_day and datetime.fromisoformat(_stamp(product_day))<=cutoff and product.get('nav') is not None:
            metadata['aum']=str(_decimal(product['nav'])*Decimal('100000000'))
            metadata['aum_as_of']=product_day;metadata['aum_source_unit']='100 million KRW'
        pdf=data.get('pdf',{})
        pdf_day=_date(pdf.get('gijunYMD'))
        # The default endpoint can publish next-day basket data. Request a dated
        # basket explicitly instead of relabeling tomorrow's holdings as today's.
        if not pdf_day or datetime.fromisoformat(_stamp(pdf_day))>cutoff:
            target=nav_day or cutoff_day
            pdf_url=base+'/api/v1/kodex/product-pdf/'+quote(fid)+'.do?gijunYMD='+target.replace('-','.')
            try: pdf=self._fetch(pdf_url,sources).get('pdf',{});pdf_day=_date(pdf.get('gijunYMD'))
            except ProviderTransportError: pdf={};pdf_day=None
        else: pdf_url=detail_url
        if pdf_day and datetime.fromisoformat(_stamp(pdf_day))<=cutoff:
            holdings=[]; excluded=[]; weight_issues=[]
            for row in pdf.get('list',[]):
                weight=_decimal(row.get('ratio'))
                if weight is None:
                    excluded.append({'raw_identifier':row.get('itmNo'),'reason':'issuer weight unavailable'})
                    continue
                weight/=Decimal('100')
                if not Decimal('0')<=weight<=Decimal('1'):
                    weight_issues.append('unsupported signed/leveraged holding weight')
                holdings.append({'instrument_id':_holding_id(row.get('itmNo')),'raw_identifier':row.get('itmNo'),
                                 'name':row.get('secNm'),'weight':str(weight),'sector':None,'country':None,'currency':None})
            reported_coverage=sum((Decimal(h['weight']) for h in holdings),Decimal('0'))
            if reported_coverage>1:
                weight_issues.append('holdings exceed full fund weight; issuer rounding may explain excess but has not been reconciled')
            ids=[h['instrument_id'] for h in holdings]
            if len(ids)!=len(set(ids)): weight_issues.append('duplicate official holdings')
            if weight_issues:
                metadata.update(raw_holdings=holdings, reported_holdings_coverage=str(reported_coverage),
                    rounding_issue='; '.join(weight_issues), holdings_calculation_status='WITHHELD',
                    holdings_weight_precision='issuer percentage text preserved; no rescaling')
                holdings=[]
            metadata.update(holdings=holdings,holdings_as_of=pdf_day,holdings_source_url=pdf_url,
                            holdings_coverage=str(sum((Decimal(h['weight']) for h in holdings),Decimal('0'))),
                            holdings_reported_count=pdf.get('totalCnt'),holdings_received_count=len(pdf.get('list',[])),
                            unweighted_rows=excluded)
        if nav is None: metadata['missing_inputs'].append('dated_nav_per_share')
        if not metadata['holdings']: metadata['missing_inputs'].append('dated_holdings')
        metadata['missing_inputs'].extend(['holdings_sector_country_currency','average_daily_value','tracking_difference','all_in_expense_ratio','fees_effective_date'])
        dates=[day for day in (nav_day,metadata['holdings_as_of']) if day]
        if not dates:
            return ProviderResult(self.name,request.capability,ProviderStatus.UNAVAILABLE,reason='dated official NAV/holdings unavailable',metadata={'sources':sources})
        metadata['sources']=sources
        obs=ProviderObservation(evidence_type='financial',source_name='Samsung Asset Management',source_url=detail_url,
            source_tier=1,provider_id=self.name,instrument_id=request.instrument_id,metric=request.metric or 'fund_structure',
            value=str(nav) if nav is not None else None,unit='KRW/share',currency='KRW',
            observed_at=_stamp(max(dates)),retrieved_at=sources[-1]['retrieved_at'],metadata=metadata)
        return ProviderResult(self.name,request.capability,ProviderStatus.PARTIAL,(obs,),reason='official dated data collected; classification/tracking/liquidity coverage remains partial',metadata={'sources':sources})

    def _manifest(self,request,listing,manifest,cutoff,sources):
        """Configured issuers supply the same dated schema without a ticker map.

        manifest={url, official_domain}; JSON requires exact listing_id and dated
        metadata with nav_per_share/nav_as_of and/or holdings/holdings_as_of.
        """
        url=manifest['url'];domain=manifest['official_domain']
        parsed=urlparse(url)
        if parsed.scheme!='https' or parsed.hostname!=domain or '.' not in domain:
            raise ValueError('configured issuer URL must match its official HTTPS domain')
        payload=self._fetch(url,sources)
        if payload.get('listing_id')!=listing: raise ValueError('configured issuer listing mismatch')
        md=_exact_json(dict(payload.get('metadata') or {}))
        dates=[]
        for key in ('nav_as_of','holdings_as_of'):
            day=_date(md.get(key))
            if md.get(key) and (not day or datetime.fromisoformat(_stamp(day))>cutoff): raise ValueError('configured issuer date invalid/future')
            if day:md[key]=day;dates.append(day)
        if not dates:raise ValueError('configured issuer dated NAV/holdings absent')
        if md.get('nav_per_share') is None and not md.get('holdings'):
            raise ValueError('configured issuer actual NAV/holdings absent')
        if md.get('nav_per_share') is not None:
            if not md.get('nav_as_of') or _decimal(md['nav_per_share'])<=0: raise ValueError('configured issuer NAV date/value invalid')
        if md.get('holdings') and not md.get('holdings_as_of'):raise ValueError('configured holdings date absent')
        weights=[_decimal(h['weight']) for h in md.get('holdings',[])]
        if any(w is None or w<0 or w>1 for w in weights) or sum(weights,Decimal('0'))>1:raise ValueError('configured holdings weights invalid')
        ids=[h['instrument_id'] for h in md.get('holdings',[])]
        if len(ids)!=len(set(ids)): raise ValueError('configured duplicate holdings')
        md.update(listing_id=listing,sources=sources,source_date_precision='DAY',observed_time_is_conservative_upper_bound=True)
        obs=ProviderObservation(evidence_type='financial',source_name=domain,source_url=url,source_tier=1,provider_id=self.name,
            instrument_id=request.instrument_id,metric=request.metric or 'fund_structure',value=md.get('nav_per_share'),
            unit='currency/share',currency=md.get('nav_currency'),observed_at=_stamp(max(dates)),retrieved_at=sources[-1]['retrieved_at'],metadata=md)
        return ProviderResult(self.name,request.capability,ProviderStatus.PARTIAL,(obs,),reason='configured dated issuer source; partial coverage',metadata={'sources':sources})
