from contextlib import closing
"""Phase4 lightweight discovery and typed portfolio inputs for the configured host."""
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
import json, sqlite3
from investment_stack.providers import ProviderRequest, ProviderCapability
from investment_stack.providers.models import ProviderResult, ProviderStatus
from investment_stack.providers.fx import cross_fx
from investment_stack.materiality import LightweightAsset, MaterialityDecision
from investment_stack.materiality.event_gate import classify_event_impact
from investment_stack.reporting.models import Availability, ReportSectionInput
from investment_stack.reporting.portfolio_modes import FxEvidence
from investment_stack.calculations.fund import FundAnalysisInput, FundHolding
from investment_stack.execution.portfolio_thesis_modes import SelectedAssetResearchResult



class PortfolioEvidence:
    def __init__(self, run, ledger, research, analysis, *, special_rules=None):
        self.run,self.ledger,self.research,self.analysis=run,ledger,research,analysis
        context=run.fetch_phase6_context(); self.clock=str(context["run_metadata"]["analysis_as_of"])
        self.zone=str(context["run_metadata"]["analysis_timezone"])
        self.held_ids=(); self.research_all_held=False; self.quantities={}; self.quotes={}; self.fx={}; self.events={}; self.missing=[]; self.lines=[]; self.refs=[]; self.calcs=[]; self.fund_inputs={}
        self.projection=ledger.get_projection_as_of_state_version(int(context['pinned_personal_state']['state_version']))
        with closing(sqlite3.connect(ledger.manager.database_path)) as c:
            c.row_factory=sqlite3.Row
            self.instruments={row['instrument_id']:dict(row) for row in c.execute('select * from instruments')}
            self.position_rows=[{'account_id':p.account_id,'instrument_id':p.instrument_id,
                'quantity_decimal':str(p.quantity),'average_unit_cost_decimal':str(p.average_unit_cost) if p.average_unit_cost is not None else None,
                'cost_basis_status':p.cost_basis_status.value,'currency_code':p.currency} for p in self.projection.positions]
            self.quantities={}
            for row in self.position_rows:
                iid=row['instrument_id']
                self.quantities[iid]=self.quantities.get(iid,Decimal('0'))+Decimal(row['quantity_decimal'])
            snapshot=c.execute('select data_json from portfolio_snapshots where snapshot_id=?',(context['pinned_personal_state']['portfolio_snapshot_id'],)).fetchone()
            self.snapshot=json.loads(snapshot[0]); self.rules=list(self.snapshot.get('special_investment_rules',[]))
            for row in c.execute('select metadata_json from goals'):
                self.rules.extend(json.loads(row[0] or '{}').get('special_investment_rules',[]))
        pin=context['pinned_personal_state']
        self.snapshot.setdefault('state_version', pin['state_version'])
        self.snapshot.setdefault('data_as_of', pin.get('portfolio_data_as_of'))
        self.external_rules=list(special_rules or [])

    def collect(self, capability, iid, metric, query=None):
        return self.research.collect(ProviderRequest(capability,self.clock,self.zone,iid,metric),web_query=query)

    def lightweight(self, request):
        cutoff=datetime.fromisoformat(self.clock)
        for row in self.position_rows:
            if row['instrument_id'] in self.held_ids:
                self.lines.append(f"보유: {row['instrument_id']}; account={row['account_id']}; quantity={row['quantity_decimal']}; average_cost={row['average_unit_cost_decimal']} {row['currency_code']}; cost_basis_status={row['cost_basis_status']}; source=pinned personal.db projection.")
        for iid in self.instruments:
            # Only real held assets, not reference-only zero positions.
            if iid not in self.held_ids: continue
            out=self.collect(ProviderCapability.CURRENT_PRICE,iid,'current_price',f'{iid} latest timestamped market price')
            selected=out.selected
            if selected.observation is not None and selected.freshness is not None and selected.freshness.status.value in {'FRESH','LAST_VALID_CLOSE'}:
                self.quotes[iid]=selected; self.refs.append(selected.evidence_id)
                obs=selected.observation
                self.lines.append(f'{iid}: {obs.value} {obs.currency}; quote_time={obs.observed_at}; retrieved={obs.retrieved_at}; freshness={selected.freshness.status.value}; delay={obs.metadata.get("delay_status","UNKNOWN")}; source={obs.source_url}. 실시간으로 보장하지 않습니다.')
            else:
                self.missing.append(f'{iid}:verified_quote'); self.lines.append(f'{iid}: 검증된 가격 없음; snapshot 가격을 현재가격으로 대체하지 않음.')
            # One compact snapshot per holding supplies the lightweight baseline.
            # This does not invoke Deep Research/Fundamental/Valuation engines.
            # Providers may return no supported score facts; those stay UNKNOWN.
            compact = self.collect(ProviderCapability.FUNDAMENTALS, iid, 'capital_lightweight',
                                   f'{iid} compact timestamped capital allocation metrics')
            context = self.run.fetch_phase6_context()
            from investment_stack.execution.capital_baseline import METRICS
            self.refs.extend(e['evidence_id'] for e in context['evidence']
                             if e.get('instrument_id') == iid and e.get('metric') in METRICS
                             and e.get('selection_state') == 'SELECTED')
            # Recent Event Discovery runs before Materiality Gate, across every equity.
            if self.instruments[iid]['asset_class']=='EQUITY':
                news=self.collect(ProviderCapability.NEWS,iid,'latest_relevant_news',f'{iid} recent material events')
                observations=news.selected.selected_observations
                material=[]
                for obs in observations:
                    published=obs.published_at or obs.event_time
                    if not published: continue
                    at=datetime.fromisoformat(published.replace('Z','+00:00'))
                    if not timedelta(0)<=cutoff-at<=timedelta(days=14): continue
                    if obs.metadata.get('material_event') is True or obs.metadata.get('potential_material_event') is True:
                        impact=classify_event_impact(obs.metadata.get('event_impact'))
                        self.run.record_task_state(task_name=f'event_impact:{iid}',task_status='PARTIAL' if impact.status=='WAIT' else 'COMPLETE',metadata={'event_impact_status':impact.status,'reason':impact.reason,'official_confirmation':obs.official_confirmation_status})
                        # A potentially material reported event drives research, not numeric valuation.
                        material.append(obs)
                        self.lines.append(f'{iid}: material event: {obs.headline}; published={published}; publication_precision={obs.metadata.get("published_time_precision","UNKNOWN")}; publication_time_upper_bound={obs.metadata.get("published_time_is_conservative_upper_bound",False)}; event_time={obs.event_time or "UNKNOWN"}; retrieved={obs.retrieved_at}; confirmation={obs.official_confirmation_status}; independent_verification={obs.metadata.get("independent_verification","UNKNOWN")}.')
                self.events[iid]=tuple(material)
                self.run.record_task_state(task_name=f'recent_event_discovery:{iid}',task_status='COMPLETE' if news.selected.observation else 'PARTIAL',
                    metadata={'material_events':len(material),'query':f'{iid} recent material events','coverage':'structured_web_bundle' if news.used_web_fallback else 'provider','missing_reason':None if news.selected.observation else 'news evidence absent'})
                if news.selected.evidence_id:self.refs.append(news.selected.evidence_id)
                if not news.selected.observation:self.missing.append(f'{iid}:recent_event_search_evidence')
        for pair in ('USD/KRW','JPY/KRW','USD/JPY'):
            out=self.collect(ProviderCapability.FX,pair,'fx_rate',f'{pair} latest timestamped FX quote')
            if out.selected.observation is not None and out.selected.freshness.status.value=='FRESH':
                self.fx[pair]=out.selected;self.refs.append(out.selected.evidence_id)
            else:self.missing.append(f'{pair}:verified_fx')
        if 'USD/KRW' in self.fx and 'JPY/KRW' in self.fx:
            try:
                obs=cross_fx(self.fx['USD/KRW'].observation,self.fx['JPY/KRW'].observation,
                    self.fx['USD/JPY'].observation if 'USD/JPY' in self.fx else None)
                selected=self.research.evidence.persist_and_select((ProviderResult('fx_cross',ProviderCapability.FX,ProviderStatus.AVAILABLE,(obs,)),),analysis_as_of=self.clock)
                self.refs.append(selected.evidence_id)
                self.calcs.append('calc:fx-cross')
                inputs=[self.fx[p].evidence_id for p in ('USD/KRW','JPY/KRW')]
                self.run.add_calculation(calculation_id='calc:fx-cross',calculation_name='fx_cross_sanity',formula='USD/KRW / JPY/KRW',inputs={'evidence_ids':inputs},result={'rate':str(obs.value),**obs.metadata})
                if 'USD/JPY' not in self.fx:self.fx['USD/JPY']=selected
                self.lines.append('FX cross sanity: '+json.dumps(obs.metadata,ensure_ascii=False))
            except ValueError as exc:
                self.missing.append('fx_cross_sanity:'+str(exc))
                # Fail closed: conflicting direct rates must not value this portfolio.
                self.fx.clear()
                self.run.record_task_state(task_name='fx_cross_sanity',task_status='PARTIAL',metadata={'reason':str(exc)})
        for pair, selected in self.fx.items():
            obs=selected.observation; self.lines.append(f'{pair}: {obs.value}; timestamp={obs.observed_at}; retrieved={obs.retrieved_at}; source={obs.source_url}; rate_type={obs.metadata.get("rate_type")}; freshness={selected.freshness.status.value}.')
        from investment_stack.execution.personal_outputs import render_personal_outputs
        personal_outputs = render_personal_outputs(self.run, self.ledger, self.projection,
            self.quotes, self.fx, self.snapshot, request.payload.get('evaluation_currency', 'KRW'), self.clock)
        self.calcs.extend(personal_outputs.calculation_refs)
        self.refs.extend(personal_outputs.evidence_refs)
        self.missing.extend(personal_outputs.missing_inputs)
        self.lines.append('Cash, cost basis and P&L: see persisted transaction calculation sections.')
        self.lines.append('Pinned investment rules: '+json.dumps(self.rules,ensure_ascii=False))
        for rule in (*self.rules,*self.external_rules):
            self.lines.append('특별 운용 규칙 우선 적용: '+json.dumps(rule,ensure_ascii=False))
        section=ReportSectionInput('lightweight_evidence','가격·FX·Recent Event Discovery',tuple(self.lines),status=Availability.PARTIAL if self.missing else Availability.AVAILABLE,evidence_ids=tuple(dict.fromkeys(self.refs)))
        return SelectedAssetResearchResult((section, *personal_outputs.sections),evidence_refs=tuple(dict.fromkeys(self.refs)),calculation_refs=tuple(self.calcs),missing_inputs=tuple(self.missing))

    def typed_fx(self):
        return tuple(FxEvidence(*pair.split('/'),Decimal(str(s.observation.value)),s.evidence_id,s.observation.observed_at,
            s.observation.published_at,'ELIGIBLE',s.freshness.status.value,True) for pair,s in self.fx.items())

    def select(self, portfolio, request):
        selected=[]
        for position in portfolio.positions:
            # Data incompleteness is evaluated by the existing gate, not silently skipped.
            light=LightweightAsset(position.instrument_id,self.quantities[position.instrument_id],None,None,None,
                Decimal('1') if position.market_value is None else Decimal('0'),
                strategic_relevance=bool(self.events.get(position.instrument_id)), user_specified=self.research_all_held)
            decision=self.analysis.materiality.evaluate(light)
            self.analysis._persist_materiality(decision)
            if decision.decision is not MaterialityDecision.FAIL:selected.append(position.instrument_id)
        return tuple(selected)

    def fund(self, iid):
        out=self.collect(ProviderCapability.FUND_HOLDINGS,iid,'fund_structure',f'{iid} issuer fund facts holdings benchmark')
        obs=out.selected.observation; md=obs.metadata if obs else {}; refs=(out.selected.evidence_id,) if out.selected.evidence_id else ()
        undated=tuple(o for result in out.provider_results for o in result.observations if o.metadata.get('data_time_unknown'))
        if undated:
            with closing(sqlite3.connect(self.run.database_path)) as c:
                refs=tuple(dict.fromkeys((*refs,*(r[0] for r in c.execute("select evidence_id from evidence where instrument_id=? and metric='fund_structure'",(iid,))))))
        def dec(key):
            val=md.get(key)
            if val is None:return None
            if isinstance(val,(bool,float)):raise ValueError('fund value must be exact')
            parsed=Decimal(str(val))
            if not parsed.is_finite():raise ValueError('fund value must be finite')
            return parsed
        holdings=tuple(FundHolding(str(h['instrument_id']),Decimal(str(h['weight'])),h.get('sector'),h.get('country'),h.get('currency')) for h in md.get('holdings',[]))
        quote=self.quotes.get(iid)
        if quote is not None:
            refs=tuple(dict.fromkeys((*refs, quote.evidence_id)))
        data=FundAnalysisInput(iid,Decimal(str(quote.observation.value)) if quote else None,
            dec('nav_per_share'),dec('expense_ratio'),dec('aum'),dec('average_daily_value'),holdings,md.get('holdings_as_of'),md.get('benchmark'),
            md.get('distribution_policy'),dec('tracking_difference'),evidence_ids=refs,
            market_price_as_of=quote.observation.observed_at if quote else None,
            nav_as_of=md.get('nav_as_of'),analysis_as_of=self.clock)
        self.fund_inputs[iid]=data
        result=self.analysis.analyze_fund(data)
        missing=list(result.unknowns)
        if out.selected.partial:missing.append('fund_structure_freshness')
        for field in ('benchmark','valuation','recent_performance','macro_risk','tracking_characteristics','currency_exposure'):
            if md.get(field) is None:missing.append(field)
        for metric in result.metrics:
            if metric.value is None:missing.append(metric.name)
        lines=(f'{iid}: FUND 분석 경로; 상태={result.status.value}; benchmark={md.get("benchmark","UNKNOWN")}; holdings_as_of={md.get("holdings_as_of","UNKNOWN")}.',
            'ETF 계산: '+json.dumps({m.name:{'value':m.value,'unit':m.unit,'reason':m.reason} for m in result.metrics},ensure_ascii=False,default=str),
            'ETF look-through: '+json.dumps(dict(result.metadata),ensure_ascii=False,default=str),
            '시점 미확인 ETF 출처(계산 미사용): '+json.dumps([{'source':o.source_url,'retrieved_at':o.retrieved_at,'metadata':o.metadata} for o in undated],ensure_ascii=False,default=str),
            '미확보: '+', '.join(sorted(set(missing))))
        calc=result.metadata['calculation_id']
        section=ReportSectionInput('fund_'+iid,'ETF/Fund '+iid,lines,status=Availability.PARTIAL if missing else Availability.AVAILABLE,evidence_ids=refs,calculation_ids=(calc,))
        return SelectedAssetResearchResult((section,),evidence_refs=refs,calculation_refs=(calc,),missing_inputs=tuple(iid+':'+k for k in sorted(set(missing))))
