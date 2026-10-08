"""SYNTHETIC acceptance checks for browser02; reviewer probes remain read-only."""
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import pytest

from investment_stack.forecasting.adapters.chronos2 import Chronos2Adapter
from investment_stack.forecasting.contracts import ForecastRequest
from investment_stack.forecasting.integrity import verify_snapshot_manifest
from investment_stack.forecasting.model_registry import MODEL_SPECS


def bound_request():
    ts = tuple(pd.date_range(end='2020-01-01', periods=40, freq='D', tz='UTC').to_pydatetime())
    return ForecastRequest(instrument_id='X', currency='USD', as_of=ts[-1], current_price=100.0,
                           target_date=datetime(2020, 1, 6, tzinfo=timezone.utc), horizon_steps=5,
                           frequency='D', timestamps=ts, history=(100.,) * 40,
                           metadata={'price_basis':'split-adjusted'})


@pytest.mark.parametrize('bad', ['none', 'negative', 'crossing', 'wrong_id', 'short'])
def test_chronos_complete_and_full_path_guards(bad):
    class Pipeline:
        called = False
        def predict_df(self, *args, **kwargs):
            self.called = True
            dates = pd.date_range('2020-01-02', periods=5, tz='UTC')
            f = pd.DataFrame({'id': ['X']*5, 'timestamp': dates, 'predictions':[110.]*5,
                              '0.1':[90.]*5, '0.5':[110.]*5, '0.9':[130.]*5})
            if bad == 'negative': f.loc[0, 'predictions'] = -1
            if bad == 'crossing': f.loc[0, '0.1'] = 200
            if bad == 'wrong_id': f.loc[0, 'id'] = 'Y'
            if bad == 'short': f = f.iloc[:-1]
            return f
    pipeline = Pipeline()
    result = Chronos2Adapter(pipeline=pipeline).forecast(bound_request())
    assert pipeline.called, result.error
    if bad == 'none':
        assert result.status == 'COMPLETE' and result.point == 110.0
    else:
        assert result.status == 'ERROR' and result.point is None


def test_forecast_monthly_stale_history_rejected():
    ts = tuple(pd.date_range('2019-01-31', periods=12, freq='ME', tz='UTC').to_pydatetime())
    req = ForecastRequest(instrument_id='X',currency='USD',as_of=datetime(2023,1,1,tzinfo=timezone.utc),
                          current_price=100.,target_date=datetime(2024,12,31,tzinfo=timezone.utc),
                          horizon_steps=60,frequency='ME',timestamps=ts,history=(100.,)*12,
                          metadata={'price_basis':'split-adjusted'})
    with pytest.raises(ValueError, match='stale monthly history'):
        req.validate()


def test_manifest_rejects_wrong_40_char_revision(tmp_path):
    import json, hashlib
    spec = MODEL_SPECS['chronos2-small']
    (tmp_path/'config.json').write_text('{}')
    (tmp_path/'model.safetensors').write_bytes(b'fake')
    files = {p: hashlib.sha256((tmp_path/p).read_bytes()).hexdigest() for p in ('config.json','model.safetensors')}
    (tmp_path/'snapshot_manifest.json').write_text(json.dumps({'version':1,'model_id':spec.model_id,
                                                       'revision':'a'*40,'files':files}))
    with pytest.raises(ValueError, match='pinned registry'):
        verify_snapshot_manifest(tmp_path,spec.model_id)

@pytest.mark.parametrize('with_anchor', [False, True])
def test_actual_cli_missing_local_weights_no_traceback(tmp_path, with_anchor):
    """Run the actual script/subprocess on synthetic point-in-time daily prices."""
    import sqlite3, subprocess, sys, json
    db = tmp_path/'prices.db'
    with sqlite3.connect(db) as con:
        con.execute('''CREATE TABLE prices_daily (instrument_id TEXT, observed_at TEXT,
            open REAL,high REAL,low REAL,close REAL,adjusted_close REAL,volume REAL,
            source TEXT,retrieved_at TEXT,currency TEXT,adjustment_basis TEXT)''')
        rows = []
        for d in pd.date_range('2015-01-01', '2019-12-31', freq='B', tz='UTC'):
            rows.append(('X', d.isoformat(), 100., 101., 99., 100., 100., 1000.,
                         'synthetic', d.isoformat(), 'USD', 'split-adjusted'))
        con.executemany('INSERT INTO prices_daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', rows)
    script = Path(__file__).resolve().parents[2]/'scripts/run_pretrained_forecast.py'
    args = [sys.executable,str(script),'--db',str(db),'--instrument','X',
            '--models-dir',str(tmp_path/'missing-models'),'--as-of','2020-01-01T00:00:00+00:00',
            '--currency','USD']
    if with_anchor:
        args.extend(['--anchor-bear','90','--anchor-base','110','--anchor-bull','130'])
    cp = subprocess.run(args, text=True, capture_output=True, timeout=25)
    assert cp.returncode in (0,3), cp.stderr
    assert 'Traceback' not in cp.stderr
    data = json.loads(cp.stdout)
    assert data['components'] and all(c['status'] != 'COMPLETE' for c in data['components'])
    assert not (tmp_path/'missing-models').exists()

