"""Synthetic PIT no-network guards; independent reviewer tests remain untouched."""
from datetime import datetime, timezone
from dataclasses import replace
import pandas as pd
import pytest
from investment_stack.forecasting.adapters.kronos import KronosAdapter
from investment_stack.forecasting.contracts import ForecastRequest, FundamentalAnchor, ModelForecast
from investment_stack.forecasting.ensemble import ForecastEnsembler
from scripts.run_pretrained_forecast import to_monthly


def request():
    dates = pd.date_range('2020-01-31', periods=12, freq='ME', tz='UTC')
    df = pd.DataFrame({'open':[100.]*12,'high':[100.]*12,'low':[100.]*12,
                       'close':[100.]*12,'volume':[1000.]*12,'amount':[100000.]*12}, index=dates)
    # Kronos minimum context is 32
    dates = pd.date_range('2018-01-31', periods=36, freq='ME', tz='UTC')
    df = pd.DataFrame({c:[float(x)]*36 for c,x in {'open':100,'high':100,'low':100,'close':100,'volume':1000,'amount':100000}.items()},index=dates)
    asof=datetime(2021,1,1,tzinfo=timezone.utc)
    return ForecastRequest(instrument_id='X', currency='USD', as_of=asof, current_price=100.,
        target_date=datetime(2021,3,31,tzinfo=timezone.utc),horizon_steps=3,frequency='ME',
        timestamps=tuple(dates.to_pydatetime()),history=(100.,)*36, ohlcv=df,
        metadata={'price_basis':'split-adjusted'})

class Predictor:
    called=False
    def predict(self, *, df, x_timestamp, y_timestamp, **kwargs):
        self.called=True
        assert isinstance(x_timestamp.iloc[0], pd.Timestamp)
        return pd.DataFrame({'close':[110.]*len(y_timestamp)},index=pd.DatetimeIndex(y_timestamp))

@pytest.mark.parametrize('case', ['normal','future','range','close','length','duplicate','missing_amount'])
def test_kronos_observed_cadence_and_amount_bound_before_prediction(case):
    req=request()
    df=req.ohlcv.copy()
    if case=='future': df.index=df.index+pd.DateOffset(years=5)
    elif case=='range': df=df.reset_index(drop=True)
    elif case=='close': df.iloc[0, df.columns.get_loc('close')]=1000.
    elif case=='length': df=df.iloc[1:]
    elif case=='duplicate':
        idx=list(df.index);idx[1]=idx[0];df.index=pd.DatetimeIndex(idx)
    elif case=='missing_amount': df=df.drop(columns=['amount'])
    p=Predictor()
    result=KronosAdapter(predictor=p).forecast(replace(req,ohlcv=df))
    if case=='normal':
        assert p.called and result.status=='COMPLETE' and result.point==110.
    else:
        assert not p.called
        assert result.point is None and result.status==('UNAVAILABLE' if case=='missing_amount' else 'ERROR')

@pytest.mark.parametrize('when,kind,expected', [('past','terminal_price',True),('future','terminal_price',False),('unknown','terminal_price',False),('past','current_fair_value',False)])
def test_anchor_timestamp_provenance_and_kind(when,kind,expected):
    req=request()
    when_dt={'past':datetime(2020,12,1,tzinfo=timezone.utc), 'future':datetime(2021,2,1,tzinfo=timezone.utc), 'unknown':None}[when]
    anchor=FundamentalAnchor(status='PARTIAL',instrument_id='X',currency='USD',target_date=req.target_date,
          price_basis='split-adjusted',value_kind=kind, as_of=when_dt,base=200.,assumption_refs=('synthetic',))
    peer=ModelForecast(model_id='autogluon/chronos-2-small',status='COMPLETE',instrument_id='X',currency='USD',
         as_of=req.as_of,target_date=req.target_date,price_basis='split-adjusted',horizon_steps=req.horizon_steps,
         frequency=req.frequency,point=110.)
    out=ForecastEnsembler().combine(req,[peer],anchor)
    assert ('fundamental-anchor' in out.component_weights)==expected
    if expected:
        component=next(c for c in out.components if c.model_id=='fundamental-anchor')
        assert component.details['anchor_provenance_as_of']==when_dt.isoformat()
    else:
        assert out.point == pytest.approx(110.) and 'fundamental-anchor' in out.details['excluded']


