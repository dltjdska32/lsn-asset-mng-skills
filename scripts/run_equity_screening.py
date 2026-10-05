"""Explicit 20-100 equity universe, lightweight pass, then existing Top N pipelines."""
import argparse
from contextlib import closing
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo
from investment_stack.screening import ScreeningCandidate, screen_equities
from investment_stack.providers import ProviderRequest, ProviderCapability
from investment_stack.providers.instruments import InstrumentResolver
from investment_stack.providers.factory import build_default_provider_executor
from investment_stack.providers.http import urllib_transport
from investment_stack.research import Phase4ResearchRuntime
from investment_stack.evidence import RunDatabaseManager, EvidenceResearchStore
from investment_stack.deep_research import LiveDeepResearchRuntime
from investment_stack.asset_analysis import Phase5AssetAnalysisRuntime
from investment_stack.materiality import MaterialityEngine, MaterialityConfig
from investment_stack.execution.host import open_personal_ledger, compose_configured_host
from investment_stack.execution import ModeRequest, execute_mode
from investment_stack.routing import RequestMode


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--asset', action='append', required=True)
    p.add_argument('--personal-db', type=Path, required=True)
    p.add_argument('--run-workspace', type=Path, required=True)
    p.add_argument('--weights-json', type=Path)
    p.add_argument('--top-n', type=int, default=10)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    clock = datetime.now(ZoneInfo('Asia/Seoul')).isoformat()
    run = RunDatabaseManager(a.run_workspace, 'screen-' + datetime.now().strftime('%Y%m%d%H%M%S'))
    if not run.create().valid: raise RuntimeError('screen run creation failed')
    run.initialize_run_context(request_mode=RequestMode.ASSET_COMPARISON.value,
                               analysis_as_of=clock, analysis_timezone='Asia/Seoul',
                               state_version=0, personal_db_instance_id='NONE:SCREENING')
    resolver = InstrumentResolver(transport=urllib_transport)
    specs, excluded_identity = {}, {}
    for iid in a.asset:
        try: specs[iid] = resolver.resolve(iid).equity_spec()
        except ValueError: excluded_identity[iid] = 'identity_unavailable'
    providers = build_default_provider_executor(transport=urllib_transport, instrument_resolver=resolver)
    research = Phase4ResearchRuntime(providers=providers, evidence=EvidenceResearchStore(run))
    analysis = Phase5AssetAnalysisRuntime(run, materiality=MaterialityEngine(MaterialityConfig('screening', Decimal('.05'), Decimal('.2'), Decimal('.8'))))
    deep = LiveDeepResearchRuntime(research=research, analysis=analysis, analysis_as_of=clock, analysis_timezone='Asia/Seoul')
    candidates = []
    for iid in a.asset:
        metrics, refs = {}, ()
        if iid in specs:
            spec = specs[iid]
            financial = research.collect(ProviderRequest(ProviderCapability.FUNDAMENTALS, clock, 'Asia/Seoul', iid, 'fundamentals', dict(spec.fundamentals_parameters or {})))
            values, warnings = deep._normalize_financials(financial, target_currency=spec.currency)
            refs = tuple(r['evidence_id'] for r in run.fetch_evidence_rows() if r.get('instrument_id') == iid and r.get('selection_state') == 'SELECTED')
            # Only derived ratios of exact same-period inputs; qualitative scores require explicit evidence.
            if values.get('revenue') not in (None, Decimal('0')):
                if values.get('operating_income') is not None: metrics['financial_quality'] = values['operating_income'] / values['revenue']
                if values.get('prior_revenue') not in (None, Decimal('0')): metrics['growth'] = values['revenue'] / values['prior_revenue'] - 1
            if values.get('equity') not in (None, Decimal('0')) and values.get('total_debt') is not None:
                metrics['risk'] = values['total_debt'] / values['equity']
            if values.get('market_cap') not in (None, Decimal('0')) and values.get('cash_from_operations') is not None and values.get('capex') is not None:
                metrics['valuation'] = (values['cash_from_operations'] - values['capex']) / values['market_cap']
        candidates.append(ScreeningCandidate(iid, metrics, refs, clock))
    weights = json.loads(a.weights_json.read_text(), parse_float=Decimal) if a.weights_json else {'growth': '0.35', 'valuation': '0.25', 'financial_quality': '0.15', 'competitive_position': '0.15', 'risk': '-0.10'}
    weights = {k: Decimal(str(v)) for k, v in weights.items()}
    ledger = open_personal_ledger(a.personal_db)
    with closing(sqlite3.connect(a.personal_db)) as c:
        pin = c.execute('select snapshot_id,state_version,as_of from portfolio_snapshots order by state_version desc,rowid desc limit 1').fetchone()
    def analyze(iid, mode):
        child = RunDatabaseManager(a.run_workspace, run.run_id + '-' + iid)
        if not child.create().valid: raise RuntimeError('child run creation failed')
        child.initialize_run_context(request_mode=mode.value, analysis_as_of=clock, analysis_timezone='Asia/Seoul',
                                     state_version=pin[1], personal_db_instance_id=ledger.manager.instance_id,
                                     portfolio_snapshot_id=pin[0], portfolio_data_as_of=pin[2])
        services = compose_configured_host(child, ledger, live_providers=True)
        return execute_mode(ModeRequest(child.run_id, mode, {'assets': [{'instrument_id': iid}]}), services).as_dict()
    result = screen_equities(tuple(candidates), metric_weights=weights, top_n=a.top_n, as_of=clock, deep_research=analyze)
    run.finish_run('PARTIAL' if result.excluded else 'COMPLETE')
    out = asdict(result)
    out.update(run_id=run.run_id, run_db_path=str(run.database_path), universe_count=len(a.asset), identity_failures=excluded_identity,
               expected_5y_cagr='UNAVAILABLE: explicit earnings growth and terminal multiple assumptions required',
               availability='PARTIAL' if result.excluded else 'COMPLETE')
    a.output.write_text(json.dumps(out, default=str, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({'run_id': run.run_id, 'universe': len(a.asset), 'ranked': len(result.ranked), 'deep': len(result.deep_research), 'excluded': len(result.excluded)}))


if __name__ == '__main__': main()
