"""Opt-in, provider-transport-backed capture for experimental forecasts.

Only Yahoo Chart 1d unadjusted bars with an *explicit* empty split-event
register are supported. The pinned exchange calendar, not the data provider's
list of sparse trading dates, defines complete-month coverage. Missing proof
of corporate-action completeness is UNAVAILABLE, never a fabricated receipt.
The fetch transport must be a configured host transport; no remote fallback is
created by this module. No arbitrary user JSON arrays are accepted.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from urllib.parse import quote
from uuid import uuid4
import json

from investment_stack.evidence.source_receipt import payload_sha256
from investment_stack.freshness import get_pinned_calendar
from investment_stack.providers.market_quotes import parse_yahoo_quote
from investment_stack.providers.ohlcv import parse_yahoo_chart_ohlcv


class ForecastSourceCollector:
    def __init__(self, run, resolver, transport, *, prefer_native_monthly=False):
        self.run, self.resolver, self.transport = run, resolver, transport
        self.prefer_native_monthly = prefer_native_monthly

    def collect(self, iid: str, currency: str, cutoff: datetime) -> dict[str, str]:
        """Capture and select provider-bound rows in a single run mutation.

        Caller cannot supply provider parsed data, exchange sessions or
        adjustment factors. Any unsupported period/provider stays unavailable.
        """
        if self.transport is None or cutoff.tzinfo is None:
            raise ValueError('verified capture transport and aware cutoff required')
        resolved = self.resolver.resolved.get(iid) or self.resolver.resolve(iid)
        if resolved.instrument_id != iid or resolved.currency != currency or resolved.asset_class != 'EQUITY':
            raise ValueError('resolved equity identifier/currency mismatch')
        exchange = resolved.exchange
        listing_id = f'{resolved.exchange}:{resolved.ticker}'
        if self.prefer_native_monthly:
            return self._collect_native_monthly(iid,currency,cutoff,resolved,listing_id)
        with self.run._mutation_connection() as con:
            found=con.execute("SELECT resolved_identifier FROM instrument_resolutions WHERE run_id=? AND requested_identifier=? AND resolution_status='RESOLVED'",(self.run.run_id,iid)).fetchone()
            if not found or found[0] != listing_id:
                raise ValueError('persisted run listing differs from host verified resolver')
        calendar = get_pinned_calendar(exchange)
        if calendar is None or not calendar.is_pinned or calendar.currency != currency:
            raise ValueError('pinned official exchange calendar unavailable')
        # The existing schedule is intentionally bounded: dates outside its
        # covered period do not pass, even if a provider returned enough bars.
        local = cutoff.astimezone(__import__('zoneinfo').ZoneInfo(calendar.timezone))
        from calendar import monthrange
        from datetime import date
        y, m = local.year, local.month
        prev_y, prev_m = (y-1, 12) if m == 1 else (y, m-1)
        first_y, first_m = (prev_y-1, prev_m+1) if prev_m >= 8 else (prev_y, prev_m-7)
        # Need eight *full* months of provider daily records.
        first_y, first_m = ((prev_y*12+prev_m-1-7)//12, (prev_y*12+prev_m-1-7)%12+1)
        if not calendar.covers(date(first_y, first_m, 1), date(prev_y, prev_m, monthrange(prev_y,prev_m)[1])):
            raise ValueError('official pinned exchange calendar does not cover eight whole months')
        if exchange not in {'NASDAQ', 'NYSE', 'JPX'}:
            raise ValueError('only Yahoo Chart with confirmed no-split history supported')
        ticker = resolved.ticker + ('.T' if exchange == 'JPX' else '')
        url = 'https://query1.finance.yahoo.com/v8/finance/chart/'+quote(ticker,safe='.')+'?interval=1d&range=1y&events=div%2Csplits'
        body = self.transport(url, {'User-Agent':'Mozilla/5.0','Accept':'application/json'}, 10)
        if not isinstance(body, bytes):
            raise ValueError('provider transport must return original bytes')
        text = body.decode('utf-8', errors='strict')
        data = json.loads(text)
        chart = data['chart']['result'][0]
        if not isinstance(chart.get('events'),dict) or chart['events'].get('splits') != {}:
            raise ValueError('provider does not explicitly attest an empty split-event register')
        if chart['meta'].get('instrumentType') != 'EQUITY':
            raise ValueError('provider instrument type is not equity')
        if str(chart['meta']['currency']).upper() != currency:
            raise ValueError('provider currency mismatch')
        retrieved_raw = (self.transport.retrieved_at_for(url) if hasattr(self.transport,'retrieved_at_for')
                         else datetime.now(timezone.utc).isoformat())
        retrieved = datetime.fromisoformat(str(retrieved_raw).replace('Z','+00:00'))
        if retrieved.tzinfo is None:
            raise ValueError('capture retrieval timestamp must be aware')
        parsed = parse_yahoo_chart_ohlcv(text, instrument_id=listing_id,analysis_as_of=cutoff,
                     source_url=url,adjustment_verified=True,
                     adjustment_receipt='provider:yahoo:empty-split-events:'+payload_sha256(text),
                     calendar_receipt=calendar.schedule_id)
        if parsed.bar_set is None or parsed.incomplete_bars or parsed.discarded_bars or parsed.error_reasons:
            raise ValueError('provider OHLCV parser refused body')
        dates = [b.session_date for b in parsed.bar_set.bars]
        if len(dates) != len(set(dates)) or not dates:
            raise ValueError('duplicate/empty provider sessions')
        quote_parsed = parse_yahoo_quote(text, instrument_id=listing_id,retrieved_at=retrieved,source_url=url)
        if quote_parsed.quote is None:
            raise ValueError('source body has no verified matching quote')
        q = quote_parsed.quote
        if q.claimed_market_time is None or q.claimed_market_time.tzinfo is None:
            raise ValueError('provider quote has no claimed market time')
        observed = q.claimed_market_time.astimezone(timezone.utc)
        if type(chart['meta'].get('regularMarketTime')) is not int:
            raise ValueError('daily source raw publication epoch must be integer')
        source_published = datetime.fromtimestamp(chart['meta']['regularMarketTime'],tz=timezone.utc)
        if source_published < observed or source_published > cutoff or retrieved < source_published:
            raise ValueError('daily source actual publication is future or later than retrieval')
        if observed > cutoff or retrieved < observed or str(q.currency).upper() != currency:
            raise ValueError('quote future/currency/retrieval mismatch')
        latest = calendar.latest_completed_session(cutoff)
        if latest is None or q.market_session_date != latest.session_date.isoformat():
            raise ValueError('quote is not from latest closed pinned exchange session')
        if abs((observed-latest.closes_at).total_seconds()) > 900:
            raise ValueError('quote market time differs from pinned session close')
        if not parsed.bar_set.bars or parsed.bar_set.bars[-1].session_date != q.market_session_date or parsed.bar_set.bars[-1].close != q.price:
            raise ValueError('quote price not bound to last closed provider daily bar')
        # At least the last completed month must be present; exact complete
        # schedule reconciliation is repeated by the consumer before ML import.
        previous = (prev_y,prev_m)
        if previous not in {(int(d[:4]),int(d[5:7])) for d in dates}:
            raise ValueError('last completed month absent from provider body')
        date_tag = q.market_session_date
        if not date_tag:
            raise ValueError('provider quote session date missing')
        prefix = 'fcsrc:'+uuid4().hex+':'
        ids = {'history_evidence_id':prefix+'h','quote_evidence_id':prefix+'q'}
        conversion_id = prefix+'c'
        timestamp = observed.isoformat()
        sha = payload_sha256(text)
        receipt = {'calendar_receipt':calendar.schedule_id,
                   'calendar_source_urls':list(calendar.source_urls),
                   'calendar_timezone':calendar.timezone,
                   'expected_session_dates':dates,
                   'adjustment_receipt':'provider:yahoo:empty-split-events:'+sha,
                   'adjustment_verified':True, 'analysis_eligible':True,
                   'resolved_listing_id':listing_id}
        common = (self.run.run_id,iid,currency,'SELECTED','FRESH','CONFIRMED',timestamp,source_published.isoformat(),retrieved.isoformat())
        spec = [
           (ids['history_evidence_id'],'historical_ohlcv','yahoo_chart_ohlcv_v1',None,{'ohlcv_receipt':receipt}),
           (ids['quote_evidence_id'],'current_price','yahoo_chart_v1',str(q.price),
            {'exchange':exchange,'market_session_date':date_tag,'price_basis':'split-adjusted',
             'conversion_factor':'1','verified_adjustment_conversion_ref':conversion_id,
             'resolved_listing_id':listing_id}),
           (conversion_id,'price_adjustment_conversion','yahoo_split_events_v1',None,
            {'source_sha256':sha,'direction':'nominal_to_split_adjusted','price_basis':'split-adjusted',
             'factor':'1','instrument_id':iid,'resolved_listing_id':listing_id,'currency':currency,
             'quote_evidence_id':ids['quote_evidence_id'],
             'history_evidence_id':ids['history_evidence_id'],'effective_at':timestamp})]
        with self.run._mutation_connection() as con:
            for eid, metric, parser, value, meta in spec:
                con.execute('INSERT INTO evidence (evidence_id,run_id,evidence_type,source_uri,content_hash,metadata_json,'
                  'instrument_id,currency,metric,value_text,selection_state,freshness_status,official_confirmation_status,'
                  'observed_at,published_at,retrieved_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                  (eid,self.run.run_id,'market',url,sha,json.dumps(meta,sort_keys=True,allow_nan=False),
                   iid,currency,metric,value,'SELECTED','FRESH','CONFIRMED',timestamp,source_published.isoformat(),retrieved.isoformat()))
                con.execute('INSERT INTO source_documents (document_id,run_id,evidence_id,parser_id,content_sha256,payload_text) VALUES (?,?,?,?,?,?)',
                            ('source:'+uuid4().hex,self.run.run_id,eid,parser,sha,text))
        return ids

    def _collect_native_monthly(self, iid, currency, cutoff, resolved, listing_id):
        """5y Yahoo 1mo raw-history + independent latest closed daily quote.

        No pinned 2026 daily calendar is extended backwards. Provider native
        closed-month coverage is checked as a DIFFERENT source contract.
        """
        from investment_stack.providers.yahoo_native_months import parse_yahoo_native_months
        from zoneinfo import ZoneInfo
        import sqlite3
        if resolved.exchange not in ('NASDAQ','NYSE','JPX'):
            raise ValueError('native Yahoo monthly source unsupported exchange')
        ticker = resolved.ticker + ('.T' if resolved.exchange=='JPX' else '')
        root='https://query1.finance.yahoo.com/v8/finance/chart/'+quote(ticker,safe='.')
        history_url=root+'?interval=1mo&range=5y&events=div%2Csplits'
        quote_url=root+'?interval=1d&range=5d&events=div%2Csplits'
        if self.transport is None:raise ValueError('explicit verified transport required')
        hbytes=self.transport(history_url,{'User-Agent':'Mozilla/5.0','Accept':'application/json'},10)
        qbytes=self.transport(quote_url,{'User-Agent':'Mozilla/5.0','Accept':'application/json'},10)
        if not isinstance(hbytes,bytes) or not isinstance(qbytes,bytes):
            raise ValueError('provider original byte bodies required')
        hist=parse_yahoo_native_months(hbytes,source_url=history_url,listing_id=listing_id,
                                       currency=currency,cutoff=cutoff)
        calendar=get_pinned_calendar(resolved.exchange)
        if (calendar is None or calendar.currency!=currency or not calendar.is_pinned or
            hist.timezone!=calendar.timezone):
            raise ValueError('current quote verified exchange calendar/timezone missing')
        def retrieved(url):
            v=(self.transport.retrieved_at_for(url) if hasattr(self.transport,'retrieved_at_for')
               else datetime.now(timezone.utc).isoformat())
            d=datetime.fromisoformat(str(v).replace('Z','+00:00'))
            if d.tzinfo is None:raise ValueError('source retrieval must be aware')
            return d
        hretrieved,qretrieved=retrieved(history_url),retrieved(quote_url)
        parsed_quote=parse_yahoo_chart_ohlcv(qbytes,instrument_id=listing_id,
            analysis_as_of=cutoff,source_url=quote_url,adjustment_verified=True,
            adjustment_receipt='provider:yahoo:empty-splits:'+payload_sha256(qbytes.decode('utf8')),
            calendar_receipt=calendar.schedule_id)
        obj=json.loads(qbytes)['chart']['result'][0]
        meta=obj['meta']
        events=obj.get('events',{})
        if (meta.get('dataGranularity')!='1d' or meta.get('instrumentType')!='EQUITY' or
            str(meta.get('symbol','')).upper()!=ticker.upper() or
            str(meta.get('currency','')).upper()!=currency or
            not isinstance(events,dict) or set(events)-{'dividends','splits'} or
            events.get('splits',{})!={}):
            raise ValueError('latest daily source identity/interval/split-events mismatch')
        latest=calendar.latest_completed_session(cutoff)
        if latest is None:raise ValueError('verified last session not in pinned schedule')
        if parsed_quote.bar_set is None or parsed_quote.discarded_bars or parsed_quote.error_reasons:
            raise ValueError('canonical latest daily OHLCV parser rejected source')
        daily_bars=parsed_quote.bar_set.bars
        if not daily_bars or daily_bars[-1].session_date!=latest.session_date.isoformat():
            raise ValueError('latest verified daily quote bar unavailable')
        q=parse_yahoo_quote(qbytes,instrument_id=listing_id,retrieved_at=qretrieved,source_url=quote_url).quote
        if q is None or q.claimed_market_time is None:
            raise ValueError('official daily quote unavailable')
        observed=q.claimed_market_time.astimezone(timezone.utc)
        if type(meta.get('regularMarketTime')) is not int:
            raise ValueError('latest daily source publication epoch must be integer')
        daily_publication=datetime.fromtimestamp(meta['regularMarketTime'],tz=timezone.utc)
        if daily_publication<observed or daily_publication>cutoff or qretrieved<daily_publication:
            raise ValueError('daily quote raw publication outside PIT window')
        if (observed>cutoff or qretrieved<observed or hretrieved<datetime(
             hist.months[-1].year,hist.months[-1].month,1,tzinfo=ZoneInfo(hist.timezone)).astimezone(timezone.utc) or
            q.currency!=currency or q.market_session_date!=latest.session_date.isoformat() or
            abs((observed-latest.closes_at).total_seconds())>900 or
            q.price!=daily_bars[-1].close):
            raise ValueError('latest quote current close/clock/currency/provenance mismatch')
        # A no-split ledger must cover the quote itself, not merely the last
        # completed month. Cross-bind the provider's latest market snapshot.
        monthly_meta=json.loads(hbytes)['chart']['result'][0]['meta']
        if (type(monthly_meta.get('regularMarketTime')) is not int or
            monthly_meta['regularMarketTime'] != meta['regularMarketTime'] or
            daily_publication < observed or hretrieved < daily_publication or
            Decimal(str(monthly_meta.get('regularMarketPrice','NaN'))) != q.price):
            raise ValueError('monthly corporate action ledger does not extend to latest daily quote')
        # The native monthly quote is nominal and not adjclose: no-split body
        # proves a factor 1 within its 5y coverage; daily source separately
        # attests no splits up to the current quote.
        prefix='fcsrc:'+uuid4().hex+':'
        ids={'history_evidence_id':prefix+'h','quote_evidence_id':prefix+'q'}
        cid=prefix+'c'; hsha=payload_sha256(hbytes.decode('utf8'));qsha=payload_sha256(qbytes.decode('utf8'))
        from calendar import monthrange
        # A completed monthly candle was not available on its opening day.
        label_time=datetime(hist.months[-1].year,hist.months[-1].month,
                            monthrange(hist.months[-1].year,hist.months[-1].month)[1],
                            23,59,59,tzinfo=ZoneInfo(hist.timezone)).astimezone(timezone.utc)
        common=(self.run.run_id,iid,currency,'SELECTED','FRESH','CONFIRMED')
        receipt={'native_interval':'1mo','range':'5y','calendar_timezone':hist.timezone,
            'calendar_receipt':'provider:yahoo:native-monthly-closed:'+hsha,
            'adjustment_receipt':'provider:yahoo:no-splits:'+hsha,
            'adjustment_verified':True,'resolved_listing_id':listing_id,
            'first_closed_month':f'{hist.months[0].year:04d}-{hist.months[0].month:02d}',
            'last_closed_month':f'{hist.months[-1].year:04d}-{hist.months[-1].month:02d}',
            'completed_count':len(hist.months),'quote_source_sha256':qsha,
            'price_source':'indicators.quote (NOT dividend-adjusted adjclose)'}
        spec=[(ids['history_evidence_id'],'historical_ohlcv','yahoo_chart_native_monthly_v1',history_url,hsha,hbytes,
               None,{'ohlcv_receipt':receipt},label_time.isoformat(),hretrieved.isoformat()),
              (ids['quote_evidence_id'],'current_price','yahoo_chart_v1',quote_url,qsha,qbytes,
               str(q.price),{'exchange':resolved.exchange,'market_session_date':q.market_session_date,
               'price_basis':'split-adjusted','conversion_factor':'1',
               'verified_adjustment_conversion_ref':cid,'resolved_listing_id':listing_id},
               observed.isoformat(),qretrieved.isoformat()),
              (cid,'price_adjustment_conversion','yahoo_native_no_splits_v1',history_url,hsha,hbytes,
               None,{'source_sha256':hsha,'direction':'nominal_to_split_adjusted','price_basis':'split-adjusted',
                     'factor':'1','instrument_id':iid,'resolved_listing_id':listing_id,'currency':currency,
                     'quote_evidence_id':ids['quote_evidence_id'],'history_evidence_id':ids['history_evidence_id'],
                     'effective_at':observed.isoformat(),'quote_source_sha256':qsha},
               observed.isoformat(),hretrieved.isoformat())]
        # The provider snapshot time is not the observed exchange close.
        quote_published=daily_publication.isoformat()
        if label_time>daily_publication:raise ValueError('monthly publication predates complete candle')
        # Retrieval of an old published monthly observation can be later than
        # its publication; never pretend the current quote existed in history.
        with self.run._mutation_connection() as con:
            row=con.execute("SELECT resolved_identifier FROM instrument_resolutions WHERE run_id=? AND requested_identifier=? AND resolution_status='RESOLVED'",(self.run.run_id,iid)).fetchone()
            if row is None or row[0]!=listing_id:raise ValueError('run resolution mismatch')
            for eid,metric,parser,url,sha,raw,value,metadata,when,got in spec:
                published=quote_published
                if (datetime.fromisoformat(when)>datetime.fromisoformat(published) or
                    datetime.fromisoformat(published)>cutoff or
                    datetime.fromisoformat(got)<datetime.fromisoformat(published)):
                    raise ValueError('source publication PIT identity/retrieval mismatch')
                con.execute('INSERT INTO evidence (evidence_id,run_id,evidence_type,source_uri,content_hash,metadata_json,'
                  'instrument_id,currency,metric,value_text,selection_state,freshness_status,official_confirmation_status,'
                  'observed_at,published_at,retrieved_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                  (eid,self.run.run_id,'market',url,sha,json.dumps(metadata,sort_keys=True),iid,currency,
                   metric,value,'SELECTED','FRESH','CONFIRMED',when,published,got))
                con.execute('INSERT INTO source_documents (document_id,run_id,evidence_id,parser_id,content_sha256,payload_text) VALUES (?,?,?,?,?,?)',
                            ('source:'+uuid4().hex,self.run.run_id,eid,parser,sha,raw.decode('utf8')))
        return ids
