from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np


@dataclass(frozen=True)
class MonteCarloResult:
    paths: int
    horizon_steps: int
    terminal_quantiles: Mapping[float, float]
    loss_probability: float
    representative_price_cagr: float
    median_cagr: float
    expected_cumulative_return: float
    expected_cagr: float
    assumptions: str

def simulate_terminal_distribution(
    current_price: float,
    target_median: float,
    historical_prices: Sequence[float],
    horizon_steps: int,
    paths: int = 10000,
    seed: int = 7,
    history_frequency_steps_per_year: int = 12,
    horizon_years: float = 5.0,
) -> MonteCarloResult:
    import math
    if isinstance(current_price, bool) or not isinstance(current_price, (int, float)) or math.isnan(current_price) or math.isinf(current_price) or current_price <= 0:
        raise ValueError("current_price must be positive finite number")
    if isinstance(target_median, bool) or not isinstance(target_median, (int, float)) or math.isnan(target_median) or math.isinf(target_median) or target_median <= 0:
        raise ValueError("target_median must be positive finite number")
    if isinstance(horizon_steps, bool) or not isinstance(horizon_steps, int) or horizon_steps <= 0:
        raise ValueError("horizon_steps must be positive integer")
    if isinstance(paths, bool) or not isinstance(paths, int) or paths <= 0:
        raise ValueError("paths must be positive integer")
    if isinstance(history_frequency_steps_per_year, bool) or not isinstance(history_frequency_steps_per_year, int) or history_frequency_steps_per_year <= 0:
        raise ValueError("history_frequency_steps_per_year must be positive integer")
    if isinstance(horizon_years, bool) or not isinstance(horizon_years, (int, float)) or math.isnan(horizon_years) or math.isinf(horizon_years) or horizon_years <= 0:
        raise ValueError("horizon_years must be positive finite number")

    hist = np.asarray(historical_prices, dtype=float)
    if not np.all(np.isfinite(hist)) or not np.all(hist > 0):
        raise ValueError("historical_prices must be positive finite (no gaps allowed)")
    
    if hist.size < 30:
        raise ValueError("at least 30 historical prices are required")
        
    lr = np.diff(np.log(hist))
    sigma_history_step = float(np.std(lr, ddof=1))
    if not np.isfinite(sigma_history_step) or sigma_history_step <= 0:
        raise ValueError("historical volatility is invalid")
        
    sigma_annual = sigma_history_step * math.sqrt(history_frequency_steps_per_year)
    steps_per_year = horizon_steps / horizon_years
    sigma_horizon_step = sigma_annual / math.sqrt(steps_per_year)

    drift = np.log(target_median / current_price) / horizon_steps
    rng = np.random.default_rng(seed)
    shocks = rng.normal(loc=drift, scale=sigma_horizon_step, size=(paths, horizon_steps))
    terminal = current_price * np.exp(shocks.sum(axis=1))
    qs = {q: float(np.quantile(terminal, q)) for q in (0.1, 0.25, 0.5, 0.75, 0.9)}
    
    representative_cagr = (target_median / current_price) ** (1 / horizon_years) - 1
    median_cagr = (qs[0.5] / current_price) ** (1 / horizon_years) - 1
    
    expected_terminal = np.mean(terminal)
    expected_cumulative_return = (expected_terminal - current_price) / current_price
    
    # Corrected: mean of per-sample CAGR
    per_sample_cagr = (terminal / current_price) ** (1 / horizon_years) - 1
    expected_cagr = np.mean(per_sample_cagr)
    
    return MonteCarloResult(
        paths, horizon_steps, qs, float(np.mean(terminal < current_price)),
        float(representative_cagr), float(median_cagr), 
        float(expected_cumulative_return), float(expected_cagr),
        "Price-only (excluding dividends/tax/FX/costs). Assumes lognormal stationary independent increments (iid) scaled from historical variance, conditioned on business scenario median."
    )
