from pathlib import Path
import pandas as pd
import json, hashlib
import numpy as np
from xgboost import XGBRegressor

from investment_stack.forecasting.adapters.tabular_ml import TabularMLAdapter
from investment_stack.forecasting.contracts import ForecastRequest


def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def make_artifact(tmp_path: Path):
    d=tmp_path/'xgb'; d.mkdir(); model=XGBRegressor(n_estimators=1,max_depth=1,learning_rate=0.1,n_jobs=1).fit(np.array([[1.0],[2.0],[3.0]]),np.array([0.10,0.10,0.10])); mf=d/'model.json'; model.save_model(mf)
    meta={'model_type':'xgboost','model_id':'xgboost-tabular-5y','feature_names':['f1'],'feature_schema':{'f1':{'unit':'USD'}},'schema_version':1,'target':'future_cagr_5y','target_kind':'price_cagr','target_unit':'annual_decimal','currency':'USD','price_basis':'split-adjusted','horizon_years':5.0,'frequency':'ME','horizon_steps':60,'provenance':'REAL','oos_metrics':{'validation':{'n':10},'test':{'mae':0.1}},'model_file':'model.json','model_sha256':sha(mf),'residual_quantiles':{'0.1':-0.1,'0.25':-0.05,'0.5':0.0,'0.75':0.05,'0.9':0.1}, 'training_cutoff': '2024-01-01T00:00:00Z', 'validation_cutoff': '2024-06-01T00:00:00Z', 'evaluation_cutoff': '2025-01-01T00:00:00Z'}
    (d/'metadata.json').write_text(json.dumps(meta)); return d

def test_tabular_ml_adapter_complete(tmp_path: Path):
    from datetime import datetime, timezone
    d=make_artifact(tmp_path); req=ForecastRequest(instrument_id='X', currency='USD', as_of=datetime(2025,1,1,tzinfo=timezone.utc), current_price=100.0, target_date=datetime(2029,12,31,tzinfo=timezone.utc), horizon_steps=60,frequency='ME',target='Close',history=[100.0]*12,timestamps=list(pd.date_range(end='2024-12-31',periods=12,freq='ME',tz='UTC').to_pydatetime()),metadata={'price_basis':'split-adjusted','ml_feature_units':{'f1':'USD'},'ml_features':{'f1':1.0},'ml_feature_timestamps':{'f1':'2024-12-01T00:00:00Z'}}); out=TabularMLAdapter(d).forecast(req); assert out.status=='COMPLETE'; assert out.point>0

def test_tabular_ml_adapter_missing_feature_fails_closed(tmp_path: Path):
    from datetime import datetime, timezone
    d=make_artifact(tmp_path); req=ForecastRequest(instrument_id='X', currency='USD', as_of=datetime(2025,1,1,tzinfo=timezone.utc), current_price=100.0, target_date=datetime(2029,12,31,tzinfo=timezone.utc), horizon_steps=60,frequency='ME',target='Close',history=[100.0]*12,timestamps=list(pd.date_range(end='2024-12-31',periods=12,freq='ME',tz='UTC').to_pydatetime()),metadata={'ml_features':{}}); out=TabularMLAdapter(d).forecast(req); assert out.status=='UNAVAILABLE'

def test_tabular_ml_hash_mismatch_fails_closed(tmp_path: Path):
    d=make_artifact(tmp_path); (d/'model.json').write_text('tampered'); ok,reason=TabularMLAdapter(d).available(); assert not ok; assert 'SHA-256' in reason
