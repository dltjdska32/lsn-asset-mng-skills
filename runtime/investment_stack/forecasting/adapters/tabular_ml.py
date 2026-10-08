from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from .base import ForecastAdapter
from ..contracts import ForecastRequest, ModelForecast


def _sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


class TabularMLAdapter(ForecastAdapter):
    """Load a safe native XGBoost/LightGBM artifact and forecast terminal price.

    Artifact is a directory containing metadata.json plus a native model file:
      xgboost: model.json
      lightgbm: model.txt

    metadata.json includes model SHA-256 and feature schema. Pickle/joblib loading is
    deliberately unsupported in the production adapter.
    """
    def __init__(self, artifact_path: str | Path, model_id: str | None = None):
        p=Path(artifact_path)
        self.metadata_path = p/'metadata.json' if p.is_dir() else p
        self.model_id_override=model_id
        self._meta: Mapping[str, Any] | None=None
        self._model=None

    @property
    def metadata(self) -> Mapping[str, Any]:
        if self._meta is None:
            obj=json.loads(self.metadata_path.read_text())
            if not isinstance(obj, Mapping): raise TypeError('metadata must be an object')
            self._meta=obj
        return self._meta

    @property
    def model_path(self) -> Path:
        m=self.metadata
        model_file = str(m['model_file'])
        # Reject path escapes before native load
        if '..' in model_file or '/' in model_file or '\\' in model_file:
            raise ValueError(f'model_file must be a flat filename within artifact directory: {model_file}')
        mp = self.metadata_path.parent / model_file
        # Resolve path and check it's confined to the artifact directory
        try:
            if not mp.resolve().is_relative_to(self.metadata_path.parent.resolve()):
                raise ValueError("model path escapes artifact directory")
        except Exception:
            raise ValueError("model path escapes artifact directory")
        return mp

    def _verify(self) -> None:
        m=self.metadata
        required=['model_type','model_file','model_sha256','feature_names', 'horizon_years', 'training_cutoff', 'validation_cutoff']
        miss=[k for k in required if not m.get(k)]
        if miss: raise ValueError(f'artifact metadata missing: {miss}')
        
        mp = self.model_path
        if not mp.is_file(): raise FileNotFoundError(mp)
        actual=_sha256(mp)
        if actual.lower()!=str(m['model_sha256']).lower():
            raise ValueError('model SHA-256 mismatch')

    def available(self) -> tuple[bool, str | None]:
        try:
            self._verify(); return True,None
        except Exception as exc:
            return False,f'{type(exc).__name__}: {exc}'

    @property
    def model(self):
        if self._model is None:
            self._verify(); mt=str(self.metadata['model_type'])
            if mt=='xgboost':
                from xgboost import XGBRegressor
                model=XGBRegressor(); model.load_model(self.model_path)
            elif mt=='lightgbm':
                import lightgbm as lgb
                model=lgb.Booster(model_file=str(self.model_path))
            else:
                raise ValueError(f'unsupported model_type: {mt}')
            self._model=model
        return self._model

    def forecast(self, request: ForecastRequest) -> ModelForecast:
        model_id=self.model_id_override
        try:
            request.validate()
            meta=self.metadata
            model_id=model_id or str(meta.get('model_id') or 'tabular-ml')
            
            req_dt = pd.to_datetime(request.as_of, errors='coerce')
            if pd.isna(req_dt) or getattr(req_dt, 'tzinfo', None) is None:
                raise ValueError("request as_of must be a valid timezone-aware datetime")
            req_as_of = pd.to_datetime(request.as_of, utc=True)

            # Require all cutoffs
            for cutoff_key in ['training_cutoff', 'validation_cutoff', 'evaluation_cutoff']:
                cutoff = meta.get(cutoff_key)
                if not cutoff:
                    raise ValueError(f"metadata missing {cutoff_key}")
                dt = pd.to_datetime(cutoff, errors='coerce')
                if pd.isna(dt) or getattr(dt, 'tzinfo', None) is None:
                    raise ValueError(f"naive or invalid {cutoff_key}: {cutoff}")
                if pd.to_datetime(cutoff, utc=True) > req_as_of:
                    raise ValueError(f"{cutoff_key} {cutoff} is after request as_of {req_as_of}")
            
            if pd.to_datetime(meta['training_cutoff']) >= pd.to_datetime(meta['validation_cutoff']):
                raise ValueError("training_cutoff >= validation_cutoff")
            if pd.to_datetime(meta['validation_cutoff']) >= pd.to_datetime(meta['evaluation_cutoff']):
                raise ValueError("validation_cutoff >= evaluation_cutoff")
            
            # Enforce horizon and target
            target = meta.get('target')
            if not target: raise ValueError("metadata missing target")
            if not isinstance(target, str):
                raise ValueError("artifact target must be string")
            
            # Names alone cannot prove the trained target or its units.
            if meta.get("schema_version") != 1:
                raise ValueError("artifact schema_version=1 is required")
            if not isinstance(meta.get("feature_schema"), dict):
                raise ValueError("artifact feature_schema required")
            if not meta.get("currency") or not meta.get("price_basis"):
                raise ValueError("artifact currency and price_basis must be explicit")
            if meta.get("target_kind") != "price_cagr" or meta.get("target_unit") != "annual_decimal":
                raise ValueError("artifact target is not annual decimal price CAGR")
            if meta.get("currency") not in (None, request.currency) or meta.get("price_basis") not in (None, request.metadata["price_basis"]):
                raise ValueError("artifact currency or price basis mismatch")
            # v1 price-CAGR artifacts are trained on a whole number of
            # calendar years with monthly end-of-month 12*N cadence.
            # Every identifier and cadence must agree; no +/-0.1-year alias.
            trained_horizon = meta.get('horizon_years')
            if (isinstance(trained_horizon, bool) or
                    not isinstance(trained_horizon, (int, float)) or
                    not math.isfinite(float(trained_horizon)) or
                    float(trained_horizon) <= 0 or
                    not float(trained_horizon).is_integer()):
                raise ValueError("artifact requires positive integer calendar horizon years")
            years = int(trained_horizon)
            expected_target = f"future_cagr_{years}y"
            expected_model_id = f"{meta['model_type']}-tabular-{years}y"
            if target != expected_target:
                raise ValueError("artifact target and trained horizon disagree")
            if meta.get('model_id') != expected_model_id or model_id != expected_model_id:
                raise ValueError("artifact model identity and trained horizon disagree")
            if meta.get('model_type') not in {'xgboost', 'lightgbm'}:
                raise ValueError("unsupported model type")
            if (meta.get('frequency') != 'ME' or
                    meta.get('horizon_steps') != years * 12):
                raise ValueError("artifact cadence and trained horizon disagree")
            if (request.frequency != 'ME' or
                    request.horizon_steps != years * 12):
                raise ValueError("request cadence/horizon mismatches trained artifact")
            requested_years = float(years)

            names=list(meta.get('feature_names') or [])
            features=dict(request.metadata.get('ml_features') or {})
            if not names: raise ValueError('artifact missing feature_names')
            if any(n not in meta['feature_schema'] or not meta['feature_schema'][n].get('unit') for n in names):
                raise ValueError('missing feature unit schema')
            units = request.metadata.get("ml_feature_units")
            if not isinstance(units, dict) or any(
                units.get(n) != meta["feature_schema"][n].get("unit") for n in names
            ):
                raise ValueError("inference feature units do not match artifact feature schema")
            forbidden = ("target", "label", "outcome", "future", "forward", "next_")
            if any(any(term in n.lower() for term in forbidden) for n in names):
                raise ValueError("target/forward-looking feature leakage")
            missing=[n for n in names if n not in features]
            if missing: raise ValueError(f'missing ML features: {missing}')
            
            # Ensure features have timestamps and aren't after as_of
            feature_timestamps = dict(request.metadata.get('ml_feature_timestamps') or {})
                
            for n in names:
                if n not in feature_timestamps:
                    raise ValueError(f'missing publication timestamp for feature: {n}')
                ts_raw = feature_timestamps[n]
                dt = pd.to_datetime(ts_raw, errors='coerce')
                if pd.isna(dt) or getattr(dt, 'tzinfo', None) is None:
                    raise ValueError(f"naive or invalid publication timestamp for feature {n}")
                
                ts = pd.to_datetime(ts_raw, utc=True)
                if ts > req_as_of:
                    raise ValueError(f'feature {n} published at {ts} is after request as_of {req_as_of}')
                
                if isinstance(features[n], bool):
                    raise ValueError(f'boolean feature {n} not allowed')
                    
            vals_array=np.asarray([[features[n] for n in names]],dtype=float)
            if not np.all(np.isfinite(vals_array)): raise ValueError('non-finite ML feature')
            vals=pd.DataFrame(vals_array,columns=names)
            
            current=float(request.current_price)
            if not math.isfinite(current) or current<=0: raise ValueError('invalid current price')
            
            # Validate BEFORE using model
            model = self.model
            
            cagr=float(np.asarray(model.predict(vals)).reshape(-1)[0])
            if not math.isfinite(cagr) or cagr<=-0.95 or cagr>2.0: raise ValueError(f'implausible predicted CAGR: {cagr}')
            
            years = requested_years
            terminal=current*((1.0+cagr)**years)
            residual_q=meta.get('residual_quantiles') or {}
            
            # Require sample evidence for residual_q
            oos_metrics = meta.get('oos_metrics') or {}
            val_metrics = oos_metrics.get('validation') or {}
            n_samples = val_metrics.get('n', 0)
            
            q={}
            if residual_q and n_samples > 0:
                has_all_q = True
                for key in (0.1, 0.25, 0.5, 0.75, 0.9):
                    k_str = str(key)
                    if k_str not in residual_q and key not in residual_q:
                        has_all_q = False
                        break
                
                if has_all_q:
                    for key in (0.1, 0.25, 0.5, 0.75, 0.9):
                        delta = float(residual_q.get(str(key), residual_q.get(key)))
                        q[key] = current * ((1.0 + max(-0.95, cagr + delta)) ** years)
            
            status = 'COMPLETE' if q else 'PARTIAL'
            validation_level = 'EXPERIMENTAL'
            
            return ModelForecast(
                model_id=model_id,
                status=status,
                instrument_id=request.instrument_id,
                currency=request.currency,
                as_of=request.as_of,
                target_date=request.target_date,
                price_basis=request.metadata.get('price_basis', 'unknown'),
                horizon_steps=request.horizon_steps,
                frequency=request.frequency,
                target_semantics=request.target_semantics,
                point=terminal,
                quantiles=q,
                details={
                    'predicted_cagr':cagr,'feature_names':names,
                    'training_cutoff':meta.get('training_cutoff'),'validation_cutoff':meta.get('validation_cutoff'),
                    'evaluation_cutoff':meta.get('evaluation_cutoff'),
                    'oos_metrics':oos_metrics,'artifact_metadata':str(self.metadata_path),
                    'model_sha256':meta.get('model_sha256'),'serialization':meta.get('serialization'),
                    'validation_level': validation_level,
                },
            )
        except Exception as exc:
            return ModelForecast(
                model_id=model_id or 'tabular-ml',
                status='UNAVAILABLE',
                instrument_id=request.instrument_id,
                currency=request.currency,
                as_of=request.as_of,
                target_date=request.target_date,
                price_basis=request.metadata.get('price_basis', 'unknown'),
                horizon_steps=request.horizon_steps,
                frequency=request.frequency,
                target_semantics=request.target_semantics,
                error=f'{type(exc).__name__}: {exc}',
                details={'artifact_metadata':str(self.metadata_path)},
            )
