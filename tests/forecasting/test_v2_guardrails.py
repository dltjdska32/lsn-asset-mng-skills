from datetime import datetime, timezone
import hashlib
from pathlib import Path

from investment_stack.forecasting.contracts import ForecastRequest, FundamentalAnchor, ModelForecast
from investment_stack.forecasting.ensemble import ForecastEnsembler
from investment_stack.forecasting.horizon import plan_long_horizon
from investment_stack.forecasting.model_registry import verify_checkpoint
from investment_stack.forecasting.adapters import FinCastAdapter


def test_five_year_is_monthly_60():
    p = plan_long_horizon(5)
    assert p.frequency == "ME"
    assert p.steps == 60


def test_extreme_model_is_excluded():
    anchor = FundamentalAnchor("COMPLETE", "X", "USD", datetime(2026, 12, 31, tzinfo=timezone.utc), "split-adjusted", bear=80, base=100, bull=150, value_kind="terminal_price", evidence_refs=("test-doc",), assumption_refs=("test-assumption",), as_of=datetime(2026, 1, 1, tzinfo=timezone.utc))
    fs = [
        ModelForecast("autogluon/chronos-2-small", "COMPLETE", "X", "USD", datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 12, 31, tzinfo=timezone.utc), "split-adjusted", 12, "ME", point=140),
        ModelForecast("NeoQuasar/Kronos-mini", "COMPLETE", "X", "USD", datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 12, 31, tzinfo=timezone.utc), "split-adjusted", 12, "ME", point=1000),
    ]
    out = ForecastEnsembler().combine(ForecastRequest("X", "USD", datetime(2026, 1, 1, tzinfo=timezone.utc), 100.0, datetime(2026, 12, 31, tzinfo=timezone.utc), 12, "ME", metadata={"price_basis":"split-adjusted"}), fs, anchor)
    assert "NeoQuasar/Kronos-mini" in out.details["excluded"]
    assert "NeoQuasar/Kronos-mini" not in out.component_weights


def test_log_price_blend():
    anchor = FundamentalAnchor("COMPLETE", "X", "USD", datetime(2026, 12, 31, tzinfo=timezone.utc), "split-adjusted", base=100, value_kind="terminal_price", evidence_refs=("test-doc",), assumption_refs=("test-assumption",), as_of=datetime(2026, 1, 1, tzinfo=timezone.utc))
    fs = [ModelForecast("autogluon/chronos-2-small", "COMPLETE", "X", "USD", datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 12, 31, tzinfo=timezone.utc), "split-adjusted", 12, "ME", point=300)]
    out = ForecastEnsembler().combine(ForecastRequest("X", "USD", datetime(2026, 1, 1, tzinfo=timezone.utc), 100.0, datetime(2026, 12, 31, tzinfo=timezone.utc), 12, "ME", metadata={"price_basis":"split-adjusted"}), fs, anchor)
    # weighted geometric mean with normalized weights 0.75 anchor / 0.25 chronos
    assert 131 < out.point < 133


def test_checkpoint_hash_verifier(tmp_path: Path):
    p = tmp_path / "x.bin"
    p.write_bytes(b"abc")
    assert verify_checkpoint(p, hashlib.sha256(b"abc").hexdigest())
    assert not verify_checkpoint(p, "0" * 64)


def test_fincast_pickle_is_disabled_by_default():
    ok, reason = FinCastAdapter(model_path="/tmp/nope.pth").available()
    assert not ok
    assert "pickle" in reason.lower()
