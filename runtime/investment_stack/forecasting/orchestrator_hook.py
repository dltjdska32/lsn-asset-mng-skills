"""Forecasting integration hook.

Call after valuation inputs are validated and before capital competition. Foundation-model
and tabular-ML outputs are supplemental; they never replace the evidence-backed valuation anchor.
"""
from __future__ import annotations

from .adapters import Chronos2Adapter, FinCastAdapter, KronosAdapter, TabularMLAdapter
from .engine import ForecastingEngine
from .ensemble import ForecastEnsembler, EnsemblePolicy


def build_default_forecasting_engine(
    *,
    chronos_model_ref: str | None = None,
    kronos_model_ref: str | None = None,
    kronos_tokenizer_ref: str | None = None,
    kronos_source_root: str | None = None,
    fincast_checkpoint: str | None = None,
    enable_fincast_pickle: bool = False,
    xgboost_artifact: str | None = None,
    lightgbm_artifact: str | None = None,
    device: str = "cpu",
) -> ForecastingEngine:
    adapters = [
        KronosAdapter(model_ref=kronos_model_ref, tokenizer_ref=kronos_tokenizer_ref, source_root=kronos_source_root, device=device),
        Chronos2Adapter(device_map=device, model_ref=chronos_model_ref),
    ]
    if xgboost_artifact:
        adapters.append(TabularMLAdapter(xgboost_artifact, model_id="xgboost-tabular-5y"))
    if lightgbm_artifact:
        adapters.append(TabularMLAdapter(lightgbm_artifact, model_id="lightgbm-tabular-5y"))
    if fincast_checkpoint or enable_fincast_pickle:
        adapters.append(FinCastAdapter(
            model_path=fincast_checkpoint,
            backend="gpu" if device.startswith("cuda") else "cpu",
            allow_pickle_checkpoint=enable_fincast_pickle,
        ))
    return ForecastingEngine(adapters, ForecastEnsembler(EnsemblePolicy()))
