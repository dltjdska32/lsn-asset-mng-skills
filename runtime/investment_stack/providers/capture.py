"""Real HTTP payload capture with hashes and original retrieval timestamps.

Capture precedes the point-in-time run clock. This avoids accepting a quote that
arrived after analysis_as_of and never rewrites a provider's quote timestamp.
"""
from pathlib import Path
from datetime import datetime,timezone
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode
import hashlib,json,re
from investment_stack.providers.http import urllib_transport



def market_urls(listings=None):
    urls=[]
    for listing in (listings or {}).values():
        exchange,ticker=listing.split(':')
        if exchange not in {'KRX','JPX','NYSE','NASDAQ'} or not re.fullmatch(r'[A-Z0-9][A-Z0-9.-]{0,19}',ticker):
            raise ValueError('only public exchange/local-ticker identifiers are allowed in HTTP requests')
        if exchange=='KRX' and not re.fullmatch(r'[0-9A-Z]{6}',ticker):
            raise ValueError('KRX code must contain six characters')
        if exchange=='JPX' and not re.fullmatch(r'[0-9A-Z]{4}',ticker):
            raise ValueError('JPX local code must contain four characters')
        if exchange=='KRX':
            urls.append(f'https://m.stock.naver.com/api/stock/{ticker}/basic')
            urls.append(f'https://m.stock.naver.com/api/stock/{ticker}/integration')
        else:
            symbol=ticker+'.T' if exchange=='JPX' else ticker
            for host in ('query1.finance.yahoo.com','query2.finance.yahoo.com'):
                urls.append(f'https://{host}/v8/finance/chart/{symbol}?interval=1d&range=1mo')
                urls.append(f'https://{host}/v1/finance/search?'+urlencode({'q':symbol,'quotesCount':0,'newsCount':10}))
    for pair in ('KRW=X','JPYKRW=X','JPY=X'):
        for host in ('query1.finance.yahoo.com','query2.finance.yahoo.com'):
            urls.append(f'https://{host}/v8/finance/chart/{pair}?interval=1d&range=5d')
    urls.extend(f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}-USD?interval=1d&range=1mo' for symbol in ('BTC','ETH'))
    urls.append('https://api.exchange.coinbase.com/products/BTC-USD/ticker')
    return tuple(dict.fromkeys(urls))

def capture_market_data(directory, transport=urllib_transport, *, listings=None):
    root=Path(directory);root.mkdir(parents=True,exist_ok=True)
    def capture(url):
        try:
            body=transport(url,{'User-Agent':'Mozilla/5.0','Accept':'application/json'},10)
            try:
                payload=json.loads(body)
            except (ValueError, UnicodeDecodeError):
                return {'url':url,'status':'UNAVAILABLE','reason':'INVALID_JSON_RESPONSE',
                        'sha256':hashlib.sha256(body).hexdigest()}
            if not isinstance(payload, dict):
                return {'url':url,'status':'UNAVAILABLE','reason':'INVALID_JSON_OBJECT'}
            retrieved=datetime.now(timezone.utc).isoformat();digest=hashlib.sha256(body).hexdigest()
            filename=hashlib.sha256(url.encode()).hexdigest()+'.json';(root/filename).write_bytes(body)
            return {'url':url,'file':filename,'sha256':digest,'retrieved_at':retrieved,'status':'CAPTURED'}
        except Exception as exc:return {'url':url,'status':'UNAVAILABLE','reason':type(exc).__name__}
    with ThreadPoolExecutor(max_workers=8) as pool:records=list(pool.map(capture,market_urls(listings)))
    payload={'schema_version':1,'captured_at':datetime.now(timezone.utc).isoformat(),'records':records}
    (root/'manifest.json').write_text(json.dumps(payload,indent=2))
    return payload

class CapturedMarketTransport:
    def __init__(self,directory,*,fallback=urllib_transport,allow_live_fallback=True):
        self.root=Path(directory);manifest=json.loads((self.root/'manifest.json').read_text())
        if manifest.get('schema_version')!=1:raise ValueError('unsupported capture manifest')
        self.records={row['url']:row for row in manifest['records'] if row['status']=='CAPTURED'}
        def deny(url,headers,timeout):
            raise ValueError('offline captures: live network fallback disabled')
        self.fallback=fallback if allow_live_fallback else deny
    def __call__(self,url,headers,timeout):
        record=self.records.get(url)
        if record is None:return self.fallback(url,headers,timeout)
        path=(self.root/record['file']).resolve()
        if not path.is_relative_to(self.root.resolve()):raise ValueError('capture path escape')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=record['sha256']:raise ValueError('capture payload hash mismatch')
        return raw
    def retrieved_at_for(self,url):
        row=self.records.get(url)
        return row['retrieved_at'] if row else datetime.now(timezone.utc).isoformat()
