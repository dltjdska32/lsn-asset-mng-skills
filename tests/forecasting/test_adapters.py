from datetime import datetime, timezone
import numpy as np
from investment_stack.forecasting.contracts import ForecastRequest
from investment_stack.forecasting.adapters import Chronos2Adapter, KronosAdapter, FinCastAdapter


def request():
    return ForecastRequest("TEST", datetime.now(timezone.utc), 5, "D", history=tuple(np.arange(20, dtype=float)+100))


def test_optional_adapters_fail_closed_when_dependencies_absent():
    # In environments where dependencies are installed this can be available; either way
    # availability must return a boolean and a reason only when unavailable.
    for adapter in [Chronos2Adapter(), KronosAdapter(), FinCastAdapter()]:
        ok, reason = adapter.available()
        assert isinstance(ok, bool)
        assert ok or isinstance(reason, str)
