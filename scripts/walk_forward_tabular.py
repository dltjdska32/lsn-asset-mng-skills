#!/usr/bin/env python3
from __future__ import annotations

import argparse, json
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from sklearn.metrics import mean_absolute_error
from xgboost import XGBRegressor
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from runtime.investment_stack.forecasting.dataset import enforce_point_in_time

def model_factory(name: str, seed: int):
    if name == "xgboost":
        return XGBRegressor(n_estimators=300,max_depth=4,learning_rate=0.04,subsample=0.8,colsample_bytree=0.8,objective="reg:squarederror",random_state=seed,n_jobs=1)
    if name == "lightgbm":
        return LGBMRegressor(n_estimators=300,num_leaves=31,learning_rate=0.04,subsample=0.8,colsample_bytree=0.8,random_state=seed,n_jobs=1,verbosity=-1)
    raise ValueError(name)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--csv',required=True); ap.add_argument('--features',required=True)
    ap.add_argument('--target',default='future_cagr_5y'); ap.add_argument('--date-col',default='as_of')
    ap.add_argument('--label-available-col',default='future_as_of')
    ap.add_argument('--model',choices=['xgboost','lightgbm'],default='xgboost')
    ap.add_argument('--min-train-years',type=int,default=8); ap.add_argument('--test-years',type=int,default=1)
    ap.add_argument('--seed',type=int,default=7); ap.add_argument('--output',required=True)
    a=ap.parse_args(); features=[x.strip() for x in a.features.split(',') if x.strip()]
    df=pd.read_csv(a.csv)
    
    forbidden_features = {'label', 'future_price', 'target', 'date', 'as_of', 'future_as_of', 'instrument_id'}
    if any(f in forbidden_features for f in features):
        raise SystemExit(f'Forbidden feature detected in: {features}')
    
    pub_cols = [f"{f}_published_at" for f in features]
    unit_cols = [f"{f}_units" for f in features]
    chk = enforce_point_in_time(df, as_of_col=a.date_col, published_at_cols=pub_cols, target_col=a.target, instrument_col='instrument_id')
    if not chk.ok: raise SystemExit(f'PIT violations: {chk.details}')
    
    required=['instrument_id',a.date_col,a.label_available_col,a.target,*features,*pub_cols,*unit_cols]
    missing=[c for c in required if c not in df.columns]
    if missing: raise SystemExit(f'missing columns: {missing}')
    for c in required:
        if df[c].isna().any():
            raise SystemExit(f'missing/NaN values found in required column: {c}')
            
    df=df.copy()
    df['_date']=pd.to_datetime(df[a.date_col],utc=True); 
    df['_label_avail']=pd.to_datetime(df[a.label_available_col],utc=True)
    df=df.sort_values('_date')
    
    start=df['_date'].min()+pd.DateOffset(years=a.min_train_years); end=df['_date'].max()
    folds=[]; preds=[]; cutoff=start
    while cutoff < end:
        # Require calibration window for true OOS.
        cal_end = cutoff + pd.DateOffset(years=1)
        test_end = cal_end + pd.DateOffset(years=a.test_years)
        from runtime.investment_stack.forecasting.dataset import purged_time_split
        try:
            splits = purged_time_split(df, date_col='_date', label_avail_col='_label_avail', fit_cutoff=cutoff, calibration_cutoff=cal_end, evaluation_cutoff=test_end)
            tr, te = splits.train, splits.test
        except ValueError:
            cutoff = test_end
            continue

        if len(tr)>=100 and len(te)>0:
            m=model_factory(a.model,a.seed); m.fit(tr[features].astype(float),tr[a.target].astype(float))
            p=np.asarray(m.predict(te[features].astype(float)),dtype=float); y=te[a.target].astype(float).to_numpy()
            fold={"train_end":str(cutoff.date()),"test_end":str(test_end.date()),"n_train":len(tr),"n_test":len(te),"mae":float(mean_absolute_error(y,p)),"directional_accuracy":float(np.mean(np.sign(y)==np.sign(p)))}
            folds.append(fold)
            for idx, pred in zip(te.index,p): preds.append({"index":int(idx),"as_of":str(te.loc[idx,'_date'].date()),"actual":float(te.loc[idx,a.target]),"predicted":float(pred)})
        cutoff=test_end
    if not folds: raise SystemExit('no valid walk-forward folds')
    actual=np.array([x['actual'] for x in preds]); predicted=np.array([x['predicted'] for x in preds])
    result={"model":f"{a.model}-tabular-5y","folds":folds,"aggregate":{"n":len(preds),"mae":float(mean_absolute_error(actual,predicted)),"directional_accuracy":float(np.mean(np.sign(actual)==np.sign(predicted)))},"predictions":preds}
    with open(a.output,'w') as f: json.dump(result,f,indent=2)
    print(json.dumps({"model":a.model,"aggregate":result['aggregate'],"fold_count":len(folds)},indent=2))
if __name__=='__main__': main()
