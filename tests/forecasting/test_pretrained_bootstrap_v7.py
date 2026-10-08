from pathlib import Path
import importlib.util
import pandas as pd

from investment_stack.forecasting.adapters.chronos2 import Chronos2Adapter
from investment_stack.forecasting.adapters.kronos import KronosAdapter
from investment_stack.forecasting.model_registry import MODEL_SPECS


def _load_script(name):
    path = Path(__file__).resolve().parents[2] / 'scripts' / name
    spec = importlib.util.spec_from_file_location(name.replace('.py',''), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_official_checkpoint_hashes_are_pinned():
    assert MODEL_SPECS['chronos2-small'].checkpoint_sha256 == '492290ae82bb89f9769e3479ce90b3179de1f33e600c34daa0352531538b23cd'
    assert MODEL_SPECS['kronos-mini'].checkpoint_sha256 == 'a7d5f37e2e9fbd9891f7d7d4f72574512dd1f704fee14223e0a8cd0fbf54197c'
    assert MODEL_SPECS['kronos-mini'].tokenizer_sha256 == 'b97ec46b3b72160509e289183eaf7bdf5f0dac5bb9b49522f6d46638a99a8717'


def test_bootstrap_revisions_are_pinned():
    mod = _load_script('bootstrap_pretrained_models.py')
    assert len(mod.HF_SPECS['chronos2-small']['revision']) == 40
    assert len(mod.HF_SPECS['kronos-mini']['revision']) == 40
    assert len(mod.HF_SPECS['kronos-tokenizer-2k']['revision']) == 40
    assert len(mod.KRONOS_COMMIT) == 40


def test_missing_local_paths_fail_closed():
    ok, reason = Chronos2Adapter(model_ref='C:/definitely/missing/chronos').available()
    assert not ok and ('not found' in reason or 'explicit local path' in reason)
    ok, reason = KronosAdapter(model_ref='C:/definitely/missing/kronos', tokenizer_ref='C:/definitely/missing/tok').available()
    assert not ok


def test_kronos_device_is_stored():
    a = KronosAdapter(predictor=object(), device='cpu')
    assert a.device == 'cpu'


def test_monthly_resample_preserves_ohlc_logic():
    mod = _load_script('run_pretrained_forecast.py')
    idx = pd.to_datetime(['2026-01-02','2026-01-30','2026-02-02','2026-02-27']).tz_localize('UTC')
    df = pd.DataFrame({
        'open':[10,11,20,21], 'high':[12,13,22,23], 'low':[9,10,19,20],
        'close':[11,12,21,22], 'adjusted_close':[11,12,21,22], 'volume':[100,200,300,400]
    }, index=idx)
    out = mod.to_monthly(df, as_of=pd.Timestamp('2026-03-01', tz='UTC'))
    assert list(out['open']) == [10,20]
    assert list(out['high']) == [13,23]
    assert list(out['low']) == [9,19]
    assert list(out['close']) == [12,22]
    assert list(out['volume']) == [300,700]
