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

    @staticmethod
    def _provider_timestamps(values: Any) -> pd.DatetimeIndex:
        """Express validated instants as UTC-naive datetime64 for Chronos 2.3.x.

        Its normalize_df casts a NumPy datetime64 array to int64. Feeding
        timezone-aware pandas timestamps produces an object array instead.
        Convert to UTC *before* removing tz metadata to preserve the instant.
        """
        return pd.DatetimeIndex(pd.to_datetime(list(values), utc=True)).tz_localize(None)

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
                observed_dates = request.timestamps
            else:
                observed_dates = pd.date_range(
                    end=pd.Timestamp(request.as_of), periods=len(hist), freq=request.frequency
                )
            # Keep the request's aware, PIT-validated calendar as the sole
            # authority. Both provider input and expected output use the same
            # aware instants, converted to UTC at the provider boundary.
            future_dates = self._future_timestamps(request)
            context_df = pd.DataFrame({
                "id": request.instrument_id,
                "timestamp": self._provider_timestamps(observed_dates),
                "target": hist,
            })
            future_df = pd.DataFrame({
                "id": request.instrument_id,
                "timestamp": self._provider_timestamps(future_dates),
            })
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
            # The same future_dates supplied to the provider determine the
            # exact expected UTC path; do not independently regenerate dates.
            if not pred.columns.is_unique:
                raise ValueError("Chronos duplicate return columns")
            if not {"id", "timestamp"}.issubset(pred.columns):
                raise ValueError("Chronos returned no ID/timestamp path")
            if not pred["id"].notna().all() or not pred["id"].eq(request.instrument_id).fillna(False).all():
                raise ValueError("Chronos instrument ID mismatch")
            returned = pd.to_datetime(pred["timestamp"], utc=True)
            if list(returned) != list(pd.to_datetime(future_dates, utc=True)):
                raise ValueError("Chronos timestamp path mismatch")
            # Chronos 2.3.2 supplies a string target_name column. Unlike an
            # unbound annotation, it is an identity contract for the target
            # column named "target" in context_df. Older stubs may omit it.
            if "target_name" in pred and (
                not pred["target_name"].notna().all()
                or not pred["target_name"].eq("target").fillna(False).all()
            ):
                raise ValueError("Chronos target_name identity mismatch")
            allowed = {"id", "timestamp", "target_name", "predictions",
                       "0.1", "0.25", "0.5", "0.75", "0.9"}
            unexpected = set(pred.columns) - allowed
            if unexpected:
                raise ValueError(f"Chronos unexpected return columns: {sorted(map(str, unexpected))}")
            # Inspect only explicitly supported numeric price/quantile columns;
            # do not silently ignore arbitrary text or unbound extra outputs.
            price_cols = [c for c in ("predictions", "0.1", "0.25", "0.5", "0.75", "0.9") if c in pred]
            if not ("predictions" in pred or "0.5" in pred):
                raise ValueError("Chronos missing point/median prediction column")
            if not np.isfinite(pred[price_cols].to_numpy(dtype=float)).all():
                raise ValueError("Chronos nonfinite prediction")
            # All returned steps must satisfy the price and quantile contracts,
            # not merely the terminal step validated by ModelForecast.
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
