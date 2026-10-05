"""Persist dated official fund look-through without normalizing missing exposure."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from itertools import combinations
import json
from uuid import uuid4
from investment_stack.calculations.fund import FundAnalyzer, fund_overlap, portfolio_fund_lookthrough
from investment_stack.reporting.models import Availability, ReportSectionInput
from investment_stack.reporting.portfolio_modes import _convert


@dataclass(frozen=True)
class PortfolioFundOutputs:
    sections: tuple
    evidence_refs: tuple
    calculation_refs: tuple
    missing_inputs: tuple


def render_portfolio_funds(run, request, result, inputs):
    context=run.fetch_phase6_context()
    cutoff=datetime.fromisoformat(request.pinned_state.analysis_as_of.replace('Z','+00:00'))
    evidence={r['evidence_id']:r for r in context['evidence']}
    valid={}; gaps=[]; refs=[]
    for iid,data in inputs.items():
        official=[]
        for eid in data.evidence_ids:
            row=evidence.get(eid,{})
            try:
                metadata=json.loads(row.get('metadata_json') or '{}')
                recorded=metadata.get('holdings',())
                signature=lambda hs:tuple(sorted((str(h['instrument_id']),Decimal(str(h['weight'])),
                    h.get('sector'),h.get('country'),h.get('currency')) for h in hs))
                supplied=tuple({'instrument_id':h.instrument_id,'weight':h.weight,
                    'sector':h.sector,'country':h.country,'currency':h.currency} for h in data.holdings)
                observed=datetime.fromisoformat(row['observed_at'].replace('Z','+00:00'))
                retrieved=datetime.fromisoformat(row['retrieved_at'].replace('Z','+00:00'))
                published=(datetime.fromisoformat(row['published_at'].replace('Z','+00:00'))
                           if row.get('published_at') else None)
                if (row.get('instrument_id')==iid and row.get('metric')=='fund_structure'
                        and row.get('selection_state')=='SELECTED' and row.get('source_tier')==1
                        and row.get('freshness_status')=='FRESH'
                        and metadata.get('holdings_as_of')==data.holdings_as_of
                        and data.analysis_as_of==request.pinned_state.analysis_as_of
                        and signature(recorded)==signature(supplied)
                        and observed<=cutoff and (published is None or published<=cutoff)
                        and retrieved>=max(observed,published or observed)):
                    official.append(eid)
            except (KeyError,ValueError,TypeError,ArithmeticError):
                pass
        analyzed=FundAnalyzer().analyze(data)
        if official and analyzed.metadata.get('holdings_current') and data.holdings:
            valid[iid]=data; refs.extend(data.evidence_ids)
        else:
            gaps.append(iid+':dated_official_holdings_unavailable')
    pairs={a+'|'+b:{'overlap_lower_bound':str(fund_overlap(valid[a].holdings,valid[b].holdings)),
        'partial_holdings':any(sum((h.weight for h in valid[k].holdings),Decimal(0))<1 for k in (a,b))}
        for a,b in combinations(sorted(valid),2)}
    for a,b in combinations(sorted(valid),2):
        schemes=lambda iid:{h.instrument_id.split(':',1)[0] for h in valid[iid].holdings}
        crosswalk_missing=schemes(a)!=schemes(b)
        pairs[a+'|'+b].update(identifier_crosswalk_unavailable=crosswalk_missing,
            zero_does_not_establish_no_overlap=True,
            identity_basis='exact source identifiers only; issuer ticker/ISIN schemes are not inferred')
        if crosswalk_missing:
            gaps.append(a+'|'+b+':holding_identifier_crosswalk_unavailable')
    if result.gross_assets is not None and result.gross_assets>0:
        weighted={}
        for position in request.positions:
            if position.instrument_id not in inputs:
                continue
            value=_convert(position.market_value,position.currency,request.evaluation_currency,cutoff,request.fx_evidence)
            if value is None:
                gaps.append(position.instrument_id+':portfolio_weight_unavailable')
            else:
                weighted[position.instrument_id]=(value/result.gross_assets,inputs[position.instrument_id])
        # Invalid/unofficial sources remain unknown fund exposure even with a
        # numeric weight; never enter the pure calculator as eligible holdings.
        from dataclasses import replace
        weighted={iid:(weight,data if iid in valid else replace(data,holdings=(),holdings_as_of=None))
                  for iid,(weight,data) in weighted.items()}
        payload=portfolio_fund_lookthrough(weighted)
        gaps.extend(payload['gaps'])
    else:
        payload={'status':'UNAVAILABLE','denominator':'full portfolio weight unavailable',
                 'holding_exposure':{},'sector_exposure':{},'country_exposure':{},'currency_exposure':{},
                 'covered_portfolio_weight':None,'unknown_fund_portfolio_weight':None}
        gaps.append('fund_lookthrough_total_portfolio_denominator_unavailable')
    payload.update(fund_pair_overlap=pairs,official_funds=sorted(valid),gaps=sorted(set(gaps)),
                   pair_overlap_denominator='each fund, not total portfolio',
                   partial_holdings_not_renormalized=True)
    if gaps and payload['status']=='COMPLETE':
        payload['status']='PARTIAL'
    source_ids=tuple(row['calculation_id'] for row in context['calculations']
        if row['calculation_name'] in {'FUND','portfolio_analysis'})
    cid='calc:portfolio-fund-lookthrough:'+uuid4().hex
    refs=tuple(dict.fromkeys(refs))
    run.add_calculation(calculation_id=cid,calculation_name='PORTFOLIO_FUND_LOOKTHROUGH',
        formula='full portfolio fraction * dated official holding weight; pair overlap sum(min(weights))',
        inputs={'evidence_ids':list(refs),'source_calculation_ids':list(source_ids),
            'state_version':result.state_version,'snapshot_ref':result.snapshot_ref},result=payload)
    section=ReportSectionInput('portfolio_fund_lookthrough','ETF 실제 보유종목·중복·통과 노출',
        (json.dumps(payload,ensure_ascii=False,default=str),),
        status=Availability.AVAILABLE if payload['status']=='COMPLETE' else Availability.PARTIAL,
        evidence_ids=refs,calculation_ids=(cid,))
    return PortfolioFundOutputs((section,),refs,(cid,),tuple(sorted(set(gaps))))
