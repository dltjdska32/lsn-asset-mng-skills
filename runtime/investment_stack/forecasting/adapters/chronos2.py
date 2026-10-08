from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .base import ForecastAdapter
from ..contracts import ForecastRequest, ModelForecast


class Chronos2Adapter(ForecastAdapter):
    model_id = "autogluon/chronos-2-small"

    def __init__(self, device_map: str = "cpu", model_ref: str | None = None, pipeline: Any | None = None):
        self.device_map = device_map
        self.model_ref = model_ref or self.model_id
        self._pipeline = pipeline

    def available(self) -> tuple[bool, str | None]:
        if self._pipeline is not None:
            return True, None
        mr = self.model_ref
        if mr:
            p = Path(mr).expanduser()
            if not p.is_absolute() and not mr.startswith(('./', '../')):
                return False, f"model_ref must be an absolute or explicit local path, got: {mr}"
            if '..' in p.parts: return False, "path traversal not allowed"
            if not p.exists(): return False, f"local model path not found: {mr}"
            man = p / "snapshot_manifest.json"
            if not man.exists(): return False, f"missing snapshot_manifest.json in {mr}"
        if importlib.util.find_spec("chronos") is None:
            return False, "chronos-forecasting package is not installed"
        return True, None

    def _load(self):
        if self._pipeline is None:
            from ..integrity import verify_snapshot_manifest
            p = Path(self.model_ref).expanduser()
            verify_snapshot_manifest(p, self.model_id)
            from chronos import BaseChronosPipeline
            # Fail closed on download, local_files_only=True
            self._pipeline = BaseChronosPipeline.from_pretrained(str(p), device_map=self.device_map, local_files_only=True)
        return self._pipeline

    @staticmethod
    def _future_timestamps(request: ForecastRequest) -> list[pd.Timestamp]:
        last = pd.Timestamp(request.timestamps[-1]) if request.timestamps else pd.Timestamp(request.as_of)
        offset = pd.tseries.frequencies.to_offset(request.frequency)
        return [last + offset * (i + 1) for i in range(request.horizon_steps)]

    def forecast(self, request: ForecastRequest) -> ModelForecast:
        request.validate()
        ok, reason = self.available()
        if not ok:
            return ModelForecast(
                model_id=self.model_id, status="UNAVAILABLE", error=reason,
                instrument_id=request.instrument_id, currency=request.currency,
                as_of=request.as_of, target_date=request.target_date,
                price_basis=request.metadata.get("price_basis", "unknown"),
                horizon_steps=request.horizon_steps, frequency=request.frequency,
                target_semantics=request.target_semantics
            )
        try:
            hist = np.asarray(request.history, dtype=float)
            if hist.size < 16:
                return ModelForecast(
                    model_id=self.model_id, status="UNAVAILABLE", error="insufficient history",
                    instrument_id=request.instrument_id, currency=request.currency,
                    as_of=request.as_of, target_date=request.target_date,
                    price_basis=request.metadata.get("price_basis", "unknown"),
                    horizon_steps=request.horizon_steps, frequency=request.frequency,
                    target_semantics=request.target_semantics
                )
            if request.timestamps:
                ts = pd.to_datetime(list(request.timestamps))
            else:
                ts = pd.date_range(end=pd.Timestamp(request.as_of), periods=len(hist), freq=request.frequency)
            context_df = pd.DataFrame({"id": request.instrument_id, "timestamp": ts, "target": hist})
            future_df = pd.DataFrame({"id": request.instrument_id, "timestamp": self._future_timestamps(request)})
            for name, values in request.covariates.items():
                vals = list(values)
                if len(vals) == len(hist):
                    context_df[name] = vals
                elif len(vals) == request.horizon_steps:
                    future_df[name] = vals
                elif len(vals) == len(hist) + request.horizon_steps:
                    context_df[name] = vals[:len(hist)]
                    future_df[name] = vals[len(hist):]
                else:
                    raise ValueError(f"covariate {name} has unsupported length")
            pred = self._load().predict_df(
                context_df,
                future_df=future_df,
                prediction_length=request.horizon_steps,
                quantile_levels=[0.1, 0.25, 0.5, 0.75, 0.9],
                id_column="id", timestamp_column="timestamp", target="target",
            )
            if not isinstance(pred, pd.DataFrame) or len(pred) != request.horizon_steps:
                raise ValueError("Chronos prediction path length mismatch")
            expected_dates = pd.date_range(start=request.timestamps[-1], periods=request.horizon_steps + 1, freq=request.frequency)[1:]
            if not {"id", "timestamp"}.issubset(pred.columns):
                raise ValueError("Chronos returned no ID/timestamp path")
            if not pred["id"].eq(request.instrument_id).all():
                raise ValueError("Chronos instrument ID mismatch")
            returned = pd.to_datetime(pred["timestamp"], utc=True)
            if list(returned) != list(pd.to_datetime(expected_dates, utc=True)):
                raise ValueError("Chronos timestamp path mismatch")
            numeric_columns = [c for c in pred if c not in ("id", "timestamp")]
            if not numeric_columns or not np.isfinite(pred[numeric_columns].to_numpy(dtype=float)).all():
                raise ValueError("Chronos nonfinite prediction")
            # All returned steps must satisfy the price and quantile contracts,
            # not merely the terminal step validated by ModelForecast.
            price_cols = [c for c in ("predictions", "0.1", "0.25", "0.5", "0.75", "0.9") if c in pred]
            if not price_cols or (pred[price_cols].to_numpy(dtype=float) <= 0).any():
                raise ValueError("Chronos nonpositive price anywhere in path")
            quantile_cols = [c for c in ("0.1", "0.25", "0.5", "0.75", "0.9") if c in pred]
            if len(quantile_cols) > 1 and (np.diff(pred[quantile_cols].to_numpy(dtype=float), axis=1) < 0).any():
                raise ValueError("Chronos crossing quantiles anywhere in path")
            last = pred.iloc[-1]
            point = float(last["predictions"] if "predictions" in last else last["0.5"])
            quantiles = {q: float(last[str(q)]) for q in (0.1, 0.25, 0.5, 0.75, 0.9) if str(q) in last}
            out = ModelForecast(
                model_id=self.model_id,
                status="COMPLETE",
                instrument_id=request.instrument_id,
                currency=request.currency,
                as_of=request.as_of,
                target_date=request.target_date,
                price_basis=request.metadata.get("price_basis", "unknown"),
                horizon_steps=request.horizon_steps,
                frequency=request.frequency,
                target_semantics=request.target_semantics,
                point=point,
                quantiles=quantiles,
                details={"provider": "BaseChronosPipeline", "model_ref": self.model_ref, "target": request.target}
            )
            out.validate(); return out
        except Exception as exc:
            return ModelForecast(
                model_id=self.model_id, status="ERROR", error=f"{type(exc).__name__}: {exc}",
                instrument_id=request.instrument_id, currency=request.currency,
                as_of=request.as_of, target_date=request.target_date,
                price_basis=request.metadata.get("price_basis", "unknown"),
                horizon_steps=request.horizon_steps, frequency=request.frequency,
                target_semantics=request.target_semantics
            )
