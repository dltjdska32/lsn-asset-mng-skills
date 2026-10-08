from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HorizonPlan:
    years: float
    frequency: str
    steps: int
    rationale: str


def plan_long_horizon(years: float) -> HorizonPlan:
    if years <= 0:
        raise ValueError("years must be positive")
    # Daily multi-year autoregressive forecasts compound noise and exceed several model horizons.
    # Monthly keeps a five-year request at 60 steps and is supported by the selected foundation models.
    if years >= 2:
        return HorizonPlan(years, "ME", max(1, round(years * 12)), "multi-year forecasts use month-end observations")
    if years >= 0.5:
        return HorizonPlan(years, "W-FRI", max(1, round(years * 52)), "medium horizons use weekly observations")
    return HorizonPlan(years, "B", max(1, round(years * 252)), "short horizons may use business-day observations")
