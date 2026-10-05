#!/usr/bin/env python3
"""Create, pin, and execute a configured PERSONAL_PORTFOLIO_ANALYSIS run."""
from __future__ import annotations
from contextlib import closing
import argparse, hashlib, json, sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from investment_stack.evidence import RunDatabaseManager
from investment_stack.execution.dispatcher import execute_mode
from investment_stack.execution.host import compose_configured_host, open_personal_ledger
from investment_stack.execution.models import ModeRequest
from investment_stack.routing.models import RequestMode

def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument('--personal-db', type=Path, required=True)
    p.add_argument('--run-workspace', type=Path, required=True)
    p.add_argument('--run-id')
    p.add_argument('--timezone', default='Asia/Seoul')
    p.add_argument('--evaluation-currency', default='KRW')
    p.add_argument('--web-research-bundle', type=Path)
    p.add_argument('--live-providers', action='store_true')
    p.add_argument('--special-rules', type=Path)
    p.add_argument('--include-reference-assets', action='store_true')
    p.add_argument('--market-captures', type=Path)
    p.add_argument('--research-all-held', action='store_true')
    p.add_argument('--authoritative-zip', type=Path)
    p.add_argument('--report-output', type=Path)
    p.add_argument('--instrument-registry', type=Path)
    p.add_argument('--offline-captures', action='store_true')
    p.add_argument('--previous-run-db', type=Path)
    a=p.parse_args()
    now=datetime.now(ZoneInfo(a.timezone))
    run_id=a.run_id or 'portfolio-'+now.strftime('%Y%m%d%H%M%S')
    ledger=open_personal_ledger(a.personal_db)
    with closing(sqlite3.connect(a.personal_db)) as c, c:
        c.row_factory=sqlite3.Row
        row=c.execute('SELECT snapshot_id,state_version,as_of FROM portfolio_snapshots ORDER BY state_version DESC,rowid DESC LIMIT 1').fetchone()
    if row is None: raise RuntimeError('personal.db has no portfolio snapshot')
    run=RunDatabaseManager(a.run_workspace,run_id)
    report=run.create()
    if not report.valid: raise RuntimeError('; '.join(report.errors))
    run.initialize_run_context(request_mode=RequestMode.PERSONAL_PORTFOLIO_ANALYSIS.value,
        analysis_as_of=now.isoformat(), analysis_timezone=a.timezone,
        state_version=int(row['state_version']), personal_db_instance_id=ledger.manager.instance_id,
        portfolio_snapshot_id=str(row['snapshot_id']), portfolio_data_as_of=str(row['as_of']))
    rules=json.loads(a.special_rules.read_text()) if a.special_rules else []
    transport=None
    if a.market_captures:
        from investment_stack.providers.capture import CapturedMarketTransport
        transport=CapturedMarketTransport(a.market_captures,allow_live_fallback=not a.offline_captures)
    services=compose_configured_host(run,ledger,web_research_bundle=a.web_research_bundle,live_providers=a.live_providers,transport=transport,special_rules=rules,include_reference_assets=a.include_reference_assets,research_all_held=a.research_all_held,instrument_registry=a.instrument_registry,previous_run_db=a.previous_run_db)
    request=ModeRequest(run_id,RequestMode.PERSONAL_PORTFOLIO_ANALYSIS,
        {'portfolio_source':'pinned_ledger','evaluation_currency':a.evaluation_currency.upper()})
    result=execute_mode(request,services)
    out=result.as_dict(); out['run_id']=run_id
    out['pinned_state']={'state_version':int(row['state_version']),'snapshot_id':str(row['snapshot_id']),
                         'portfolio_data_as_of':str(row['as_of']),'personal_db_instance_id':ledger.manager.instance_id}
    with closing(sqlite3.connect(run.database_path)) as c, c:
        c.row_factory=sqlite3.Row
        quotes=[dict(r) for r in c.execute("select instrument_id,value_text as value,currency,observed_at,retrieved_at,freshness_status,source_uri,metadata_json from evidence where metric='current_price' and selection_state='SELECTED'")]
        fx=[dict(r) for r in c.execute("select instrument_id,value_text as value,observed_at,retrieved_at,freshness_status,metadata_json from evidence where metric='fx_rate' and selection_state='SELECTED'")]
        evidence_count=c.execute('select count(*) from evidence').fetchone()[0]
        research_count=c.execute("select count(*) from evidence where evidence_type in ('news','financial','fund','macro')").fetchone()[0]
        selected_assets=[r[0] for r in c.execute("select subject from materiality_decisions where decision != 'FAIL' order by subject")]
        tasks=[dict(r) for r in c.execute('select task_name,task_status,metadata_json from task_states')]
    with closing(sqlite3.connect(a.personal_db)) as c, c:
        held=[r[0] for r in c.execute("select distinct instrument_id from positions where CAST(quantity_decimal as NUMERIC) != 0 order by instrument_id")]
        schema=c.execute('select max(version) from schema_migrations').fetchone()[0]
    priced={r['instrument_id'] for r in quotes}
    out['verification']={
        'authoritative_zip_sha256':hashlib.sha256(a.authoritative_zip.read_bytes()).hexdigest() if a.authoritative_zip else None,
        'runtime_path':str(Path(__file__).resolve().parents[1] / 'runtime' / 'investment_stack'),
        'personal_db_path':str(a.personal_db.resolve()),'run_db_path':str(run.database_path),
        'personal_schema_version':schema,'held_assets':held,'held_count':len(held),
        'selected_deep_research_assets':sorted(set(selected_assets)),
        'market_quote_status':'COMPLETE' if set(held)<=priced else 'PARTIAL',
        'missing_held_quotes':sorted(set(held)-priced),'quotes':quotes,
        'fx_status':'COMPLETE' if {'USD/KRW','JPY/KRW','USD/JPY'}<={r['instrument_id'] for r in fx} and not any('fx_cross_sanity:' in item for item in result.missing_inputs) else 'PARTIAL',
        'fx':fx,'evidence_count':evidence_count,'research_evidence_count':research_count,'task_states':tasks,
    }
    if a.report_output:
        report=result.step_states[-1].result.output.get('report') if result.step_states else None
        if report is not None:
            a.report_output.parent.mkdir(parents=True,exist_ok=True)
            a.report_output.write_text(report.markdown,encoding='utf-8')
            out['verification']['report_path']=str(a.report_output.resolve())
    print(json.dumps(out,ensure_ascii=False,indent=2,default=str))
    return 0 if result.availability.value in {'COMPLETE','PARTIAL'} else 3
if __name__=='__main__': raise SystemExit(main())
