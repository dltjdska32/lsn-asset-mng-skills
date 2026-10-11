from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .base import ForecastAdapter
from ..contracts import ForecastRequest, ModelForecast


class FinCastAdapter(ForecastAdapter):
    model_id = "Vincent05R/FinCast-v1"

    def __init__(self, model_path: str | None = None, backend: str = "cpu", runner: Any | None = None,
                 allow_pickle_checkpoint: bool = False):
        self.model_path = model_path
        self.backend = backend
        self._runner = runner
        self.allow_pickle_checkpoint = allow_pickle_checkpoint

    def available(self) -> tuple[bool, str | None]:
        if self._runner is not None:
            return True, None
        if not self.allow_pickle_checkpoint:
            return False, "FinCast v1 official main checkpoint is pickle-based .pth; explicit opt-in required"
        if importlib.util.find_spec("tools.inference_utils") is None:
            return False, "FinCast official src directory is not installed on PYTHONPATH"
        if not self.model_path or not Path(self.model_path).is_file():
            return False, "FinCast checkpoint path is missing"
        return True, None

    @staticmethod
    def build_config(data_path: str, model_path: str, output_path: str, request: ForecastRequest, backend: str = "cpu"):
        cfg = SimpleNamespace()
        cfg.backend = backend
        cfg.model_path = model_path
        cfg.model_version = "v1"
        cfg.data_path = data_path
        cfg.data_frequency = request.frequency
        cfg.context_len = min(max(len(request.history), 32), 1024)
        cfg.horizon_len = min(request.horizon_steps, 256)
        cfg.all_data = False
        cfg.columns_target = [request.target]
        cfg.series_norm = False
        cfg.batch_size = 1
        cfg.forecast_mode = "median"
        cfg.quantile_outputs = [1, 2, 5, 8, 9]
        cfg.save_output = True
        cfg.save_output_path = output_path
        cfg.plt_outputs = False
        cfg.plt_quantiles = []
        return cfg

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
        if request.horizon_steps > 256:
            return ModelForecast(
                model_id=self.model_id, status="UNAVAILABLE", error="FinCast v1 inference horizon must be <=256 steps",
                instrument_id=request.instrument_id, currency=request.currency,
                as_of=request.as_of, target_date=request.target_date,
                price_basis=request.metadata.get("price_basis", "unknown"),
                horizon_steps=request.horizon_steps, frequency=request.frequency,
                target_semantics=request.target_semantics
            )
        if self._runner is None:
            return ModelForecast(
                model_id=self.model_id, status="UNAVAILABLE", error="FinCast file-oriented bridge runner is not configured",
                instrument_id=request.instrument_id, currency=request.currency,
                as_of=request.as_of, target_date=request.target_date,
                price_basis=request.metadata.get("price_basis", "unknown"),
                horizon_steps=request.horizon_steps, frequency=request.frequency,
                target_semantics=request.target_semantics
            )
        try:
            result = self._runner(request)
            if isinstance(result, ModelForecast):
                result.validate(); return result
            point = float(result["point"])
            quantiles = {float(k): float(v) for k, v in result.get("quantiles", {}).items()}
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
                details={"model_version": "v1", "backend": self.backend, "checkpoint_format": "pth"}
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
