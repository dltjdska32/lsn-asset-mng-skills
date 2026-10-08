import pytest
import pandas as pd
from runtime.investment_stack.forecasting.dataset import purged_time_split, add_forward_cagr_from_prices

def test_purged_time_split_strict_ordering():
    df = pd.DataFrame({
        "as_of": ["2020-01-01T00:00:00Z"],
        "future_as_of": ["2020-01-02T00:00:00Z"]
    })
    
    with pytest.raises(ValueError, match="fit_cutoff must be < calibration_cutoff"):
        purged_time_split(df, fit_cutoff="2022-01-01T00:00:00Z", calibration_cutoff="2021-01-01T00:00:00Z", evaluation_cutoff="2023-01-01T00:00:00Z")
        
    with pytest.raises(ValueError, match="calibration_cutoff must be < evaluation_cutoff"):
        purged_time_split(df, fit_cutoff="2020-01-01T00:00:00Z", calibration_cutoff="2022-01-01T00:00:00Z", evaluation_cutoff="2021-01-01T00:00:00Z")

def test_purged_time_split_logic():
    df = pd.DataFrame({
        "id": [1, 2, 3],
        "as_of": ["2020-01-01T00:00:00Z", "2021-01-01T00:00:00Z", "2022-01-01T00:00:00Z"],
        "future_as_of": ["2020-02-01T00:00:00Z", "2021-02-01T00:00:00Z", "2022-02-01T00:00:00Z"]
    })
    
    splits = purged_time_split(
        df,
        fit_cutoff="2020-12-31T00:00:00Z",
        calibration_cutoff="2021-12-31T00:00:00Z",
        evaluation_cutoff="2022-12-31T00:00:00Z"
    )
    
    assert len(splits.train) == 1
    assert splits.train.iloc[0]["id"] == 1
    
    assert len(splits.valid) == 1
    assert splits.valid.iloc[0]["id"] == 2
    
    assert len(splits.test) == 1
    assert splits.test.iloc[0]["id"] == 3

def test_add_forward_cagr_rejects_past_or_current():
    df = pd.DataFrame({
        "instrument_id": ["A", "A", "A"],
        "as_of": ["2020-01-01T00:00:00Z", "2020-01-02T00:00:00Z", "2025-01-01T00:00:00Z"],
        "price": [100.0, 101.0, 200.0]
    })
    
    # 5 years from 2020-01-01 is 2025-01-01. It is allowed.
    # 5 years from 2020-01-02 is 2025-01-02. It will match 2025-01-01 within 45 days.
    # 5 years from 2025-01-01 is 2030-01-01. No match.
    
    res = add_forward_cagr_from_prices(df, years=5, tolerance_days=45)
    assert len(res) == 2
    assert res.iloc[0]["as_of"] == pd.Timestamp("2020-01-01T00:00:00Z")
    assert res.iloc[0]["future_as_of"] == pd.Timestamp("2025-01-01T00:00:00Z")
    assert res.iloc[1]["as_of"] == pd.Timestamp("2020-01-02T00:00:00Z")
    assert res.iloc[1]["future_as_of"] == pd.Timestamp("2025-01-01T00:00:00Z")

def test_add_forward_cagr_no_self_label():
    df = pd.DataFrame({
        "instrument_id": ["A"],
        "as_of": ["2020-01-01T00:00:00Z"],
        "price": [100.0]
    })
    
    res = add_forward_cagr_from_prices(df, years=5, tolerance_days=2000)
    # Even with huge tolerance, candidate must be strictly future, so no self label
    assert len(res) == 0
