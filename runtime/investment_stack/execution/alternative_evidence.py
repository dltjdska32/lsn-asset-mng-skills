"""Reference-only BTC native analysis and explicitly external ETH evidence framework."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import json
from investment_stack.calculations.alternative import AlternativeAssetInput, AlternativeAsset
from investment_stack.providers.models import ProviderObservation, ProviderResult, ProviderStatus
from investment_stack.providers import ProviderCapability, ProviderRequest
from investment_stack.reporting.models import ReportSectionInput, Availability
from investment_stack.execution.portfolio_thesis_modes import SelectedAssetResearchResult


def external_crypto(payload, symbol, *, cutoff, retrieved, url):
    """Validate aggregator identity/time; no native ETH support is claimed."""
    d=json.loads(payload,parse_float=Decimal) if isinstance(payload,(bytes,str)) else payload
    result=d['chart']['result'][0];meta=result['meta']
    if symbol not in {'BTC','ETH'} or meta.get('symbol')!=symbol+'-USD' or meta.get('currency')!='USD' or meta.get('instrumentType')!='CRYPTOCURRENCY':
        raise ValueError('external crypto identity/type/currency mismatch')
    value=meta['regularMarketPrice']
    if isinstance(value,(bool,float)):raise ValueError('exact crypto decimal required')
    value=Decimal(value)
    if not value.is_finite() or value<=0:raise ValueError('invalid crypto price')
    at=datetime.fromtimestamp(int(meta['regularMarketTime']),timezone.utc)
    asof=datetime.fromisoformat(cutoff.replace('Z','+00:00'))
    if asof.tzinfo is None or not timedelta(0)<=asof-at<=timedelta(minutes=20):
        raise ValueError('crypto quote future/stale')
    obs=ProviderObservation('market','Yahoo crypto aggregate',url,2,'external_alternative',value=value,unit='USD',currency='USD',instrument_id=symbol,metric='external_spot_price',retrieved_at=retrieved,observed_at=at.isoformat(),published_at=at.isoformat(),metadata={'native_support':symbol=='BTC','framework':'external_evidence','venue':'aggregate','exact_value_decimal':str(value),'quote_kind_label':'AGGREGATE_SPOT_DELAY_UNKNOWN'})
    closes=[]
    series=result.get('indicators',{}).get('quote',[{}])[0].get('close',[])
    for stamp,close in zip(result.get('timestamp',[]),series):
        # Daily crypto candle end is derived from the interval, not a provider timestamp.
        end=datetime.fromtimestamp(int(stamp),timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1)
        if close is None or end>asof:continue
        if isinstance(close,(bool,float)):raise ValueError('exact historical decimal required')
        price=Decimal(close)
        if not price.is_finite() or price<=0:continue
        closes.append(ProviderObservation('market','Yahoo crypto aggregate',url,2,'external_alternative',value=price,unit='USD',currency='USD',instrument_id=symbol,metric='external_daily_close',retrieved_at=retrieved,observed_at=end.isoformat(),published_at=end.isoformat(),metadata={'interval':'1d','derived_interval_end':True,'exact_value_decimal':str(price),'calculation_input_approved':True}))
    return obs,tuple(closes)


def reference_alternatives(live, transport):
    sections=[];refs=[];calcs=[];missing=[]
    for symbol in ('BTC','ETH'):
        url=f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}-USD?interval=1d&range=1mo'
        try:
            raw=transport(url,{'User-Agent':'Mozilla/5.0'},10)
            obs,history=external_crypto(raw,symbol,cutoff=live.clock,retrieved=transport.retrieved_at_for(url) if hasattr(transport,'retrieved_at_for') else datetime.now(timezone.utc).isoformat(),url=url)
            store=live.research.evidence
            current=store.persist_and_select((ProviderResult('external_alternative',ProviderCapability.CURRENT_PRICE,ProviderStatus.AVAILABLE,(obs,)),),analysis_as_of=live.clock)
            asset_refs=[current.evidence_id] if current.evidence_id else []
            for item in history:
                selected=store.persist_and_select((ProviderResult('external_alternative',ProviderCapability.HISTORICAL_PRICE,ProviderStatus.AVAILABLE,(item,)),),analysis_as_of=live.clock)
                # Historical closes are dated data; freshness isn't relabeled current.
                if selected.evidence_id:asset_refs.append(selected.evidence_id)
            series=tuple(Decimal(str(item.value)) for item in history)
            if symbol=='BTC':
                native=live.collect(ProviderCapability.CURRENT_PRICE,'CRYPTO:BTC/USD','current_price')
                if native.selected.observation:
                    asset_refs.append(native.selected.evidence_id)
                else:missing.append('BTC:verified_venue_spot_quote')
                result=live.analysis.analyze_alternative(AlternativeAssetInput('BTC',AlternativeAsset.BITCOIN,'reference_only_not_held',None,series,'USD',venue='Yahoo aggregate history; spot venue separately qualified',price_as_of=obs.observed_at,evidence_ids=tuple(asset_refs)))
                calcs.append(result.metadata['calculation_id'])
                missing.extend('BTC:'+k for k in result.unknowns)
                framework='alternative-asset-analysis native BITCOIN calculator; external history'
            else:
                result=live.analysis.analyze_alternative(AlternativeAssetInput('ETH',AlternativeAsset.ETHEREUM,'reference_only_not_held',None,series,'USD',venue='Yahoo aggregate history',price_as_of=obs.observed_at,evidence_ids=tuple(asset_refs)))
                calcs.append(result.metadata['calculation_id'])
                missing.extend('ETH:'+k for k in result.unknowns)
                framework='alternative-asset-analysis ETHEREUM calculator; external history; network inputs unavailable'
            lines=[f'{symbol}: reference only, not held; {framework}.',f'가격={obs.value} USD; timestamp={obs.observed_at}; retrieved={obs.retrieved_at}; source={url}; aggregate/delay unknown.']
            if len(series)>=2:
                change=series[-1]/series[0]-1
                lines.append(f'완료 일봉 {len(series)}개 추세={change}; 과거 관측 최저={min(series)}·최고={max(series)} USD. 예측 지지/저항 또는 매수 가격 목표가 아닙니다.')
                calc='calc:alternative-range:'+symbol
                live.run.add_calculation(calculation_id=calc,calculation_name='external_alternative_trend_range',formula='last / first - 1; min(close); max(close)',inputs={'evidence_ids':asset_refs},result={'period_return':str(change),'historical_low':str(min(series)),'historical_high':str(max(series)),'native_eth_supported':True})
                calcs.append(calc)
            else:missing.append(symbol+':completed_history')
            for metric in ('institutional_etf_flows','macro_context','latest_news','entry_range_evidence'):
                missing.append(symbol+':'+metric)
            lines.append('기관/ETF 자금 흐름·거시·최신 뉴스·진입구간 근거 부족. 목표가격 및 합리적 진입가격 산출 보류.')
            refs.extend(asset_refs)
            sections.append(ReportSectionInput('alternative_'+symbol,symbol+' reference',tuple(lines),status=Availability.PARTIAL,evidence_ids=tuple(asset_refs)))
        except Exception as exc:
            missing.append(symbol+':external_evidence:'+type(exc).__name__)
            live.run.record_task_state(task_name='reference_alternative:'+symbol,task_status='PARTIAL',metadata={'reason':str(exc) if isinstance(exc,ValueError) else type(exc).__name__,'native_eth_supported':True})
            sections.append(ReportSectionInput('alternative_'+symbol,symbol+' reference',(symbol+': 최신 검증 evidence 부족; 가격·진입구간 산출 보류. ETH native runtime 미지원.',),status=Availability.PARTIAL))
    return SelectedAssetResearchResult(tuple(sections),evidence_refs=tuple(refs),calculation_refs=tuple(calcs),missing_inputs=tuple(missing))
