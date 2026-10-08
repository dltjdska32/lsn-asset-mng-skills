from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence
import pandas as pd
import numpy as np


@dataclass(frozen=True)
class LeakageCheck:
    ok: bool
    violations: int
    checked_rows: int
    details: tuple[str, ...]

@dataclass
class PITSplit:
    train: pd.DataFrame
    valid: pd.DataFrame
    test: pd.DataFrame


def _is_aware_and_valid(val):
    if pd.isna(val): return False
    dt = pd.to_datetime(val, errors='coerce')
    if pd.isna(dt): return False
    return getattr(dt, 'tzinfo', None) is not None

def enforce_point_in_time(
    df: pd.DataFrame,
    *,
    as_of_col: str = "as_of",
    published_at_cols: Sequence[str] = (),
    target_col: str = "future_cagr_5y",
    instrument_col: str = "instrument_id",
) -> LeakageCheck:
    """Validate that every feature was knowable at the observation `as_of` time.

    Each feature source should carry a publication timestamp column, e.g.
    `financial_published_at`, `macro_published_at`, `price_observed_at`.
    Any publication timestamp after `as_of` is a look-ahead violation.
    """
    details=[]; violations=0
    if as_of_col not in df.columns:
        return LeakageCheck(False,len(df),len(df),(f"missing {as_of_col}",))
        
    bad_asof = df[as_of_col].apply(lambda x: not _is_aware_and_valid(x))
    if bad_asof.any():
        n=int(bad_asof.sum()); violations+=n; details.append(f"invalid/naive as_of rows: {n}")
        
    as_of=pd.to_datetime(df[as_of_col],utc=True,errors='coerce')
    
    for col in published_at_cols:
        if col not in df.columns:
            violations+=len(df); details.append(f"missing publication timestamp column: {col}"); continue
            
        bad_pub = df[col].apply(lambda x: not _is_aware_and_valid(x))
        if bad_pub.any():
            n=int(bad_pub.sum()); violations+=n; details.append(f"invalid/naive {col} rows: {n}")
            
        pub=pd.to_datetime(df[col],utc=True,errors='coerce')
        # Check look-ahead: pub > as_of
        bad_lookahead = pub > as_of
        if bad_lookahead.any():
            n=int(bad_lookahead.sum()); violations+=n; details.append(f"{col} look-ahead rows: {n}")
            
    if target_col in df.columns:
        target=pd.to_numeric(df[target_col],errors='coerce')
        if target.isna().any():
            n=int(target.isna().sum()); violations+=n; details.append(f"target missing/invalid rows: {n}")
            
    if instrument_col not in df.columns:
        violations+=len(df); details.append(f"missing {instrument_col}")
        
    return LeakageCheck(violations==0,violations,len(df),tuple(details))


def purged_time_split(
    df: pd.DataFrame,
    *,
    date_col: str = "as_of",
    label_avail_col: str = "future_as_of",
    fit_cutoff: pd.Timestamp | str,
    calibration_cutoff: pd.Timestamp | str,
    evaluation_cutoff: pd.Timestamp | str | None = None,
) -> PITSplit:
    """Split data into train, valid, test enforcing strict cutoffs to avoid look-ahead bias."""
    
    def _parse_strict(c):
        if not _is_aware_and_valid(c):
            raise ValueError(f"Cutoff {c} must be tz-aware")
        return pd.to_datetime(c, utc=True)
        
    fit_c = _parse_strict(fit_cutoff)
    cal_c = _parse_strict(calibration_cutoff)
    
    if fit_c >= cal_c:
        raise ValueError("fit_cutoff must be < calibration_cutoff")
    
    if evaluation_cutoff is not None:
        eval_c = _parse_strict(evaluation_cutoff)
        if cal_c >= eval_c:
             raise ValueError("calibration_cutoff must be < evaluation_cutoff")
    else:
        raise ValueError("evaluation_cutoff is mandatory")

    if df[date_col].apply(lambda x: not _is_aware_and_valid(x)).any():
        raise ValueError(f"Naive or invalid dates found in {date_col}")
    if df[label_avail_col].apply(lambda x: not _is_aware_and_valid(x)).any():
        raise ValueError(f"Naive or invalid dates found in {label_avail_col}")

    d = pd.to_datetime(df[date_col], utc=True)
    l = pd.to_datetime(df[label_avail_col], utc=True)
    
    if (l < d).any():
        raise ValueError("Label available before observation")

    # training: feature obs <= fit_cutoff, label avail <= fit_cutoff
    tr_mask = (d <= fit_c) & (l <= fit_c)
    tr = df[tr_mask].copy()
    
    # validation: feature obs > fit_cutoff, label avail <= cal_c
    va_mask = (d > fit_c) & (l <= cal_c)
    va = df[va_mask].copy()
    
    # test: feature obs > cal_c, label avail <= eval_c
    te_mask = (d > cal_c) & (l <= eval_c)
    te = df[te_mask].copy()
    
    if tr.empty or va.empty or te.empty:
        raise ValueError("Non-empty train, valid, and test sets required")
    
    return PITSplit(train=tr, valid=va, test=te)


