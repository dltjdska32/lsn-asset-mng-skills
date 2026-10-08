"""SYNTHETIC acceptance regressions for the four browser05 P1 findings.

Reviewer probes under workspace/cache are immutable, and no real accounts,
weights, credentials, networks, or deployment are exercised here.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess

import numpy as np
import pandas as pd
import pytest

from investment_stack.forecasting.adapters.tabular_ml import TabularMLAdapter
from investment_stack.forecasting.contracts import EnsembleForecast, FundamentalAnchor, ModelForecast
from investment_stack.forecasting.ensemble import ForecastEnsembler
from investment_stack.forecasting.integrity import verify_kronos_source
from investment_stack.forecasting.store import ForecastStore
from test_browser03_persistence import canonical, request, anchor, FakeAdapter, model_links


def peer(point=100., *, basis='split-adjusted'):
    req=request()
    return ModelForecast(model_id='xgboost-tabular-5y', status='COMPLETE', instrument_id='X',
        currency='USD', as_of=req.as_of, target_date=req.target_date,
        price_basis=basis, horizon_steps=req.horizon_steps, frequency=req.frequency,
        point=point, quantiles={0.1:point*0.8,0.9:point*1.2},
        details={'provenance':'SYNTHETIC', 'model_revision':'test'},
    )


@pytest.mark.parametrize('invalid', [
    'wrong_kind','future','missing_time','wrong_id','currency','basis','status','nan','bad_refs',
])
def test_rejected_anchor_never_poison_peers_or_output_basis(invalid):
    req=request()
    good=anchor()
    overrides={
        'wrong_kind':{'value_kind':'current_fair_value','base':1000.},
        'future':{'as_of':datetime(2026, 1, 1, tzinfo=timezone.utc), 'base':1000.},
        'missing_time':{'as_of':None, 'base':1000.},
        'wrong_id':{'instrument_id':'Y','base':1000.},
        'currency':{'currency':'EUR','base':1000.},
        'basis':{'price_basis':'nominal','base':1000.},
        'status':{'status':'UNAVAILABLE','base':1000.},
        'nan':{'base':float('nan')},
        'bad_refs':{'evidence_refs':(), 'base':1000.},
    }
    bad=replace(good, **overrides[invalid])
    out=ForecastEnsembler().combine(req,[peer()],bad)
    assert out.status == 'PARTIAL'
    assert out.point == pytest.approx(100.)
    assert out.price_basis == 'split-adjusted'
    assert out.anchor is None
    assert out.component_weights == {'xgboost-tabular-5y':1.}
    assert out.details['excluded'].get('fundamental-anchor')


def test_engine_rejected_anchor_does_not_crash_peer_or_persistence(tmp_path):
    from investment_stack.forecasting.engine import ForecastingEngine
    db=canonical(tmp_path)
    invalid=replace(anchor(), base=float('nan'))
    combined,results=ForecastingEngine([FakeAdapter('xgboost-tabular-5y')]).run(
        request(), invalid, run_db_path=str(db), run_id='browser03-run')
    assert combined.point == pytest.approx(120.)
    assert 'fundamental-anchor' not in combined.component_weights
    assert 'fundamental-anchor' in combined.details['excluded']
    assert model_links(db)==[('xgboost-tabular-5y',)]


def test_qualified_anchor_still_guards_an_actual_outlier():
    req=request()
    valid=anchor()
    result=ForecastEnsembler().combine(req,[peer(1000.)],valid)
    assert 'xgboost-tabular-5y' not in result.component_weights
    assert result.component_weights == {'fundamental-anchor':1.}
    assert result.point == pytest.approx(110.)
    assert result.price_basis == 'split-adjusted'


def _git(root: Path, *args, binary=False):
    cmd=['git','-C',str(root),*args]
    return subprocess.check_output(cmd, stderr=subprocess.STDOUT,
                                   **({} if binary else {'text':True})).strip()


@pytest.mark.skipif(shutil.which('git') is None, reason='local git executable unavailable')
def test_pinned_clean_git_rejects_ignored_import_shadow_not_ignored_weights(tmp_path):
    root=tmp_path/'synthetic-kronos';root.mkdir()
    _git(root,'init','-q')
    (root/'model').mkdir()
    (root/'model/__init__.py').write_text('from .kronos import Kronos\n')
    (root/'model/kronos.py').write_text('class Kronos: pass\n')
    (root/'.gitignore').write_text('model/kronos/\nweights/\ncache/\n')
    _git(root,'add','.gitignore','model/__init__.py','model/kronos.py')
    _git(root,'-c','user.name=synthetic','-c','user.email=synthetic@example.invalid',
         'commit','-qm','pinned synthetic source')
    pin=_git(root,'rev-parse','HEAD')
    (root/'weights').mkdir();(root/'weights/weights.bin').write_bytes(b'not actual weights')
    (root/'cache').mkdir();(root/'cache/log.txt').write_text('ignored non-code data')
    assert not _git(root,'status','--porcelain')
    assert verify_kronos_source(root,pin)==root.resolve()
    (root/'model/kronos').mkdir()
    (root/'model/kronos/__init__.py').write_text('class Kronos: pass  # shadowed package\n')
    assert not _git(root,'status','--porcelain')
    assert b'model/kronos/__init__.py' in _git(root,'ls-files','--others','--ignored','--exclude-standard','-z',binary=True)
    with pytest.raises(RuntimeError, match='ignored executable/import-shadowing'):
        verify_kronos_source(root,pin)
    (root/'model/kronos/__init__.py').unlink()
    (root/'model/kronos').rmdir()
    assert verify_kronos_source(root,pin)==root.resolve()


def counts(path):
    with sqlite3.connect(path) as c:
        return tuple(c.execute(f'SELECT count(*) FROM {t}').fetchone()[0]
                     for t in ('forecast_model_runs','forecast_ensembles','forecast_ensemble_components'))


def ensemble_for(model):
    req=request()
    return EnsembleForecast(instrument_id=req.instrument_id,currency=req.currency,
        as_of=req.as_of,target_date=req.target_date,price_basis='split-adjusted',
        horizon_steps=req.horizon_steps,frequency=req.frequency,
        status='COMPLETE',point=model.point,quantiles={},
        component_weights={model.model_id:1.0},components=[model])


@pytest.mark.parametrize('mutation', [
    {'point':1000.}, {'status':'PARTIAL'}, {'quantiles':{0.1:90.,0.9:200.}},
    {'details':{'provenance':'CHANGED','model_revision':'test'}},
    {'point_semantics':'median'}, {'validation_level':'RESEARCH'},
    {'error':'unexpected'}, {'observed_at':datetime(2024,1,1,tzinfo=timezone.utc)},
])
def test_bundle_active_payload_mismatch_cannot_insert_any_rows(tmp_path, mutation):
    db=canonical(tmp_path);store=ForecastStore(db)
    wanted=peer();supplied=replace(wanted,**mutation)
    with pytest.raises(ValueError, match='active component payload'):
        store.save_bundle('browser03-run','X',[supplied],ensemble_for(wanted))
    assert counts(db)==(0,0,0)


@pytest.mark.parametrize('mutation', [
    {'point':1000.}, {'status':'PARTIAL'}, {'quantiles':{0.1:90.,0.9:200.}},
    {'details':{'provenance':'CHANGED','model_revision':'test'}},
    {'point_semantics':'median'}, {'validation_level':'RESEARCH'},
    {'error':'unexpected'},
])
def test_save_ensemble_rejects_persisted_link_payload_mismatch_atomically(tmp_path,mutation):
    db=canonical(tmp_path);store=ForecastStore(db)
    component=peer(); saved=replace(component,**mutation)
    saved_id=store.save_model('browser03-run','X',saved)
    assert counts(db)==(1,0,0)
    with pytest.raises(ValueError, match='payload differs'):
        store.save_ensemble('browser03-run',ensemble_for(component),component_model_run_ids=[saved_id])
    assert counts(db)==(1,0,0)


def test_ensemble_rejects_unpersistable_active_observation_time(tmp_path):
    db=canonical(tmp_path)
    component=replace(peer(), observed_at=datetime(2024,12,31,tzinfo=timezone.utc))
    ens=ensemble_for(component)
    store=ForecastStore(db)
    with pytest.raises(ValueError,match='observed_at cannot be serialized'):
        store.save_bundle('browser03-run','X',[component],ens)
    assert counts(db)==(0,0,0)
    mid=store.save_model('browser03-run','X',peer())
    with pytest.raises(ValueError,match='observed_at cannot be serialized'):
        store.save_ensemble('browser03-run',ens,component_model_run_ids=[mid])
    assert counts(db)==(1,0,0)


def test_exact_active_payloads_and_inactive_audit_continue_to_persist(tmp_path):
    db=canonical(tmp_path);store=ForecastStore(db)
    active=peer();inactive=replace(peer(point=115.),model_id='unavailable-audit',status='UNAVAILABLE',point=None,
                             quantiles={},error='synthetic missing source')
    ens=ensemble_for(active)
    ids,eid=store.save_bundle('browser03-run','X',[active,inactive],ens)
    assert len(ids)==2 and eid.startswith('ensemble:')
    assert counts(db)==(2,1,1)
    assert model_links(db)==[(active.model_id,)]
    db2=canonical(tmp_path/'external'); store2=ForecastStore(db2)
    mid=store2.save_model('browser03-run','X',active)
    store2.save_ensemble('browser03-run',ens,component_model_run_ids=[mid])
    assert counts(db2)==(1,1,1)


class PredictCagr:
    called=False
    def predict(self, x):
        self.called=True
        return np.asarray([0.1])


def tabular_artifact(tmp_path, **overrides):
    model=tmp_path/'model.json';model.write_bytes(b'synthetic opaque model for cached predictor')
    meta={'schema_version':1,'model_type':'xgboost','model_id':'xgboost-tabular-5y',
          'model_file':'model.json','model_sha256':hashlib.sha256(model.read_bytes()).hexdigest(),
          'feature_names':['pe'],'feature_schema':{'pe':{'unit':'ratio','description':'synthetic'}} ,
          'target':'future_cagr_5y','target_kind':'price_cagr','target_unit':'annual_decimal',
          'horizon_years':5,'frequency':'ME','horizon_steps':60,
          'currency':'USD','price_basis':'split-adjusted',
          'training_cutoff':'2020-01-01T00:00:00Z',
          'validation_cutoff':'2021-01-01T00:00:00Z',
          'evaluation_cutoff':'2022-01-01T00:00:00Z'}
    meta.update(overrides)
    (tmp_path/'metadata.json').write_text(json.dumps(meta))
    adapter=TabularMLAdapter(tmp_path)
    predictor=PredictCagr();adapter._model=predictor
    return adapter,predictor


def tabular_request(*, horizon_steps=60, frequency='ME', target_date=None):
    from investment_stack.forecasting.contracts import ForecastRequest
    asof=datetime(2025,1,1,tzinfo=timezone.utc)
    if target_date is None:
        target_date=pd.Timestamp('2029-12-31T00:00:00Z').to_pydatetime()
    return ForecastRequest(instrument_id='X',currency='USD',as_of=asof,current_price=100.,
        target_date=target_date,horizon_steps=horizon_steps,frequency=frequency,
        timestamps=tuple(pd.date_range(end='2024-12-31',periods=36,freq='ME',tz='UTC').to_pydatetime()),
        history=(100.,)*36,
        metadata={'price_basis':'split-adjusted','ml_features':{'pe':10.},
                  'ml_feature_units':{'pe':'ratio'},
                  'ml_feature_timestamps':{'pe':'2024-12-31T00:00:00Z'}})


@pytest.mark.parametrize('bad_meta', [
    {'target':'future_cagr_1y'}, {'horizon_years':1}, {'model_id':'xgboost-tabular-1y'},
    {'frequency':'W-FRI'}, {'horizon_steps':59}, {'horizon_years':5.09},
])
def test_target_horizon_model_identity_and_cadence_rejected_before_cached_predict(bad_meta,tmp_path):
    a,p=tabular_artifact(tmp_path,**bad_meta)
    result=a.forecast(tabular_request())
    assert result.status=='UNAVAILABLE' and result.point is None
    assert not p.called


def test_59_month_request_refused_even_when_artifact_horizon_is_five(tmp_path):
    a,p=tabular_artifact(tmp_path)
    req=tabular_request(horizon_steps=59,target_date=pd.Timestamp('2029-11-30T00:00:00Z').to_pydatetime())
    result=a.forecast(req)
    assert result.status=='UNAVAILABLE' and result.point is None and not p.called


def test_bound_5_year_native_metadata_path_calls_cached_predict(tmp_path):
    a,p=tabular_artifact(tmp_path)
    out=a.forecast(tabular_request())
    assert p.called and out.status=='PARTIAL' and out.point==pytest.approx(100 * 1.1**5)
