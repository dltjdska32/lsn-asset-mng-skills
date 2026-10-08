import pytest
import pandas as pd
from datetime import datetime, timezone
import sqlite3
from pathlib import Path

from scripts.run_pretrained_forecast import load_daily, to_monthly

def test_load_daily_fails_without_currency(tmp_path):
    db_path = tmp_path / "test.db"
    with sqlite3.connect(db_path) as cx:
        cx.execute("""
            CREATE TABLE prices_daily (
                observed_at TEXT, open REAL, high REAL, low REAL, close REAL, adjusted_close REAL,
                volume REAL, source TEXT, retrieved_at TEXT, currency TEXT, adjustment_basis TEXT, instrument_id TEXT
            )
        """)
        cx.execute("INSERT INTO prices_daily VALUES ('2023-01-01T00:00:00Z', 1, 2, 0.5, 1.5, 1.5, 100, 'src', '2023-01-01T01:00:00Z', 'USD', 'split-adjusted', 'INST')")
    
    as_of = datetime(2023, 1, 2, tzinfo=timezone.utc)
    
    with pytest.raises(ValueError, match="Currency must be explicitly specified"):
        load_daily(db_path, "INST", as_of)

def test_load_daily_enforces_as_of(tmp_path):
    db_path = tmp_path / "test.db"
    with sqlite3.connect(db_path) as cx:
        cx.execute("""
            CREATE TABLE prices_daily (
                observed_at TEXT, open REAL, high REAL, low REAL, close REAL, adjusted_close REAL,
                volume REAL, source TEXT, retrieved_at TEXT, currency TEXT, adjustment_basis TEXT, instrument_id TEXT
            )
        """)
        cx.execute("INSERT INTO prices_daily VALUES ('2023-01-01T00:00:00Z', 1, 2, 0.5, 1.5, 1.5, 100, 'src', '2023-01-01T01:00:00Z', 'USD', 'split-adjusted', 'INST')")
        cx.execute("INSERT INTO prices_daily VALUES ('2023-01-03T00:00:00Z', 1, 2, 0.5, 1.5, 1.5, 100, 'src', '2023-01-03T01:00:00Z', 'USD', 'split-adjusted', 'INST')")
    
    as_of = datetime(2023, 1, 2, tzinfo=timezone.utc)
    df = load_daily(db_path, "INST", as_of, required_currency="USD")
    assert len(df) == 1
    assert df.index[0].day == 1

def test_load_daily_conflict_resolution(tmp_path):
    db_path = tmp_path / "test.db"
    with sqlite3.connect(db_path) as cx:
        cx.execute("""
            CREATE TABLE prices_daily (
                observed_at TEXT, open REAL, high REAL, low REAL, close REAL, adjusted_close REAL,
                volume REAL, source TEXT, retrieved_at TEXT, currency TEXT, adjustment_basis TEXT, instrument_id TEXT
            )
        """)
        cx.execute("INSERT INTO prices_daily VALUES ('2023-01-01T00:00:00Z', 1, 2, 0.5, 1.5, 1.5, 100, 'srcA', '2023-01-01T01:00:00Z', 'USD', 'split-adjusted', 'INST')")
        cx.execute("INSERT INTO prices_daily VALUES ('2023-01-01T00:00:00Z', 2, 3, 1.5, 2.5, 2.5, 200, 'srcB', '2023-01-01T01:00:00Z', 'USD', 'split-adjusted', 'INST')")
    
    as_of = datetime(2023, 1, 2, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="Conflicting sources"):
        load_daily(db_path, "INST", as_of, required_currency="USD")
        
    df = load_daily(db_path, "INST", as_of, required_currency="USD", source_policy="srcA")
    assert len(df) == 1
    assert df["close"].iloc[0] == 1.5

def test_to_monthly_excludes_current_incomplete_month():
    dates = pd.date_range("2023-01-01", "2023-02-15", freq="D", tz="UTC")
    daily = pd.DataFrame({
        "open": [1]*len(dates),
        "high": [2]*len(dates),
        "low": [0.5]*len(dates),
        "close": [1.5]*len(dates),
        "volume": [100]*len(dates)
    }, index=dates)
    
    as_of = datetime(2023, 2, 15, tzinfo=timezone.utc)
    monthly = to_monthly(daily, as_of)
    assert len(monthly) == 1
    assert monthly.index[0].month == 1

def test_to_monthly_includes_complete_month():
    dates = pd.date_range("2023-01-01", "2023-02-28", freq="D", tz="UTC") # Not a leap year, so 28 is complete
    daily = pd.DataFrame({
        "open": [1]*len(dates),
        "high": [2]*len(dates),
        "low": [0.5]*len(dates),
        "close": [1.5]*len(dates),
        "volume": [100]*len(dates)
    }, index=dates)
    
    as_of = datetime(2023, 3, 1, tzinfo=timezone.utc)
    monthly = to_monthly(daily, as_of)
    assert len(monthly) == 2
    assert monthly.index[-1].month == 2
