#!/usr/bin/env python3
"""Capture current market payloads for the supplied DB's actual held universe."""
import argparse,json,sqlite3
from pathlib import Path
from investment_stack.providers.capture import capture_market_data
from investment_stack.providers.instruments import InstrumentResolver
from investment_stack.providers.http import urllib_transport
p=argparse.ArgumentParser();p.add_argument('--output-dir',required=True)
p.add_argument('--personal-db',type=Path);p.add_argument('--instrument-registry',type=Path)
p.add_argument('--asset',action='append',default=[])
a=p.parse_args();listings={};failures={}
if a.personal_db:
    resolver=InstrumentResolver.from_database(a.personal_db,registry_path=a.instrument_registry,transport=urllib_transport)
    with sqlite3.connect(a.personal_db) as c:
        held=tuple(r[0] for r in c.execute("select distinct instrument_id from positions where CAST(quantity_decimal as NUMERIC)!=0"))
    listings={iid:v.listing_id for iid,v in resolver.portfolio(held).items()};failures=resolver.failures
else:
    resolver=InstrumentResolver(transport=urllib_transport)
for iid in a.asset:
    try:listings[iid]=resolver.resolve(iid).listing_id
    except ValueError as exc:failures[iid]=str(exc)
result=capture_market_data(a.output_dir,listings=listings)
print(json.dumps({'captured':sum(r['status']=='CAPTURED' for r in result['records']),
                 'total':len(result['records']),'captured_at':result['captured_at'],
                 'instrument_resolution_failures':failures},indent=2))
