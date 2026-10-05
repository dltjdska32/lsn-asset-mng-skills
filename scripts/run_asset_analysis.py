from contextlib import closing
#!/usr/bin/env python3
"""Run actual single-asset/comparison Fixed Pipelines with generic identity inputs."""
import argparse,json,sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from investment_stack.evidence import RunDatabaseManager
from investment_stack.execution.host import compose_configured_host,open_personal_ledger
from investment_stack.execution.dispatcher import execute_mode
from investment_stack.execution.models import ModeRequest
from investment_stack.routing import RequestMode

def main():
 p=argparse.ArgumentParser();p.add_argument('--personal-db',type=Path,required=True);p.add_argument('--run-workspace',type=Path,required=True)
 p.add_argument('--asset',action='append',default=[]);p.add_argument('--assets-json',type=Path)
 p.add_argument('--run-id');p.add_argument('--timezone',default='Asia/Seoul');p.add_argument('--live-providers',action='store_true')
 p.add_argument('--offline-captures',action='store_true')
 p.add_argument('--market-captures',type=Path);p.add_argument('--web-research-bundle',type=Path);p.add_argument('--instrument-registry',type=Path)
 p.add_argument('--previous-run-db',type=Path)
 p.add_argument('--portfolio-context',action='store_true')
 p.add_argument('--evaluation-currency',default='KRW')
 a=p.parse_args();assets=json.loads(a.assets_json.read_text()) if a.assets_json else [{'instrument_id':v} for v in a.asset]
 if not assets:p.error('at least one explicit asset is required')
 mode=RequestMode.SINGLE_ASSET_ANALYSIS if len(assets)==1 else RequestMode.ASSET_COMPARISON
 ledger=open_personal_ledger(a.personal_db);now=datetime.now(ZoneInfo(a.timezone));rid=a.run_id or 'assets-'+now.strftime('%Y%m%d%H%M%S')
 with closing(sqlite3.connect(a.personal_db)) as c, c:pin=c.execute('select snapshot_id,state_version,as_of from portfolio_snapshots order by state_version desc,rowid desc limit 1').fetchone()
 if pin is None:raise ValueError('authoritative personal snapshot required')
 run=RunDatabaseManager(a.run_workspace,rid)
 if not run.create().valid:raise ValueError('run creation failed')
 run.initialize_run_context(request_mode=mode.value,analysis_as_of=now.isoformat(),analysis_timezone=a.timezone,state_version=pin[1],personal_db_instance_id=ledger.manager.instance_id,portfolio_snapshot_id=pin[0],portfolio_data_as_of=pin[2])
 transport=None
 if a.market_captures:
  from investment_stack.providers.capture import CapturedMarketTransport
  transport=CapturedMarketTransport(a.market_captures,allow_live_fallback=not a.offline_captures)
 host=compose_configured_host(run,ledger,live_providers=a.live_providers,transport=transport,web_research_bundle=a.web_research_bundle,instrument_registry=a.instrument_registry,previous_run_db=a.previous_run_db)
 result=execute_mode(ModeRequest(rid,mode,{'assets':assets,'portfolio_context':a.portfolio_context,
   'evaluation_currency':a.evaluation_currency.upper()}),host);out=result.as_dict();out['run_id']=rid;out['run_db_path']=str(run.database_path)
 with closing(sqlite3.connect(run.database_path)) as c, c:
  c.row_factory=sqlite3.Row
  out['selected_quotes']=[dict(r) for r in c.execute("select instrument_id,value_text,currency,observed_at,retrieved_at,freshness_status,source_uri from evidence where metric='current_price' and selection_state='SELECTED'")]
  out['evidence_count']=c.execute('select count(*) from evidence').fetchone()[0]
 print(json.dumps(out,ensure_ascii=False,indent=2,default=str));return 0 if result.availability.value in {'COMPLETE','PARTIAL'} else 3
if __name__=='__main__':raise SystemExit(main())
