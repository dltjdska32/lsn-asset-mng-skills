"""Synthetic canonical-run persistence, active anchor links, and atomic rollback."""
from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

from investment_stack.evidence.manager import RunDatabaseManager
from investment_stack.forecasting.contracts import ForecastRequest, FundamentalAnchor, ModelForecast
from investment_stack.forecasting.engine import ForecastingEngine
from investment_stack.forecasting.store import ForecastStore

AS_OF = datetime(2025, 1, 1, tzinfo=timezone.utc)
TARGET = AS_OF + timedelta(days=5)


def canonical(tmp_path):
    manager = RunDatabaseManager(tmp_path, 'browser03-run')
    assert manager.create().valid
    manager.initialize_run_context(request_mode='test', analysis_as_of=AS_OF.isoformat(), analysis_timezone='UTC')
    db = manager._operational_database_path()
    with sqlite3.connect(db) as con:
        con.execute('''INSERT INTO instrument_resolutions
                    (resolution_id, run_id, requested_identifier, resolved_identifier, resolution_status)
                    VALUES (?,?,?,?,?)''', ('resolution03', 'browser03-run', 'X', 'X', 'RESOLVED'))
    return db


def request():
    return ForecastRequest(instrument_id='X', currency='USD', as_of=AS_OF, current_price=100.,
                           target_date=TARGET, horizon_steps=5, frequency='D',
                           metadata={'price_basis':'split-adjusted'})


def anchor():
    return FundamentalAnchor(status='COMPLETE', instrument_id='X', currency='USD', target_date=TARGET,
                             price_basis='split-adjusted', value_kind='terminal_price', bear=90.,
                             base=110., bull=130., as_of=AS_OF, evidence_refs=('synthetic evidence',),
                             assumption_refs=('synthetic assumption',))


class FakeAdapter:
    def __init__(self, name, status='COMPLETE'):
        self.model_id, self.status = name, status

    def forecast(self, req):
        return ModelForecast(model_id=self.model_id, status=self.status, instrument_id=req.instrument_id,
                             currency=req.currency, as_of=req.as_of, target_date=req.target_date,
                             price_basis=req.metadata['price_basis'], horizon_steps=req.horizon_steps,
                             frequency=req.frequency, target_semantics=req.target_semantics,
                             point=120. if self.status == 'COMPLETE' else None,
                             error='synthetic unavailable' if self.status != 'COMPLETE' else None)


def model_links(db):
    with sqlite3.connect(db) as con:
        return con.execute('''SELECT m.model_id FROM forecast_ensemble_components c
                              JOIN forecast_model_runs m ON c.forecast_run_id=m.forecast_run_id''').fetchall()


@pytest.mark.parametrize('adapters,active_expected,all_expected', [
    ([], {'fundamental-anchor'}, {'fundamental-anchor'}),
    ([FakeAdapter('xgboost-tabular-5y')], {'fundamental-anchor', 'xgboost-tabular-5y'}, {'fundamental-anchor', 'xgboost-tabular-5y'}),
    ([FakeAdapter('xgboost-tabular-5y'),FakeAdapter('lightgbm-tabular-5y'),FakeAdapter('broken','UNAVAILABLE')],
     {'fundamental-anchor','xgboost-tabular-5y','lightgbm-tabular-5y'}, {'fundamental-anchor','xgboost-tabular-5y','lightgbm-tabular-5y','broken'}),
])
def test_active_links_and_inactive_model_audit(tmp_path, adapters, active_expected, all_expected):
    db = canonical(tmp_path)
    combined, results = ForecastingEngine(adapters).run(request(), anchor(), run_db_path=str(db), run_id='browser03-run')
    assert set(combined.component_weights) == active_expected
    assert {r[0] for r in model_links(db)} == active_expected
    with sqlite3.connect(db) as con:
        assert {r[0] for r in con.execute('SELECT model_id FROM forecast_model_runs')} == all_expected
        assert con.execute('SELECT COUNT(*) FROM forecast_ensembles').fetchone()[0] == 1
    assert len(results) == len(adapters)


def test_rollback_after_model_and_ensemble_inserts_when_link_fails(tmp_path, monkeypatch):
    db = canonical(tmp_path)
    # SQLite authorizer injects the write failure without altering the canonical
    # schema (an injected trigger would itself invalidate the run catalog).
    import investment_stack.forecasting.store as store_module
    connect = sqlite3.connect
    def denied_connect(*args, **kwargs):
        con = connect(*args, **kwargs)
        def deny_link_insert(action, arg1, arg2, database, trigger):
            if action == sqlite3.SQLITE_INSERT and arg1 == 'forecast_ensemble_components':
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        con.set_authorizer(deny_link_insert)
        return con
    with monkeypatch.context() as patch:
        patch.setattr(store_module.sqlite3, 'connect', denied_connect)
        with pytest.raises(sqlite3.DatabaseError, match='not authorized'):
            ForecastingEngine([FakeAdapter('xgboost-tabular-5y')]).run(
                request(), anchor(), run_db_path=str(db), run_id='browser03-run')
    with sqlite3.connect(db) as con:
        for table in ('forecast_model_runs', 'forecast_ensembles', 'forecast_ensemble_components'):
            assert con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == 0


def test_reject_duplicate_and_missing_positive_weight_without_writes(tmp_path):
    from investment_stack.forecasting.contracts import EnsembleForecast
    db = canonical(tmp_path)
    m = FakeAdapter('xgboost-tabular-5y').forecast(request())
    ensemble = EnsembleForecast(instrument_id='X', currency='USD', as_of=AS_OF, target_date=TARGET,
                                price_basis='split-adjusted', horizon_steps=5, frequency='D',
                                status='COMPLETE', point=120., quantiles={}, component_weights={'xgboost-tabular-5y':1.}, components=[m])
    store = ForecastStore(db)
    with pytest.raises(ValueError, match='duplicate'):
        store.save_bundle('browser03-run', 'X', (m,m), ensemble)
    with pytest.raises(ValueError, match='positive component weight'):
        store.save_bundle('browser03-run', 'X', (), ensemble)
    with sqlite3.connect(db) as con:
        for table in ('forecast_model_runs','forecast_ensembles','forecast_ensemble_components'):
            assert con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == 0