def test_monthly_amount_preserves_source_sum_and_index():
    idx=pd.date_range('2019-01-02',periods=40,freq='B',tz='UTC')
    daily=pd.DataFrame({k:[v]*len(idx) for k,v in {'open':100,'high':101,'low':99,'close':100,'volume':10,'amount':1000}.items()},index=idx)
    m=to_monthly(daily,datetime(2019,3,1,tzinfo=timezone.utc))
    assert isinstance(m.index,pd.DatetimeIndex) and m.index.tz is not None
    assert m['amount'].sum()==len(daily)*1000
    assert 'amount' not in to_monthly(daily.drop(columns=['amount']),datetime(2019,3,1,tzinfo=timezone.utc))


def test_actual_cli_uses_engine_assessment_not_none(tmp_path, monkeypatch, capsys):
    """SYNTHETIC PIT SQLite -> actual CLI main -> stubbed local model -> engine assessment."""
    import sqlite3, json, sys
    from scripts import run_pretrained_forecast as cli
    db=tmp_path/'synthetic.db'
    with sqlite3.connect(db) as cx:
        cx.execute('''CREATE TABLE prices_daily (instrument_id TEXT, observed_at TEXT,
         open REAL, high REAL, low REAL, close REAL, adjusted_close REAL, volume REAL,
         source TEXT, retrieved_at TEXT, currency TEXT, adjustment_basis TEXT)''')
        rows=[('X',d.isoformat(),100.,100.,100.,100.,100.,1000.,'synthetic',d.isoformat(),'USD','split-adjusted')
              for d in pd.date_range('2015-01-01','2020-12-31',freq='B',tz='UTC')]
        cx.executemany('INSERT INTO prices_daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',rows)

    class LocalForecast:
        model_id='autogluon/chronos-2-small'
        def __init__(self,*args,**kwargs): pass
        def forecast(self,req):
            return ModelForecast(model_id=self.model_id,status='COMPLETE',instrument_id=req.instrument_id,
                 currency=req.currency,as_of=req.as_of,target_date=req.target_date,
                 price_basis=req.metadata['price_basis'],horizon_steps=req.horizon_steps,
                 frequency=req.frequency,target_semantics=req.target_semantics,point=110.)
    class MissingForecast:
        model_id='NeoQuasar/Kronos-mini'
        def __init__(self,*args,**kwargs): pass
        def forecast(self,req):
            return ModelForecast(model_id=self.model_id,status='UNAVAILABLE',error='no pinned weights',
                instrument_id=req.instrument_id,currency=req.currency,as_of=req.as_of,
                target_date=req.target_date,price_basis=req.metadata['price_basis'],
                horizon_steps=req.horizon_steps,frequency=req.frequency,target_semantics=req.target_semantics)
    monkeypatch.setattr(cli,'Chronos2Adapter',LocalForecast)
    monkeypatch.setattr(cli,'KronosAdapter',MissingForecast)
    monkeypatch.setattr(sys,'argv',['run_pretrained_forecast.py','--db',str(db),'--instrument','X',
            '--models-dir',str(tmp_path/'absent'),'--as-of','2021-01-01T00:00:00+00:00',
            '--currency','USD','--anchor-base','115'])
    assert cli.main()==0
    payload=json.loads(capsys.readouterr().out)
    assert payload['assessment']==payload['ensemble']['details']['assessment']
    assert payload['assessment']['ranking_allowed'] is False
    assert payload['assessment']['status'] in ('CONDITIONAL','UNAVAILABLE','ERROR')
    assert payload['ensemble']['status'] in ('PARTIAL','COMPLETE')
    assert payload['ensemble']['weights'].get('fundamental-anchor',0)>0
    assert not (tmp_path/'absent').exists()
