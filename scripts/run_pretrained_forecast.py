#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
import math

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from investment_stack.forecasting.adapters import Chronos2Adapter, KronosAdapter
from investment_stack.forecasting.contracts import ForecastRequest, FundamentalAnchor
from investment_stack.forecasting.engine import ForecastingEngine
from investment_stack.forecasting.ensemble import ForecastEnsembler, EnsemblePolicy
from investment_stack.forecasting.monte_carlo import simulate_terminal_distribution

def load_daily(db: Path, instrument_id: str, as_of: datetime, historical_retrieval_cutoff: datetime | None = None, required_currency: str = "", source_policy: str = "conflict_fail", price_basis_policy: str = "split-adjusted") -> pd.DataFrame:
    if not db.exists():
        raise FileNotFoundError(f"Database not found: {db}")
    uri = f"file:{db.absolute().as_posix()}?mode=ro"
    
    with sqlite3.connect(uri, uri=True) as cx:
        # Require actual currency and adjustment policy from DB if present, assume schema has them
        db_columns = {row[1] for row in cx.execute("PRAGMA table_info(prices_daily)")}
        amount_select = ", amount" if "amount" in db_columns else ""
        query = f"""
            SELECT observed_at, open, high, low, close, adjusted_close, volume, source, retrieved_at, currency, adjustment_basis{amount_select}
            FROM prices_daily
            WHERE instrument_id=?
        """
        params = [instrument_id]
        
        try:
            df = pd.read_sql_query(query, cx, params=params)
        except sqlite3.OperationalError:
            # Fallback if currency/adjustment_basis not in schema (but fail if we rely on strict checks)
            # We are asked to verify actual currency against required CLI. If schema lacks it, we must fail?
            # "Actualcurrency from DB verified against requiredCLI declaration if schema lacks it; no USDdefault."
            # If schema lacks it, maybe we check if it is passed in the table? If table doesn't have it, we fail.
            raise RuntimeError("DB schema must include currency and adjustment_basis")

    if df.empty:
        raise RuntimeError(f"no price data for {instrument_id}")
    
    # Reject naive/missing before UTC normalize
    for col in ["observed_at", "retrieved_at"]:
        if col not in df.columns or df[col].isna().all():
            if col == "observed_at": raise RuntimeError("observed_at missing")
            continue
            
        is_naive = ~df[col].dropna().astype(str).str.contains(r'(Z|[+-]\d{2}:\d{2})$', regex=True)
        if is_naive.any():
            raise RuntimeError(f"Naive or invalid timestamps found in {col}")
    
    df["observed_at"] = pd.to_datetime(df["observed_at"], utc=True)
    df["retrieved_at"] = pd.to_datetime(df["retrieved_at"], utc=True)
        
    df = df[df["observed_at"] <= as_of]
    if historical_retrieval_cutoff:
        if historical_retrieval_cutoff > as_of:
            raise ValueError("retrieval_cutoff cannot be later than as_of")
        if df["retrieved_at"].isna().any():
            raise RuntimeError("Missing retrieved_at for historical retrieval cutoff")
        df = df[df["retrieved_at"] <= historical_retrieval_cutoff]
        
    df = df[(df["retrieved_at"].isna()) | (df["retrieved_at"] <= as_of)]

    if df.empty:
        raise RuntimeError(f"no price data for {instrument_id} as of {as_of}")

    if not required_currency:
        raise ValueError("Currency must be explicitly specified (no USD default)")
        
    if not (df["currency"] == required_currency).all():
        raise ValueError(f"Currency mismatch: expected {required_currency}")
        
    if not (df["adjustment_basis"] == price_basis_policy).all():
        raise ValueError(f"Price basis mismatch: expected {price_basis_policy}")

    # Explicit source selection applies ALL rows
    sources = df["source"].unique()
    if len(sources) > 1:
        if source_policy == "conflict_fail":
            raise ValueError(f"Conflicting sources: {sources}")
        else:
            df = df[df["source"] == source_policy]
            if df.empty:
                raise ValueError(f"No data for selected source {source_policy}")
                
    # Same provider duplicate observations: latest retrieval or conflict
    duplicates = df[df.duplicated(subset=["observed_at"], keep=False)]
    if not duplicates.empty:
        df = df.sort_values(["observed_at", "retrieved_at"])
        for obs, group in df.groupby("observed_at"):
            if len(group) > 1:
                # check if values differ
                vals = group[["open", "high", "low", "close", "adjusted_close", "volume"]].nunique()
                if (vals > 1).any():
                    raise ValueError(f"Conflicting values for same provider on {obs}")
        df = df.drop_duplicates(subset=["observed_at"], keep="last")

    if "amount" in df.columns:
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
        if not np.isfinite(df["amount"]).all() or (df["amount"] < 0).any():
            raise ValueError("invalid source transaction amount")

    # Finite positive OHLC, volume nonnegative finite
    for col in ["open", "high", "low", "close", "adjusted_close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
        if not np.all(np.isfinite(df[col])) or not np.all(df[col] > 0):
            raise ValueError(f"Non-finite or non-positive values in {col}")
            
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    if not np.all(np.isfinite(df["volume"])) or not np.all(df["volume"] >= 0):
        raise ValueError("Missing, non-finite, or negative volume")

    # Validate high >= max(open, close, low) and low <= min(open, close, high)
    max_ocl = df[["open", "close", "low"]].max(axis=1)
    if not (df["high"] >= max_ocl).all():
        raise ValueError("high < max(open, close, low) detected")
    min_och = df[["open", "close", "high"]].min(axis=1)
    if not (df["low"] <= min_och).all():
        raise ValueError("low > min(open, close, high) detected")

    # Split-only validated factor applies to open/high/low/close
    if price_basis_policy == "split-adjusted":
        factor = df["adjusted_close"] / df["close"]
        df["open"] = df["open"] * factor
        df["high"] = df["high"] * factor
        df["low"] = df["low"] * factor
        df["close"] = df["adjusted_close"]
    
    df = df.set_index("observed_at").sort_index()
    return df

def to_monthly(daily: pd.DataFrame, as_of: datetime) -> pd.DataFrame:
    monthly = pd.DataFrame({
        "open": daily["open"].resample("ME").first(),
        "high": daily["high"].resample("ME").max(),
        "low": daily["low"].resample("ME").min(),
        "close": daily["close"].resample("ME").last(),
        "volume": daily["volume"].resample("ME").sum(),
        **({"amount": daily["amount"].resample("ME").sum()} if "amount" in daily.columns else {}),
    }).dropna(subset=["open", "high", "low", "close"])
    
    if monthly.empty:
        return monthly
        
    # Conservative current month exclusion
    last_idx = monthly.index[-1]
    if last_idx.year == as_of.year and last_idx.month == as_of.month:
        if True:
            # Without trustworthy exchange-close evidence, exclude current calendar month
            monthly = monthly.iloc[:-1]
            
    return monthly

def model_paths(models_dir: Path) -> tuple[Path, Path, Path, Path]:
    chronos = models_dir / "chronos2-small"
    kronos = models_dir / "kronos-mini"
    tokenizer = models_dir / "kronos-tokenizer-2k"
    source = models_dir / "kronos-source"
    return chronos, kronos, tokenizer, source

def main() -> int:
    ap = argparse.ArgumentParser(description="Run pretrained forecast")
    ap.add_argument("--db", required=True)
    ap.add_argument("--instrument", required=True)
    ap.add_argument("--models-dir", required=True)
    ap.add_argument("--as-of", required=True, help="ISO8601 offset-aware datetime")
    ap.add_argument("--retrieval-cutoff", help="ISO8601 offset-aware datetime")
    ap.add_argument("--years", type=float, default=5.0)
    ap.add_argument("--anchor-bear", type=float)
    ap.add_argument("--anchor-base", type=float)
    ap.add_argument("--anchor-bull", type=float)
    ap.add_argument("--currency", required=True)
    ap.add_argument("--source", default="conflict_fail")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--output")
    ns = ap.parse_args()

    as_of = datetime.fromisoformat(ns.as_of)
    if as_of.tzinfo is None:
        raise ValueError("as_of must be offset-aware")
    ret_cut = datetime.fromisoformat(ns.retrieval_cutoff) if ns.retrieval_cutoff else None
    if ret_cut and ret_cut.tzinfo is None:
        raise ValueError("retrieval_cutoff must be offset-aware")

    daily = load_daily(Path(ns.db), ns.instrument, as_of, ret_cut, required_currency=ns.currency, source_policy=ns.source)
    monthly = to_monthly(daily, as_of)
    if len(monthly) < 32:
        raise RuntimeError(f"insufficient monthly OHLCV history: {len(monthly)} rows")
        
    steps = max(1, round(ns.years * 12))
    
    last_idx = monthly.index[-1]
    target_date = last_idx + pd.DateOffset(months=steps)
    target_dt = target_date.to_pydatetime()
    if target_dt.tzinfo is None:
        target_dt = target_dt.replace(tzinfo=timezone.utc)
        
    chronos_dir, kronos_dir, tokenizer_dir, kronos_source = model_paths(Path(ns.models_dir))

    current_price = float(monthly["close"].iloc[-1])
    
    request = ForecastRequest(
        instrument_id=ns.instrument,
        currency=ns.currency,
        as_of=as_of,
        current_price=current_price,
        target_date=target_dt,
        horizon_steps=steps,
        frequency="ME",
        history=tuple(float(x) for x in monthly["close"].tolist()),
        timestamps=tuple(dt.to_pydatetime() for dt in monthly.index),
        ohlcv=monthly,
        metadata={"price_basis": "split-adjusted"},
        target_semantics="terminal_price"
    )
    
    anchor = None
    if ns.anchor_base is not None:
        anchor = FundamentalAnchor(
            status="PARTIAL",
            instrument_id=ns.instrument,
            currency=ns.currency,
            target_date=target_dt,
            price_basis="split-adjusted",
            value_kind="terminal_price",
            as_of=as_of,
            assumption_refs=("user_supplied_scenario_prices",),
            bear=ns.anchor_bear,
            base=ns.anchor_base,
            bull=ns.anchor_bull,
            evidence_refs=[]
        )

    adapters = [
        KronosAdapter(model_ref=str(kronos_dir), tokenizer_ref=str(tokenizer_dir), device=ns.device, source_root=str(kronos_source)),
        Chronos2Adapter(device_map=ns.device, model_ref=str(chronos_dir)),
    ]
    engine = ForecastingEngine(adapters, ForecastEnsembler(EnsemblePolicy()))
    combined, components = engine.run(request, anchor)
    
    # Engine owns assessment. Do not independently duplicate Monte Carlo or
    # assume fields outside the current assessment contract.
    assessment_dict = (combined.details or {}).get("assessment", {"status": "UNAVAILABLE", "ranking_allowed": False, "reason": "No assessment produced"})
    result = {
        "instrument_id": ns.instrument,
        "as_of": str(request.as_of),
        "target_date": str(request.target_date),
        "years": ns.years,
        "frequency": request.frequency,
        "horizon_steps": steps,
        "history_months": len(monthly),
        "last_close": current_price,
        "components": [
            {
                "model_id": x.model_id,
                "status": x.status,
                "point": x.point,
                "quantiles": {str(k): v for k, v in (x.quantiles or {}).items()},
                "error": x.error,
                "details": dict(x.details),
            }
            for x in components
        ],
        "ensemble": {
            "status": combined.status,
            "point": combined.point,
            "quantiles": {str(k): v for k, v in (combined.quantiles or {}).items()},
            "weights": dict(combined.component_weights),
            "details": dict(combined.details),
        },
        "assessment": assessment_dict
    }
    out = json.dumps(result, indent=2, ensure_ascii=False)
    print(out)
    if ns.output:
        Path(ns.output).write_text(out, encoding="utf-8")
    return 0 if any(c.status in {"COMPLETE", "PARTIAL"} for c in components) else 3

if __name__ == "__main__":
    raise SystemExit(main())
