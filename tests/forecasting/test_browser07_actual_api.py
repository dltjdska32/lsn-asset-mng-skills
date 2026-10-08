"""Synthetic Chronos 2.3.2 API and pinned Kronos import side-effect contracts.

No remote downloads, real model weights, reviewer probes, or personal DB.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta, timezone
from pathlib import Path
import shutil
import subprocess
import sys
import threading

import numpy as np
import pandas as pd
import pytest

from investment_stack.forecasting.adapters.chronos2 import Chronos2Adapter
import investment_stack.forecasting.adapters.kronos as kronos_module
from investment_stack.forecasting.contracts import ForecastRequest
from investment_stack.forecasting.integrity import verify_kronos_source


def aware_non_utc_request() -> ForecastRequest:
    tz = timezone(timedelta(hours=9))
    stamps = pd.date_range("2020-01-01", periods=40, freq="D", tz=tz)
    return ForecastRequest(
        instrument_id="X", currency="USD", as_of=stamps[-1], current_price=100.,
        target_date=stamps[-1] + pd.offsets.Day(5), horizon_steps=5, frequency="D",
        history=(100.,) * 40, timestamps=tuple(stamps.to_pydatetime()),
        metadata={"price_basis": "split-adjusted"},
    )


class RealShapeChronosStub:
    def __init__(self, alteration=None):
        self.called = False
        self.alteration = alteration

    def predict_df(self, context_df, *, future_df, prediction_length,
                   quantile_levels, id_column, timestamp_column, target):
        self.called = True
        assert target == "target" and id_column == "id" and timestamp_column == "timestamp"
        assert prediction_length == 5 and quantile_levels == [0.1, 0.25, 0.5, 0.75, 0.9]
        assert context_df["timestamp"].dtype.kind == "M"
        assert future_df["timestamp"].dtype.kind == "M"
        # Exercise the real Chronos 2.3.2 normalize_df numeric timestamp cast.
        assert context_df["timestamp"].to_numpy().view("int64").shape == (40,)
        assert future_df["timestamp"].to_numpy().view("int64").shape == (5,)
        assert context_df["timestamp"].tolist() == list(
            pd.DatetimeIndex(pd.to_datetime(aware_non_utc_request().timestamps, utc=True)).tz_localize(None)
        )
        assert future_df["timestamp"].iloc[0] == pd.Timestamp("2020-02-09 15:00:00")
        frame = pd.DataFrame({
            "id": ["X"] * 5, "timestamp": future_df["timestamp"],
            "target_name": ["target"] * 5,
            "predictions": [110.] * 5,
            "0.1": [90.] * 5, "0.25": [100.] * 5, "0.5": [110.] * 5,
            "0.75": [120.] * 5, "0.9": [130.] * 5,
        })
        if self.alteration:
            self.alteration(frame)
        return frame


def test_official_chronos_target_name_and_utc_naive_boundary():
    req = aware_non_utc_request()
    req.validate()  # The provider conversion must NOT loosen aware request validation.
    p = RealShapeChronosStub()
    result = Chronos2Adapter(pipeline=p).forecast(req)
    assert p.called and result.status == "COMPLETE", result.error
    assert result.point == 110. and result.quantiles[.1] == 90.
    assert result.as_of == req.as_of and result.target_date == req.target_date


@pytest.mark.parametrize("bad", [
    "wrong_target", "mixed_target", "null_target", "unbound_extra", "nonnumeric",
    "nonfinite", "negative_middle", "crossing_middle", "wrong_id",
    "wrong_timestamp", "short", "missing_point",
])
def test_chronos_actual_shape_rejects_unbound_or_invalid_data(bad):
    def alter(frame):
        if bad == "wrong_target": frame["target_name"] = "close"
        elif bad == "mixed_target": frame.loc[1, "target_name"] = "close"
        elif bad == "null_target": frame.loc[0, "target_name"] = None
        elif bad == "unbound_extra": frame["other_source"] = ["untrusted"] * 5
        elif bad == "nonnumeric":
            frame["0.25"] = frame["0.25"].astype(object)
            frame.loc[1, "0.25"] = "N/A"
        elif bad == "nonfinite": frame.loc[1, "predictions"] = np.nan
        elif bad == "negative_middle": frame.loc[1, "0.1"] = -1
        elif bad == "crossing_middle": frame.loc[1, "0.1"] = 200
        elif bad == "wrong_id": frame.loc[2, "id"] = "Y"
        elif bad == "wrong_timestamp": frame.loc[0, "timestamp"] += pd.Timedelta(hours=1)
        elif bad == "short": frame.drop(index=4, inplace=True)
        elif bad == "missing_point": frame.drop(columns=["predictions", "0.5"], inplace=True)
    p = RealShapeChronosStub(alter)
    result = Chronos2Adapter(pipeline=p).forecast(aware_non_utc_request())
    assert p.called and result.status == "ERROR" and result.point is None, (bad, result)


def test_older_chronos_stub_without_target_name_is_compatible():
    def remove_name(frame): frame.drop(columns=["target_name"], inplace=True)
    p = RealShapeChronosStub(remove_name)
    result = Chronos2Adapter(pipeline=p).forecast(aware_non_utc_request())
    assert p.called and result.status == "COMPLETE" and result.point == 110., result.error


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *args], text=True, stderr=subprocess.STDOUT
    ).strip()


@pytest.fixture
def pinned_upstream_path_mutation(tmp_path, monkeypatch):
    if shutil.which("git") is None:
        pytest.skip("Synthetic pinned source verifier requires Git")
    for name in tuple(sys.modules):
        if name == "model" or name.startswith("model."):
            monkeypatch.delitem(sys.modules, name)
    root = tmp_path / "synthetic-source"
    (root / "model").mkdir(parents=True)
    (root / "model" / "__init__.py").write_text(
        "from .kronos import Kronos, KronosTokenizer, KronosPredictor\n", encoding="utf-8"
    )
    # Import-side mutation mirrors the official pinned model/kronos.py:9.
    (root / "model" / "kronos.py").write_text(
        """import os
