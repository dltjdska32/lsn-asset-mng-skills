import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd
import numpy as np

from investment_stack.forecasting.adapters.tabular_ml import TabularMLAdapter
from investment_stack.forecasting.contracts import ForecastRequest

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc

def test_e2e_tabular_forecaster(tmp_path):
    # 1. Construct sufficient synthetic PIT financial panel with real 5year label maturity and consistent schema
    # We need train, cal, eval splits, so we span a wide range of years.
    # Label needs to be 5 years in the future.
    # horizon_years = 5, tolerance is handled if we just create exact +5 year targets.
    
    rows = []
    # Train: 2000 to 2010. Valid: 2011 to 2015. Test: 2016 to 2019
    # Label requires +5 years, so for 2019, label is at 2024.
    
    start_date = pd.to_datetime('1990-01-01', utc=True)
    dates = pd.date_range(start_date, periods=400, freq='ME') # ~33 years
    
    for i, as_of in enumerate(dates):
        # future_as_of is 5 years later
        future_as_of = as_of + pd.DateOffset(years=5)
        # some fake values
        price = 100.0 * (1.05 ** (i / 12))
        future_price = 100.0 * (1.05 ** ((i + 60) / 12))
        cagr_5y = (future_price / price) ** (1/5) - 1.0
        
        # feature f1: current price normalized
        f1_val = price / 100.0
        
        rows.append({
            'instrument_id': 'XYZ',
            'as_of': as_of.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'future_as_of': future_as_of.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'f1': f1_val,
            'f1_published_at': as_of.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'f1_units': 'USD',
            'future_cagr_5y': cagr_5y
        })
    
    df = pd.DataFrame(rows)
    csv_path = tmp_path / 'panel.csv'
    df.to_csv(csv_path, index=False)
    
    # 2. Consistent schema
    schema = {
        "f1": {
            "description": "Normalized price",
            "type": "numeric", "unit": "USD"
        },
        "future_cagr_5y": {
            "description": "forbidden",
            "type": "numeric", "unit": "USD"
        }
    }
    schema_path = tmp_path / 'schema.json'
    schema_path.write_text(json.dumps(schema))
    
    # 3. Invoke real train_tabular_forecaster CLI
    out_dir = tmp_path / 'artifacts'
    
    train_end = '2010-01-01T00:00:00Z'
    valid_end = '2016-01-01T00:00:00Z'
    eval_end = '2022-01-01T00:00:00Z'
    
    p = subprocess.run([
        sys.executable, str(ROOT / 'scripts/train_tabular_forecaster.py'),
        '--csv', str(csv_path),
        '--output-dir', str(out_dir),
        '--features', 'f1',
        '--feature-schema', str(schema_path),
        '--train-end', train_end,
        '--valid-end', valid_end,
        '--eval-end', eval_end,
        '--provenance', 'SYNTHETIC', '--currency', 'USD', '--price-basis', 'split-adjusted'
    ], capture_output=True, text=True)
    
    if p.returncode != 0:
        print("STDOUT:", p.stdout)
        print("STDERR:", p.stderr)
        assert False, "CLI failed"
        
    summary = json.loads((out_dir / 'training_summary.json').read_text())
    assert summary['splits']['train'] >= 100
    assert summary['splits']['valid'] > 0
    assert summary['splits']['test'] > 0
    
    # 4. Load produced artifacts using actual native models, call adapter at later aware asof
    for model_type in ['xgboost', 'lightgbm']:
        model_dir = out_dir / model_type
        assert model_dir.exists()
        
        adapter = TabularMLAdapter(model_dir)
        
        request_as_of = pd.to_datetime('2023-01-01T00:00:00Z') # Later than eval_end
        
        # Test forecast
        req = ForecastRequest(
            instrument_id='XYZ',
            currency='USD',
            as_of=request_as_of.to_pydatetime(),
            current_price=200.0,
            target_date=pd.Timestamp('2027-12-31T00:00:00Z').to_pydatetime(),
            horizon_steps=60,
            frequency='ME',
            history=[100.0] * 40,
            timestamps=list(pd.date_range(end='2022-12-31', periods=40, freq='ME', tz='UTC').to_pydatetime()),
            metadata={
                'price_basis': 'split-adjusted',
                'ml_features': {'f1': 2.0},
                'ml_feature_units': {'f1': 'USD'},
                'ml_feature_timestamps': {'f1': '2022-12-31T00:00:00Z'}
            }
        )
        
        out = adapter.forecast(req)
        assert out.status == 'COMPLETE', f"Expected COMPLETE, got {out.status}: {getattr(out, 'error', '')}"
        assert out.validation_level == 'EXPERIMENTAL'
        
        # Assert positive finite output correct CAGR-to-price basis
        assert np.isfinite(out.point)
        assert out.point > 0
        
        details = out.details
        assert 'predicted_cagr' in details
        
        cagr = details['predicted_cagr']
        # The expected price given CAGR: terminal = current_price * ((1.0 + cagr) ** 5)
        # Because we requested 60 ME (5 years)
        expected_point = 200.0 * ((1.0 + cagr) ** 5)
        np.testing.assert_allclose(out.point, expected_point, rtol=1e-5)
        
        # Check distinct counts/cutoffs
        assert details['training_cutoff'] == train_end
        assert details['validation_cutoff'] == valid_end
        assert details['evaluation_cutoff'] == eval_end

def test_cli_failure_cases(tmp_path):
    schema = {"f1": {"description": "Normalized price", "type": "numeric", "unit": "USD"}, "future_cagr_5y": {"description": "test", "type": "numeric", "unit": "USD"}}
    schema_path = tmp_path / 'schema.json'
    schema_path.write_text(json.dumps(schema))
    
    rows = []
    start_date = pd.to_datetime('2000-01-01', utc=True)
    dates = pd.date_range(start_date, periods=150, freq='ME')
    for i, as_of in enumerate(dates):
        future_as_of = as_of + pd.DateOffset(years=5)
        rows.append({
            'instrument_id': 'XYZ',
            'as_of': as_of.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'future_as_of': future_as_of.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'f1': 1.0,
            'f1_published_at': as_of.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'f1_units': 'USD',
            'future_cagr_5y': 0.05
        })
    df = pd.DataFrame(rows)
    csv_path = tmp_path / 'panel.csv'
    df.to_csv(csv_path, index=False)
    out_dir = tmp_path / 'artifacts'
    
    base_cmd = [
        sys.executable, str(ROOT / 'scripts/train_tabular_forecaster.py'),
        '--csv', str(csv_path), '--output-dir', str(out_dir),
        '--feature-schema', str(schema_path),
        '--train-end', '2005-01-01T00:00:00Z', '--valid-end', '2011-01-01T00:00:00Z', '--eval-end', '2016-01-01T00:00:00Z',
        '--provenance', 'SYNTHETIC', '--currency', 'USD', '--price-basis', 'split-adjusted'
    ]
    
    # 1. selected target feature (forbidden feature detected)
    p = subprocess.run(base_cmd + ['--features', 'future_cagr_5y'], capture_output=True, text=True)
    assert p.returncode != 0
    assert 'Forbidden or outcome feature detected' in (p.stdout + p.stderr)
    
    # 2. future artifact label maturity (label avail < obs + horizon)
    # The dataframe has 5 years exactly. If we set horizon_years to 6, it should fail.
    p = subprocess.run(base_cmd + ['--features', 'f1', '--horizon-years', '6.0'], capture_output=True, text=True)
    assert p.returncode != 0
    assert 'target/horizon must bind to price CAGR years' in (p.stdout + p.stderr)
