import pandas as pd
from investment_stack.forecasting.dataset import enforce_point_in_time, add_forward_cagr_from_prices, join_features_asof

def test_leakage_check_rejects_future_publication():
    df=pd.DataFrame({'instrument_id':['A','A'],'as_of':['2020-01-01T00:00:00Z','2020-02-01T00:00:00Z'],'financial_published_at':['2019-12-31T00:00:00Z','2020-03-01T00:00:00Z'],'future_cagr_5y':[.1,.2]})
    r=enforce_point_in_time(df,published_at_cols=['financial_published_at'])
    assert not r.ok and r.violations==1

def test_add_forward_cagr():
    df=pd.DataFrame({'instrument_id':['A']*3,'as_of':['2015-01-01T00:00:00Z','2020-01-01T00:00:00Z','2025-01-01T00:00:00Z'],'price':[100,200,400]})
    out=add_forward_cagr_from_prices(df,years=5,tolerance_days=5)
    assert len(out)==2
    
    # 2015 to 2020 includes 1 leap year. 365*4 + 366 = 1826 days. actual_years = 1826 / 365.25 = 4.9993155373
    actual_years_1 = 1826 / 365.25
    expected_cagr_1 = (200.0/100.0)**(1.0/actual_years_1) - 1.0
    assert abs(out.iloc[0].future_cagr_5y - expected_cagr_1) < 1e-9

def test_join_features_asof_never_uses_future_release():
    base=pd.DataFrame({'instrument_id':['A','A'],'as_of':['2020-02-01T00:00:00Z','2020-04-01T00:00:00Z']})
    feat=pd.DataFrame({'instrument_id':['A','A'],'published_at':['2020-01-15T00:00:00Z','2020-03-15T00:00:00Z'],'eps_growth':[.1,.2]})
    out=join_features_asof(base,feat,feature_cols=['eps_growth'])
    assert list(out.eps_growth)==[.1,.2]
