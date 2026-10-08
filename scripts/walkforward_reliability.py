#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from investment_stack.forecasting.backtest import reliability_from_walkforward_results


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('json_files',nargs='+'); ap.add_argument('--output')
    a=ap.parse_args(); comparable={}
    for fp in a.json_files:
        obj=json.loads(Path(fp).read_text())
        model=str(obj.get('model'))
        agg=obj.get('aggregate') or {}
        comparable[model]={'mae':agg.get('mae'),'directional_accuracy':agg.get('directional_accuracy')}
    out={'inputs':comparable,'relative_reliability':dict(reliability_from_walkforward_results(comparable))}
    text=json.dumps(out,indent=2,sort_keys=True)
    if a.output: Path(a.output).write_text(text+'\n')
    print(text)
if __name__=='__main__': main()
