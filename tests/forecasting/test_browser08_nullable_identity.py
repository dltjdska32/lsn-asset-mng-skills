"""Synthetic Chronos 2.3.x nullable-StringDtype identity binding regressions.

No weights or network. Older provider stubs without target_name remain supported,
but if either identity column is present, every returned row must be non-null and
must match the bound request/target, including pandas nullable-string columns.
"""
from __future__ import annotations

import pandas as pd
import pytest

from investment_stack.forecasting.adapters.chronos2 import Chronos2Adapter
from investment_stack.forecasting.contracts import ForecastRequest


def bound_request() -> ForecastRequest:
    dates = pd.date_range("2020-01-01", periods=40, freq="D", tz="Asia/Seoul")
    return ForecastRequest(
        instrument_id="X",
        currency="USD",
        as_of=dates[-1].to_pydatetime(),
        current_price=100.0,
        target_date=(dates[-1] + pd.offsets.Day(5)).to_pydatetime(),
        horizon_steps=5,
        frequency="D",
        history=(100.0,) * len(dates),
        timestamps=tuple(dates.to_pydatetime()),
        metadata={"price_basis": "split-adjusted"},
    )


class NullableIdentityChronosStub:
    def __init__(self, *, column: str, variation: str):
        self.column = column
        self.variation = variation
        self.called = False

    def predict_df(self, context_df, *, future_df, prediction_length,
                   quantile_levels, id_column, timestamp_column, target):
        self.called = True
        assert target == "target" and id_column == "id" and timestamp_column == "timestamp"
        assert prediction_length == 5
        assert context_df["timestamp"].dtype.kind == "M"
        assert future_df["timestamp"].dtype.kind == "M"
        result = pd.DataFrame({
            "id": pd.Series(["X"] * 5, dtype="string"),
            "timestamp": future_df["timestamp"].to_numpy(),
            "target_name": pd.Series(["target"] * 5, dtype="string"),
            "predictions": [110.0] * 5,
            "0.1": [90.0] * 5, "0.25": [100.0] * 5,
            "0.5": [110.0] * 5, "0.75": [120.0] * 5,
            "0.9": [130.0] * 5,
        })
        if self.variation == "one_missing":
            result.loc[0, self.column] = pd.NA
        elif self.variation == "all_missing":
            result[self.column] = pd.Series([pd.NA] * 5, dtype="string")
        elif self.variation == "wrong_value":
            result.loc[1, self.column] = "Y" if self.column == "id" else "close"
        elif self.variation == "omit_target_name":
            result.drop(columns=["target_name"], inplace=True)
        assert result["id"].dtype == pd.StringDtype()
        if "target_name" in result:
            assert result["target_name"].dtype == pd.StringDtype()
        return result


@pytest.mark.parametrize("column", ["id", "target_name"])
@pytest.mark.parametrize("variation", ["valid", "one_missing", "all_missing", "wrong_value"])
def test_nullable_chronos_identity_requires_non_null_exact_match(column, variation):
    req = bound_request()
    req.validate()
    pipeline = NullableIdentityChronosStub(column=column, variation=variation)
    out = Chronos2Adapter(pipeline=pipeline).forecast(req)
    assert pipeline.called
    if variation == "valid":
        assert out.status == "COMPLETE", out.error
        assert out.point == 110.0
        assert out.instrument_id == req.instrument_id
    else:
        assert out.status == "ERROR", (column, variation, out)
        assert out.point is None
        assert "mismatch" in (out.error or ""), out.error


def test_older_chronos_provider_without_target_name_remains_supported():
    pipeline = NullableIdentityChronosStub(column="target_name", variation="omit_target_name")
    out = Chronos2Adapter(pipeline=pipeline).forecast(bound_request())
    assert pipeline.called
    assert out.status == "COMPLETE", out.error
    assert out.point == 110.0
