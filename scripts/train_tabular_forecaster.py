#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
import numpy as np, pandas as pd
from lightgbm import LGBMRegressor
from sklearn.metrics import mean_absolute_error
from xgboost import XGBRegressor
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from runtime.investment_stack.forecasting.dataset import enforce_point_in_time

def sha256(path: Path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def directional_accuracy(y,p): return float(np.mean(np.sign(y)==np.sign(p))) if len(y) else float('nan')

def metrics(model,df,features,target):
    if df.empty:return {'n':0,'mae':None,'directional_accuracy':None}
    y=df[target].astype(float).to_numpy(); p=np.asarray(model.predict(df[features].astype(float)),dtype=float)
    return {'n':int(len(df)),'mae':float(mean_absolute_error(y,p)),'directional_accuracy':directional_accuracy(y,p)}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--csv',required=True); ap.add_argument('--output-dir',required=True)
    ap.add_argument('--features',required=True); ap.add_argument('--target',default='future_cagr_5y')
    ap.add_argument('--feature-schema',default=None, help="JSON file explaining each selected feature")
    ap.add_argument('--date-col',default='as_of'); ap.add_argument('--label-available-col',default='future_as_of')
    ap.add_argument('--train-end',required=True); ap.add_argument('--valid-end',required=True)
    ap.add_argument('--eval-end',default=None)
    ap.add_argument('--horizon-years',type=float,default=5.0)
    ap.add_argument('--currency',required=True); ap.add_argument('--price-basis',required=True,choices=['nominal','real','split-adjusted'])
    ap.add_argument('--provenance',required=True, choices=['SYNTHETIC', 'LIVE', 'HISTORICAL_PUBLISHED'])
    ap.add_argument('--seed',type=int,default=7); a=ap.parse_args()
    
    if not a.feature_schema:
        raise SystemExit("publication schema whitelist explaining each selected feature is required")
    schema_path = Path(a.feature_schema)
    if not schema_path.exists(): raise SystemExit(f"Schema file not found: {schema_path}")
    schema_data = json.loads(schema_path.read_text())
    
    features=[x.strip() for x in a.features.split(',') if x.strip()]; df=pd.read_csv(a.csv)
    
    for f in features:
        if f not in schema_data:
            raise SystemExit(f"Feature {f} not documented in schema whitelist")
        if 'unit' not in schema_data[f] or not schema_data[f]['unit']:
            raise SystemExit(f'Feature {f} lacks declared unit')
        if 'description' not in schema_data[f] or not schema_data[f]['description']:
            raise SystemExit(f"Feature {f} lacks explanation/description in schema")
    
    if a.target != f'future_cagr_{int(a.horizon_years)}y' or a.horizon_years != int(a.horizon_years):
        raise SystemExit('target/horizon must bind to price CAGR years')
    forbidden_features = {'label', 'future_price', 'target', 'date', 'as_of', 'future_as_of', 'instrument_id', a.target}
    if any(f in forbidden_features or any(x in f.lower() for x in ('future','outcome','target','label','forward','next_')) for f in features):
        raise SystemExit(f'Forbidden or outcome feature detected in: {features}')
        
    pub_cols = [f"{f}_published_at" for f in features]
    unit_cols = [f"{f}_units" for f in features]
    
    # Enforce point-in-time
    chk = enforce_point_in_time(df, as_of_col=a.date_col, published_at_cols=pub_cols, target_col=a.target, instrument_col='instrument_id')
    if not chk.ok: raise SystemExit(f'PIT violations: {chk.details}')
    
    if not a.eval_end:
        raise SystemExit("eval-end is required")
        
    required=['instrument_id',a.date_col,a.label_available_col,a.target,*features,*pub_cols,*unit_cols]
    missing=[c for c in required if c not in df.columns]
    if missing: raise SystemExit(f'missing columns: {missing}')
    
    # Do not silently drop malformed rows
    for c in required:
        if df[c].isna().any():
            raise SystemExit(f'missing/NaN values found in required column: {c}')
            
    if df['instrument_id'].astype(str).str.strip().eq('').any():
        raise SystemExit("Empty identifiers found")
        
    for f in features:
        units = df[f"{f}_units"].unique()
        if len(units) != 1 or str(units[0]) != schema_data[f]['unit']:
            raise SystemExit(f'Feature {f} unit differs from schema')
        if len(units) > 1: raise SystemExit(f"Inconsistent units for feature {f}: {units}")
        if not np.isfinite(pd.to_numeric(df[f], errors='coerce')).all():
            raise SystemExit(f"Non-finite values in feature {f}")
            
    if not np.isfinite(pd.to_numeric(df[a.target], errors='coerce')).all():
        raise SystemExit(f"Non-finite values in target {a.target}")
        
    obs_date = pd.to_datetime(df[a.date_col], utc=True)
    avail_date = pd.to_datetime(df[a.label_available_col], utc=True)
    # Calendar-year target is mature at the same calendar date N years later.
    # Do not approximate calendar years using 365 days: leap years matter.
    # Realized annualized CAGR elsewhere uses actual elapsed days / 365.25.
    if float(a.horizon_years).is_integer():
        maturity = obs_date + pd.DateOffset(years=int(a.horizon_years))
    else:
        maturity = obs_date + pd.Timedelta(days=365.25 * a.horizon_years)
    if (avail_date < maturity).any():
        raise SystemExit("Label availability is before the required horizon maturity")
    
    clean=df.copy()
    from runtime.investment_stack.forecasting.dataset import purged_time_split
    splits = purged_time_split(clean, date_col=a.date_col, label_avail_col=a.label_available_col, fit_cutoff=a.train_end, calibration_cutoff=a.valid_end, evaluation_cutoff=a.eval_end)
    tr, va, te = splits.train, splits.valid, splits.test
    if len(tr)<100: raise SystemExit('need at least 100 training rows')
    
    models={
      'xgboost':XGBRegressor(n_estimators=500,max_depth=5,learning_rate=0.03,subsample=0.8,colsample_bytree=0.8,reg_lambda=1.0,objective='reg:squarederror',random_state=a.seed,n_jobs=1),
      'lightgbm':LGBMRegressor(n_estimators=500,num_leaves=31,learning_rate=0.03,subsample=0.8,colsample_bytree=0.8,reg_lambda=1.0,random_state=a.seed,n_jobs=1,verbosity=-1),
    }
    out=Path(a.output_dir); out.mkdir(parents=True,exist_ok=True); summary={'splits':{'train':len(tr),'valid':len(va),'test':len(te)},'models':{}}
    for name,model in models.items():
        model.fit(tr[features].astype(float),tr[a.target].astype(float)); vm=metrics(model,va,features,a.target); tm=metrics(model,te,features,a.target)
        residuals=np.asarray(va[a.target]-model.predict(va[features].astype(float))) if not va.empty else np.array([])
        rqs={str(q):float(np.quantile(residuals,q)) for q in (0.1,0.25,0.5,0.75,0.9)} if len(residuals) else {}
        d=out/name; d.mkdir(exist_ok=True)
        if name=='xgboost':
            model_file=d/'model.json'; model.save_model(model_file); serialization='xgboost-json'
        else:
            model_file=d/'model.txt'; model.booster_.save_model(str(model_file)); serialization='lightgbm-text'
        meta={
            'schema_version':1,'target_kind':'price_cagr','target_unit':'annual_decimal',
            'currency':a.currency,'price_basis':a.price_basis,
            'feature_schema':{f:schema_data[f] for f in features},
            'model_type':name,'model_id':f'{name}-tabular-{int(a.horizon_years)}y',
            'feature_names':features,'target':a.target,'horizon_years':int(a.horizon_years),
            'frequency':'ME','horizon_steps':int(a.horizon_years)*12,
            'feature_units':[str(df[f"{f}_units"].iloc[0]) if f"{f}_units" in df.columns else "unknown" for f in features],
            'training_cutoff':a.train_end,'validation_cutoff':a.valid_end,
            'evaluation_cutoff':a.eval_end,
            'oos_metrics':{'validation':vm,'test':tm},'residual_quantiles':rqs,
            'provenance':a.provenance,
            'authenticity':'unverified',
            'model_file':model_file.name,'model_sha256':sha256(model_file),'serialization':serialization
        }
        (d/'metadata.json').write_text(json.dumps(meta,indent=2,sort_keys=True)+'\n')
        summary['models'][name]={'validation':vm,'test':tm,'artifact':str(d),'model_sha256':meta['model_sha256'],'serialization':serialization}
    (out/'training_summary.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n'); print(json.dumps(summary,indent=2,sort_keys=True))
if __name__=='__main__':main()