def test_offline_bootstrap_never_invokes_git_network(tmp_path, monkeypatch):
    import importlib.util
    script = Path(__file__).resolve().parents[2]/'scripts/bootstrap_pretrained_models.py'
    spec = importlib.util.spec_from_file_location('fb02_bootstrap', script)
    import sys
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    def forbidden(*args, **kwargs):
        raise AssertionError('offline unexpectedly executed network-capable process')
    monkeypatch.setattr(module.subprocess, 'run', forbidden)
    state = module._ensure_kronos_source(tmp_path, skip=False, local_files_only=True)
    assert state['status'] == 'UNAVAILABLE'
    assert not (tmp_path/'kronos-source').exists()


def test_tabular_feature_units_must_be_inference_bound(tmp_path):
    from investment_stack.forecasting.adapters.tabular_ml import TabularMLAdapter
    import json, hashlib
    model = tmp_path/'model.json'
    model.write_bytes(b'not real weights')
    meta = {'schema_version':1,'model_type':'xgboost','model_file':'model.json',
            'model_sha256':hashlib.sha256(model.read_bytes()).hexdigest(),
            'feature_names':['pe'], 'feature_schema':{'pe':{'unit':'ratio'}},
            'horizon_years':5.0,'frequency':'ME','horizon_steps':60,'target':'future_cagr_5y',
            'target_kind':'price_cagr','target_unit':'annual_decimal',
            'training_cutoff':'2017-01-01T00:00:00+00:00',
            'validation_cutoff':'2018-01-01T00:00:00+00:00',
            'evaluation_cutoff':'2019-01-01T00:00:00+00:00',
            'currency':'USD','price_basis':'split-adjusted'}
    (tmp_path/'metadata.json').write_text(json.dumps(meta))
    asof=datetime(2020,1,1,tzinfo=timezone.utc)
    req = ForecastRequest(instrument_id='X',currency='USD',as_of=asof,current_price=100.,
                          target_date=datetime(2025,1,1,tzinfo=timezone.utc),horizon_steps=5,
                          frequency='YS',metadata={'price_basis':'split-adjusted','ml_features':{'pe':10.},
                                                   'ml_feature_timestamps':{'pe':'2019-12-31T00:00:00+00:00'},
                                                   'ml_feature_units':{'pe':'USD'}})
    out=TabularMLAdapter(tmp_path).forecast(req)
    assert out.status in ('ERROR','UNAVAILABLE') and out.point is None


def test_snapshot_rejects_extra_undeclared_file_before_import(tmp_path, monkeypatch):
    import hashlib
    import json
    import investment_stack.forecasting.integrity as integrity
    spec = MODEL_SPECS['chronos2-small']
    (tmp_path/'config.json').write_text('{}')
    (tmp_path/'model.safetensors').write_bytes(b'mock model')
    manifest = {'version':1, 'model_id':spec.model_id, 'revision':spec.revision,
                'files': {'config.json':hashlib.sha256(b'{}').hexdigest(),
                          'model.safetensors':spec.checkpoint_sha256}}
    (tmp_path/'snapshot_manifest.json').write_text(json.dumps(manifest))
    original = integrity.sha256_file
    monkeypatch.setattr(integrity,'sha256_file',lambda p,chunk_size=1024*1024: (
        spec.checkpoint_sha256 if p.name=='model.safetensors' else original(p,chunk_size)))
    integrity.verify_snapshot_manifest(tmp_path,spec.model_id)
    (tmp_path/'unlisted_model_code.py').write_text('raise RuntimeError("not imported")')
    with pytest.raises(ValueError, match='inventory mismatch'):
        integrity.verify_snapshot_manifest(tmp_path,spec.model_id)
    (tmp_path/'unlisted_model_code.py').unlink()


def test_snapshot_symlink_rejected_when_supported(tmp_path, monkeypatch):
    import os
    import hashlib, json
    spec = MODEL_SPECS['chronos2-small']
    (tmp_path/'config.json').write_text('{}')
    (tmp_path/'model.safetensors').write_bytes(b'mock model')
    (tmp_path/'snapshot_manifest.json').write_text(json.dumps({'version':1,'model_id':spec.model_id,'revision':spec.revision,'files':{'config.json':hashlib.sha256(b'{}').hexdigest(),'model.safetensors':spec.checkpoint_sha256}}))
    import investment_stack.forecasting.integrity as integrity
    orig = integrity.sha256_file
    monkeypatch.setattr(integrity,'sha256_file',lambda p,chunk_size=1024*1024: spec.checkpoint_sha256 if p.name=='model.safetensors' else orig(p,chunk_size))
    link = tmp_path/'redirected.json'
    try:
        link.symlink_to(tmp_path/'config.json')
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"OS cannot create test symlink: {exc}")
    from investment_stack.forecasting.integrity import verify_snapshot_manifest
    with pytest.raises((ValueError, FileNotFoundError), match='symlink'):
        verify_snapshot_manifest(tmp_path, MODEL_SPECS['chronos2-small'].model_id)
