"""Strict Yahoo Chart 1mo / 5y native bar parser (source-backed, no daily-calendar invention).

The 'quote' OHLC, not dividend-adjusted adjclose, is used. This parser
attests *monthly publisher periods*, NOT independent exchange trading sessions.
"""
from __future__ import annotations
from calendar import monthrange
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse,parse_qs
from zoneinfo import ZoneInfo
import json


@dataclass(frozen=True)
class NativeMonth:
    year: int
    month: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    amount: Decimal | None = None


@dataclass(frozen=True)
class NativeMonths:
    months: tuple[NativeMonth, ...]
    timezone: str
    symbol: str
    currency: str
    source_interval: str = '1mo'
    adjustment_contract: str = 'source_quote_no_splits_dividend_adjclose_unused'


def parse_yahoo_native_months(payload: bytes | str, *, source_url: str,
                              listing_id: str, currency: str, cutoff: datetime,
                              minimum_months: int = 32) -> NativeMonths:
    if cutoff.tzinfo is None:
        raise ValueError('native monthly cutoff must be timezone aware')
    uri=urlparse(source_url)
    q=parse_qs(uri.query,keep_blank_values=True)
    if (uri.scheme!='https' or uri.hostname!='query1.finance.yahoo.com' or
        not uri.path.startswith('/v8/finance/chart/') or
        q!={'interval':['1mo'],'range':['5y'],'events':['div,splits']}):
        raise ValueError('native monthly official endpoint/query binding mismatch')
    data=json.loads(payload)
    chart=data['chart']
    if chart.get('error') is not None or len(chart['result'])!=1:
        raise ValueError('native monthly chart errors/ambiguous result')
    obj=chart['result'][0];meta=obj['meta']
    expected=listing_id.split(':',1)[-1]+('.T' if listing_id.startswith('JPX:') else '')
    if (uri.path.rsplit('/',1)[-1].upper()!=expected.upper() or
        str(meta.get('symbol','')).upper()!=expected.upper() or
        str(meta.get('currency','')).upper()!=currency.upper() or
        meta.get('instrumentType')!='EQUITY' or meta.get('dataGranularity')!='1mo' or
        meta.get('range')!='5y'):
        raise ValueError('native monthly symbol/currency/instrument/granularity/range mismatch')
    tzname=meta.get('exchangeTimezoneName')
    if not isinstance(tzname,str):raise ValueError('exchange timezone absent')
    tz=ZoneInfo(tzname)
    # Events omitted or dividends-only is Yahoo's no-split-record encoding for
    # this exact events=div,splits request, not a proof for arbitrary URLs.
    events=obj.get('events',{})
    if not isinstance(events,dict) or set(events)-{'dividends','splits'}:
        raise ValueError('malformed corporate-action event register')
    splits=events.get('splits',{})
    if not isinstance(splits,dict) or splits:
        raise ValueError('nonempty or malformed splits require a verified adjustment model')
    dividends=events.get('dividends',{})
    if not isinstance(dividends,dict):raise ValueError('malformed dividends register')
    for k,v in dividends.items():
        if not isinstance(v,dict) or not str(k).isdigit() or set(v)<{'amount','date'}:
            raise ValueError('malformed dividend event')
        try:
            if int(k)<0 or type(v['date']) is not int or int(v['date'])<0 or not Decimal(str(v['amount'])).is_finite() or Decimal(str(v['amount']))<0:
                raise ValueError('invalid dividend event')
            if (datetime.fromtimestamp(v['date'],tz)>cutoff.astimezone(tz)):
                raise ValueError('future dividend event')
        except (ValueError,InvalidOperation,TypeError,OverflowError) as exc:raise ValueError('invalid dividend event') from exc
    stamps=obj.get('timestamp');quotes=obj['indicators']['quote']
    if not isinstance(stamps,list) or not stamps or not isinstance(quotes,list) or len(quotes)!=1:
        raise ValueError('missing/ambiguous native timestamps or price fields')
    quote=quotes[0]; fields=('open','high','low','close','volume')
    if any(not isinstance(quote.get(k),list) or len(quote[k])!=len(stamps) for k in fields):
        raise ValueError('native monthly OHLCV length mismatch')
    extra_amount=quote.get('amount')
    if extra_amount is not None and (not isinstance(extra_amount,list) or len(extra_amount)!=len(stamps)):
        raise ValueError('native source amount array mismatch')
    completed=[];keys=[]
    localcut=cutoff.astimezone(tz); current=(localcut.year,localcut.month)
    last_key=None; current_seen=0
    for i,epoch in enumerate(stamps):
        if type(epoch) is not int:raise ValueError('native month timestamp must be integer epoch')
        observed=datetime.fromtimestamp(epoch,tz)
        if observed.astimezone(cutoff.tzinfo)>cutoff:raise ValueError('future native source month')
        key=(observed.year,observed.month)
        if key == current:
            # The source may contain both a native current-month opener and a
            # separate trailing current-quote snapshot. Neither is a closed bar.
            current_seen += 1
            if current_seen > 2 or (current_seen == 1 and observed.day > 2) or (current_seen == 2 and i != len(stamps)-1):
                raise ValueError('unexpected extra current-month quote row')
            continue
        if last_key is not None and key <= last_key:raise ValueError('duplicate or unsorted native months')
        last_key=key
        if observed.day>2:
            raise ValueError('native monthly label is not a month start')
        if key>current:raise ValueError('future native month')
        def number(k):
            try:d=Decimal(str(quote[k][i]))
            except (InvalidOperation,ValueError,TypeError) as e:raise ValueError('malformed native OHLCV '+k) from e
            if not d.is_finite():raise ValueError('nonfinite native OHLCV '+k)
            return d
        o,h,l,c,v=(number(k) for k in fields)
        if min(o,h,l,c)<=0 or v<0 or l>min(o,c) or h<max(o,c) or h<l:
            raise ValueError('native monthly OHLCV bounds invalid')
        amount=None
        if extra_amount is not None:
            amount=number('amount')
            if amount<0:raise ValueError('negative native amount')
        completed.append(NativeMonth(*key,o,h,l,c,v,amount));keys.append(key)
    if not completed:raise ValueError('no closed native monthly bars')
    # 5y range begins inside its first month. Never promote that partial bar.
    completed=completed[1:]; keys=keys[1:]
    if len(completed)<minimum_months:raise ValueError('insufficient closed native months')
    if any((b[0]-a[0])*12+b[1]-a[1]!=1 for a,b in zip(keys,keys[1:])):
        raise ValueError('missing interior native monthly bars')
    prev=(localcut.year-(localcut.month==1),(localcut.month-2)%12+1)
    if keys[-1]!=prev:raise ValueError('stale/incomplete last closed native month')
    return NativeMonths(tuple(completed),tzname,expected,currency)