def add_forward_cagr_from_prices(
    prices: pd.DataFrame,
    *,
    instrument_col: str = "instrument_id",
    date_col: str = "as_of",
    price_col: str = "price",
    years: int = 5,
    tolerance_days: int = 45,
) -> pd.DataFrame:
    """Create training targets using future prices without exposing them as features.

    For each row, match the first observation strictly near `as_of + years` within tolerance.
    """
    if years<=0: raise ValueError('years must be positive')
    x=prices[[instrument_col,date_col,price_col]].copy()
    if x[date_col].apply(lambda v: not _is_aware_and_valid(v)).any():
        raise ValueError("Naive or invalid dates found in prices date_col")
    x[date_col]=pd.to_datetime(x[date_col],utc=True)
    
    x[price_col]=pd.to_numeric(x[price_col],errors='coerce')
    if x[price_col].isna().any():
        raise ValueError("Invalid prices found")
    x=x.sort_values([instrument_col,date_col])
    out=[]
    tol=pd.Timedelta(days=tolerance_days)
    for inst,g in x.groupby(instrument_col,sort=False):
        gd=g.reset_index(drop=True); dates=gd[date_col]; vals=gd[price_col].to_numpy(float)
        for i,(d,p) in enumerate(zip(gd[date_col],vals)):
            if p<=0: continue
            target=d+pd.DateOffset(years=years)
            pos=int(dates.searchsorted(target,side='left'))
            candidates=[]
            for k in (pos-1,pos,pos+1):
                if 0<=k<len(gd):
                    c_date = gd.loc[k,date_col]
                    delta=abs(c_date-target)
                    # Candidate must be strictly in the future (after as_of)
                    if c_date > d and delta<=tol: 
                        candidates.append((delta,k))
            if not candidates: continue
            _,k=min(candidates,key=lambda z:z[0])
            fp=float(vals[k])
            if fp<=0: continue
            c_date = gd.loc[k,date_col]
            actual_years = (c_date - d).days / 365.25
            if actual_years <= 0: continue
            cagr=(fp/p)**(1.0/actual_years)-1.0
            out.append({instrument_col:inst,date_col:d,price_col:p,'future_as_of':c_date,'future_price':fp,f'future_cagr_{years}y':cagr})
    return pd.DataFrame(out)


def join_features_asof(
    base: pd.DataFrame,
    features: pd.DataFrame,
    *,
    instrument_col: str='instrument_id',
    as_of_col: str='as_of',
    feature_published_col: str='published_at',
    feature_cols: Sequence[str]=(),
) -> pd.DataFrame:
    """Point-in-time asof join: for each base row use latest feature published <= as_of."""
    b=base.copy(); f=features.copy()
    if b[as_of_col].apply(lambda v: not _is_aware_and_valid(v)).any():
        raise ValueError("Naive or invalid dates in base as_of_col")
    if f[feature_published_col].apply(lambda v: not _is_aware_and_valid(v)).any():
        raise ValueError("Naive or invalid dates in features feature_published_col")
    b[as_of_col]=pd.to_datetime(b[as_of_col],utc=True); f[feature_published_col]=pd.to_datetime(f[feature_published_col],utc=True)
    b=b.sort_values([instrument_col,as_of_col]); f=f.sort_values([instrument_col,feature_published_col])
    chunks=[]
    for inst,bg in b.groupby(instrument_col,sort=False):
        fg=f[f[instrument_col]==inst]
        if fg.empty:
            tmp=bg.copy()
            for c in feature_cols: tmp[c]=np.nan
            tmp[feature_published_col]=pd.NaT
        else:
            keep=[instrument_col,feature_published_col,*feature_cols]
            tmp=pd.merge_asof(bg.sort_values(as_of_col),fg[keep].sort_values(feature_published_col),left_on=as_of_col,right_on=feature_published_col,direction='backward')
            if instrument_col+'_x' in tmp.columns:
                tmp[instrument_col]=tmp[instrument_col+'_x']; tmp=tmp.drop(columns=[instrument_col+'_x',instrument_col+'_y'])
        chunks.append(tmp)
    return pd.concat(chunks,ignore_index=True) if chunks else b.iloc[:0]