import sys
import time
sys.path.append('../')
sys.path.append(sys.path[0])
if os.environ.get('FB07_REBIND'):
    sys.path = list(sys.path) + ['unexpected_rebind']
if os.environ.get('FB07_IMPORT_FAIL'):
    raise RuntimeError('synthetic import error')
class Kronos:
    @classmethod
    def from_pretrained(cls, path):
        time.sleep(0.005)
        if os.path.basename(path) == 'bad-model':
            raise RuntimeError('synthetic constructor error')
        return cls()
    def eval(self): return self
class KronosTokenizer:
    @classmethod
    def from_pretrained(cls, path): return cls()
    def eval(self): return self
class KronosPredictor:
    def __init__(self, model, tokenizer, *, device, max_context):
        self.model = model
        self.tokenizer = tokenizer
""", encoding="utf-8"
    )
    (root / ".gitignore").write_text("__pycache__/\n*.pyc\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", ".gitignore", "model/__init__.py", "model/kronos.py")
    _git(root, "-c", "user.name=synthetic", "-c", "user.email=test@example.invalid",
         "commit", "-qm", "synthetic pinned path mutation")
    pin = _git(root, "rev-parse", "HEAD")
    monkeypatch.setattr(kronos_module, "KRONOS_COMMIT", pin)
    monkeypatch.setattr(kronos_module, "verify_snapshot_manifest", lambda *_: None)
    for key in ("FB07_REBIND", "FB07_IMPORT_FAIL"):
        monkeypatch.delenv(key, raising=False)
    def adapter(model="ok-model"):
        return kronos_module.KronosAdapter(
            source_root=str(root), model_ref=str(tmp_path / model),
            tokenizer_ref=str(tmp_path / "tokenizer")
        )
    yield root, pin, adapter
    for name in tuple(sys.modules):
        if name == "model" or name.startswith("model."):
            sys.modules.pop(name, None)


def _assert_restored(previous_ref, previous_items, previous_flag):
    assert sys.path is previous_ref
    assert sys.path == previous_items
    assert sys.dont_write_bytecode is previous_flag


def test_kronos_official_import_mutation_restores_full_path_and_identity(pinned_upstream_path_mutation, monkeypatch):
    root, pin, adapter = pinned_upstream_path_mutation
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    entry_path_items = sys.path[:]
    sys.path.insert(2, sys.path[2])  # intentional preexisting duplicate
    prior_ref, prior_items, prior_flag = sys.path, sys.path[:], sys.dont_write_bytecode
    try:
        assert verify_kronos_source(root, pin) == root.resolve()
        assert adapter()._load().model is not None
        _assert_restored(prior_ref, prior_items, prior_flag)
        assert '../' not in sys.path[len(prior_items):]
        assert not list(root.rglob("__pycache__"))
        # Fresh adapter, then genuinely cold import after cached modules removed.
        assert adapter()._load().model is not None
        for name in tuple(sys.modules):
            if name == "model" or name.startswith("model."):
                del sys.modules[name]
        assert adapter()._load().model is not None
        _assert_restored(prior_ref, prior_items, prior_flag)
        assert verify_kronos_source(root, pin) == root.resolve()
    finally:
        sys.path[:] = entry_path_items  # undo only the test's duplicate


@pytest.mark.parametrize("scenario", ["import_error", "constructor_error", "upstream_rebind"])
def test_kronos_import_exception_and_rebinding_restore_full_path(pinned_upstream_path_mutation, monkeypatch, scenario):
    root, pin, adapter = pinned_upstream_path_mutation
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    prior_ref, prior_items, prior_flag = sys.path, sys.path[:], sys.dont_write_bytecode
    if scenario == "import_error": monkeypatch.setenv("FB07_IMPORT_FAIL", "1")
    if scenario == "upstream_rebind": monkeypatch.setenv("FB07_REBIND", "1")
    if scenario in ("import_error", "constructor_error"):
        with pytest.raises(RuntimeError, match="synthetic (import|constructor) error"):
            adapter("bad-model" if scenario == "constructor_error" else "ok-model")._load()
    else:
        assert adapter()._load().model is not None
    _assert_restored(prior_ref, prior_items, prior_flag)
    assert not list(root.rglob("__pycache__"))
    assert verify_kronos_source(root, pin) == root.resolve()


def test_kronos_concurrent_loads_preserve_original_sys_path(pinned_upstream_path_mutation, monkeypatch):
    root, pin, adapter = pinned_upstream_path_mutation
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    prior_ref, prior_items, prior_flag = sys.path, sys.path[:], sys.dont_write_bytecode
    barrier = threading.Barrier(2)
    def load():
        barrier.wait(timeout=5)
        return adapter()._load()
    with ThreadPoolExecutor(max_workers=2) as pool:
        loaded = list(pool.map(lambda _: load(), range(2)))
    assert loaded[0] is not loaded[1]
    _assert_restored(prior_ref, prior_items, prior_flag)
    assert not list(root.rglob("__pycache__"))
    assert verify_kronos_source(root, pin) == root.resolve()
