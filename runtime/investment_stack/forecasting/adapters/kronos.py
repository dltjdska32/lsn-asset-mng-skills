from __future__ import annotations

import importlib.util
import sys
import threading
from pathlib import Path

import pandas as pd
import numpy as np

from .base import ForecastAdapter
from ..contracts import ForecastRequest, ModelForecast
from ..integrity import verify_snapshot_manifest, verify_kronos_source

KRONOS_COMMIT = "67b630e67f6a18c9e9be918d9b4337c960db1e9a"

# Import flags and sys.path are process globals. A per-process lock keeps
# simultaneous *Kronos* loads from observing/restoring another load's state.
# Ignored bytecode is executable and is intentionally rejected by the pinned
# source verifier, so a verified import must never generate bytecode there.
_KRONOS_IMPORT_LOCK = threading.RLock()

class KronosAdapter(ForecastAdapter):
    model_id = "NeoQuasar/Kronos-mini"
    tokenizer_id = "NeoQuasar/Kronos-Tokenizer-2k"

    def __init__(self, predictor=None, max_context: int = 120, sample_count: int = 1, device: str = "cpu",
                 model_ref: str | None = None, tokenizer_ref: str | None = None, source_root: str | None = None):
        self._predictor = predictor
        self.model_ref = model_ref or self.model_id
        self.tokenizer_ref = tokenizer_ref or self.tokenizer_id
        self.max_context = max_context
        self.sample_count = sample_count
        self.device = device
        self.source_root = source_root

    def available(self) -> tuple[bool, str | None]:
        if self._predictor is not None:
            return True, None
        for ref, label in ((self.model_ref, "model"), (self.tokenizer_ref, "tokenizer")):
            if ref:
                p = Path(ref).expanduser()
                if not p.is_absolute() and not ref.startswith(('./', '../')):
                    return False, f"ref must be an absolute or explicit local path, got: {ref}"
                if '..' in p.parts: return False, "path traversal not allowed"
                if not p.exists(): return False, f"local Kronos {label} path not found: {ref}"
                man = p / "snapshot_manifest.json"
                if not man.exists(): return False, f"missing snapshot_manifest.json in {ref}"
        
        # If source root is given, it's available if it exists
        if self.source_root:
            p = Path(self.source_root).expanduser()
            if not p.exists():
                return False, f"source_root not found: {self.source_root}"
        elif importlib.util.find_spec("model") is None:
            return False, "Kronos official repository/package is not installed on PYTHONPATH and source_root not given"
        return True, None

    def _load(self):
        with _KRONOS_IMPORT_LOCK:
            if self._predictor is not None:
                return self._predictor

            for ref, expected_id in ((self.model_ref, self.model_id), (self.tokenizer_ref, self.tokenizer_id)):
                if ref:
                    verify_snapshot_manifest(Path(ref).expanduser(), expected_id)

            if not self.source_root:
                raise RuntimeError("explicit pinned source_root required before importing Kronos")
            sr = Path(self.source_root).expanduser().resolve()
            verify_kronos_source(sr, KRONOS_COMMIT)
            for module_name, module in tuple(sys.modules.items()):
                if module_name == "model" or module_name.startswith("model."):
                    location = getattr(module, "__file__", None)
                    if location is None or not Path(location).resolve().is_relative_to(sr):
                        raise RuntimeError(f"foreign cached Kronos module: {module_name}")

            # No .pyc may enter the verified source tree: such ignored code is
            # forbidden on the very next source verification. Scope the flag
            # to the controlled import and restore it, even if loading fails.
            previous_bytecode_flag = sys.dont_write_bytecode
            import_path = str(sr)
            sys.path.insert(0, import_path)
            sys.dont_write_bytecode = True
            try:
                from model import Kronos, KronosPredictor, KronosTokenizer
                tokenizer = KronosTokenizer.from_pretrained(str(Path(self.tokenizer_ref).expanduser()))
                model = Kronos.from_pretrained(str(Path(self.model_ref).expanduser()))
                model.eval(); tokenizer.eval()
                self._predictor = KronosPredictor(model, tokenizer, device=self.device, max_context=self.max_context)
            finally:
                sys.dont_write_bytecode = previous_bytecode_flag
                # Remove our own prepend, not another caller's existing entry.
                if sys.path and sys.path[0] == import_path:
                    sys.path.pop(0)
                else:
                    sys.path.remove(import_path)
            return self._predictor

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
        try:
            if request.ohlcv is None:
                raise ValueError("OHLCV frame required")
            df = request.ohlcv.copy()
            cols = {c.lower(): c for c in df.columns}
            needed = ["open", "high", "low", "close"]
            if any(c not in cols for c in needed):
                raise ValueError("OHLC columns are required")
            
            work = pd.DataFrame({c: pd.to_numeric(df[cols[c]], errors="coerce") for c in needed})
            for opt in ("volume", "amount"):
                if opt in cols:
                    work[opt] = pd.to_numeric(df[cols[opt]], errors="coerce")
                else:
                    raise ValueError(f"Missing required OHLCV column: {opt}. Honest unavailability required.")
            
            if work.isna().any().any():
                raise ValueError("NaN values found in OHLCV. Cannot drop invalid interior rows and preserve cadence.")
            
            # Bind observed OHLCV timestamps to the request before any predictor call.
            if not isinstance(df.index, pd.DatetimeIndex) or df.index.tz is None:
                raise ValueError("OHLCV requires an aware DatetimeIndex (RangeIndex is unbound)")
            observed = pd.DatetimeIndex(df.index).tz_convert("UTC")
            expected = pd.DatetimeIndex(pd.to_datetime(request.timestamps, utc=True))
            if (len(observed) != len(expected) or not observed.is_monotonic_increasing
                    or observed.has_duplicates or not observed.equals(expected)):
                raise ValueError("OHLCV observation timestamps mismatch request history")
            if len(work) != len(request.history) or not np.allclose(
                    work["close"].to_numpy(dtype=float), np.asarray(request.history, dtype=float), rtol=1e-9, atol=1e-9):
                raise ValueError("OHLCV close history mismatch request")
            if observed[-1] > pd.Timestamp(request.as_of).tz_convert("UTC"):
                raise ValueError("OHLCV observations later than as_of")
            work = work.tail(self.max_context)
            if len(work) < 32:
                raise ValueError("insufficient OHLCV history (minimum 32)")
            
            x_ts = observed[-len(work):]
            offset = pd.tseries.frequencies.to_offset(request.frequency)
            y_ts = pd.Series([pd.Timestamp(x_ts[-1]) + offset * (i + 1) for i in range(request.horizon_steps)])
            
            pred = self._load().predict(
                df=work, x_timestamp=pd.Series(x_ts), y_timestamp=y_ts,
                pred_len=request.horizon_steps, T=1.0, top_p=0.9,
                sample_count=self.sample_count, verbose=False,
            )
            if not isinstance(pred, pd.DataFrame) or len(pred) != request.horizon_steps:
                raise ValueError("Kronos prediction path length mismatch")
            if not isinstance(pred.index, pd.DatetimeIndex) or pred.index.tz is None:
                raise ValueError("Kronos full prediction DatetimeIndex required")
            if list(pd.to_datetime(pred.index, utc=True)) != list(pd.to_datetime(y_ts, utc=True)):
                raise ValueError("Kronos prediction timestamps mismatch")
            if "close" not in pred or not np.isfinite(pred.to_numpy(dtype=float)).all() or (pred["close"] <= 0).any():
                raise ValueError("Kronos invalid predicted prices")
            point = float(pred.iloc[-1]["close"])
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
                quantiles={},
                details={"tokenizer_id": self.tokenizer_id, "sample_count": self.sample_count,
                         "model_ref": self.model_ref, "tokenizer_ref": self.tokenizer_ref}
            )
            out.validate(); return out
        except Exception as exc:
            missing_source_amount = isinstance(exc, ValueError) and "Missing required OHLCV column: amount" in str(exc)
            return ModelForecast(
                model_id=self.model_id, status="UNAVAILABLE" if missing_source_amount else "ERROR", error=f"{type(exc).__name__}: {exc}",
                instrument_id=request.instrument_id, currency=request.currency,
                as_of=request.as_of, target_date=request.target_date,
                price_basis=request.metadata.get("price_basis", "unknown"),
                horizon_steps=request.horizon_steps, frequency=request.frequency,
                target_semantics=request.target_semantics
            )
