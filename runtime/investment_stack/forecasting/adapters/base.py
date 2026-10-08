from __future__ import annotations

from abc import ABC, abstractmethod
from ..contracts import ForecastRequest, ModelForecast


class ForecastAdapter(ABC):
    model_id: str

    @abstractmethod
    def available(self) -> tuple[bool, str | None]:
        raise NotImplementedError

    @abstractmethod
    def forecast(self, request: ForecastRequest) -> ModelForecast:
        raise NotImplementedError
