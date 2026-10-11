from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Any

import numpy as np


@dataclass(frozen=True)
class BacktestMetrics:
    model_id: str
    n: int
    mae: float
    mape: float
    directional_accuracy: float
    calibration_error: float | None = None

    @property
    def reliability(self) -> float:
        # Bounded score used only for relative ensemble weighting.
        # 1/(1+MAPE) avoids pretending the score is a probability.
        return 1.0 / (1.0 + max(self.mape, 0.0))


def evaluate_points(model_id: str, actual: Iterable[float], predicted: Iterable[float], reference: Iterable[float]) -> BacktestMetrics:
    a = np.asarray(list(actual), dtype=float)
    p = np.asarray(list(predicted), dtype=float)
    r = np.asarray(list(reference), dtype=float)
    if not (len(a) == len(p) == len(r)) or len(a) == 0:
        raise ValueError("actual/predicted/reference length mismatch or empty")
        
    if not (np.all(np.isfinite(a)) and np.all(np.isfinite(p)) and np.all(np.isfinite(r))):
        raise ValueError("non-finite values in observations")
        
    if not (np.all(a > 0) and np.all(r > 0)):
        raise ValueError("prices must be strictly positive")

    mae = float(np.mean(np.abs(a - p)))
    mape = float(np.mean(np.abs((a - p) / a)))
    
    # separate return domain
    actual_ret = a / r - 1.0
    pred_ret = p / r - 1.0
    actual_dir = np.sign(actual_ret)
    pred_dir = np.sign(pred_ret)
    directional = float(np.mean(actual_dir == pred_dir))
    return BacktestMetrics(model_id, len(a), mae, mape, directional)


def reliability_map(metrics: Iterable[BacktestMetrics]) -> Mapping[str, float]:
    ms = list(metrics)
    if not ms:
        return {}
    raw = {m.model_id: m.reliability for m in ms}
    mean = np.mean(list(raw.values()))
    if mean <= 0:
        return {k: 1.0 for k in raw}
    # Center around 1.0 so priors remain interpretable.
    return {k: float(v / mean) for k, v in raw.items()}


def reliability_from_walkforward_results(
    results: Mapping[str, Mapping[str, Any]],
    *,
    experimental_compat: bool = False
) -> Mapping[str, float]:
    """Convert comparable OOS metrics into relative ensemble multipliers.

    Expected input per model: {"mae": <points>, "directional_accuracy": <0..1>}.
    """
    raw: dict[str, float] = {}
    
    if not experimental_compat:
        scopes = []
        for m_id, m in results.items():
            scope = m.get("scope") or m.get("metrics_scope")
            horizon = m.get("horizon_steps")
            n = m.get("n")
            if not scope or not horizon or not n or n <= 0:
                raise ValueError(f"Model {m_id} missing valid scope/horizon/n for trusted OOS weighting")
            scopes.append((scope, horizon))
            
        if len(set(scopes)) > 1:
            raise ValueError("Cannot weight models with differing validated scope/horizon")
            
    for model_id, m in results.items():
        mae = float(m.get("mae", float("nan")))
        direction = float(m.get("directional_accuracy", float("nan")))
        if not np.isfinite(mae) or mae < 0:
            continue
        if not np.isfinite(direction):
            raise ValueError(f"directional_accuracy missing or non-finite for model {model_id}")
                
        direction = min(1.0, max(0.0, direction))
        raw[model_id] = (max(direction, 1e-6)) / max(mae, 1e-6)
        
    if not raw:
        return {}
    mean = float(np.mean(list(raw.values())))
    if mean <= 0 or not np.isfinite(mean):
        return {}
    return {k: float(v / mean) for k, v in raw.items()}
