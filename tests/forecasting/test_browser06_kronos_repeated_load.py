"""SYNTHETIC repeat-import acceptance checks; no remote model weights or network.

Use the real pinned Git source verifier. Only the weight snapshot verification
and the model implementation are stubbed; reviewer probes are never changed.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import types

import pytest

import investment_stack.forecasting.adapters.kronos as kronos_adapter
from investment_stack.forecasting.integrity import verify_kronos_source


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *args], text=True, stderr=subprocess.STDOUT
    ).strip()


@pytest.fixture
def pinned_stub(tmp_path, monkeypatch):
    if shutil.which("git") is None:
        pytest.skip("local Git executable is required for isolated synthetic pin fixture")

    # Isolate the generic upstream `model` package name from the rest of pytest.
    # monkeypatch restores pre-existing module entries when this test ends.
    for name in tuple(sys.modules):
        if name == "model" or name.startswith("model."):
            monkeypatch.delitem(sys.modules, name)

    root = tmp_path / "synthetic-kronos-source"
    (root / "model").mkdir(parents=True)
    (root / "model" / "__init__.py").write_text(
        "from .kronos import Kronos, KronosTokenizer, KronosPredictor\n",
        encoding="utf-8",
    )
    (root / "model" / "kronos.py").write_text(
        """from pathlib import Path
import time

class Kronos:
    @classmethod
    def from_pretrained(cls, path):
        time.sleep(0.005)
        if Path(path).name == 'fail_weight':
            raise RuntimeError('synthetic model initialization failure')
        return cls()
    def eval(self):
        return self

class KronosTokenizer:
    @classmethod
    def from_pretrained(cls, path):
        return cls()
    def eval(self):
        return self

class KronosPredictor:
    def __init__(self, model, tokenizer, *, device, max_context):
        self.model, self.tokenizer = model, tokenizer
        self.device, self.max_context = device, max_context
""",
        encoding="utf-8",
    )
    (root / ".gitignore").write_text(
        "__pycache__/\n*.pyc\nmodel/kronos/\nweights/\ncache/\n",
        encoding="utf-8",
    )
    _git(root, "init", "-q")
    _git(root, "add", ".gitignore", "model/__init__.py", "model/kronos.py")
    _git(root, "-c", "user.name=synthetic", "-c", "user.email=test@example.invalid",
         "commit", "-qm", "synthetic pinned source")
    pin = _git(root, "rev-parse", "HEAD")
    monkeypatch.setattr(kronos_adapter, "KRONOS_COMMIT", pin)

    # Snapshots are intentionally not real weights: only the source verification
    # is exercised here, so no external downloads or model import dependencies.
    snapshot_calls = []
    def verified_stub_snapshot(path, model_id):
        snapshot_calls.append((Path(path), model_id))
    monkeypatch.setattr(kronos_adapter, "verify_snapshot_manifest", verified_stub_snapshot)

    model_ref = tmp_path / "mock_weights"
    tokenizer_ref = tmp_path / "mock_tokenizer"
    model_ref.mkdir()
    tokenizer_ref.mkdir()
    def adapter(ref=model_ref):
        return kronos_adapter.KronosAdapter(
            model_ref=str(ref), tokenizer_ref=str(tokenizer_ref),
            source_root=str(root)
        )

    yield root, pin, adapter, snapshot_calls

    # Discard our synthetic cached modules; restore any pre-existing entries.
    for name in tuple(sys.modules):
        if name == "model" or name.startswith("model."):
            sys.modules.pop(name, None)


@pytest.mark.parametrize("previous_flag", [False, True])
def test_first_second_and_cold_third_import_create_no_bytecode(pinned_stub, monkeypatch, previous_flag):
    root, pin, adapter, snapshot_calls = pinned_stub
    monkeypatch.setattr(sys, "dont_write_bytecode", previous_flag)
    old_path = sys.path[:]
    assert verify_kronos_source(root, pin) == root.resolve()

    first = adapter()._load()
    assert first.model is not None and first.tokenizer is not None
    assert sys.dont_write_bytecode is previous_flag
    assert sys.path == old_path
    assert not list(root.rglob("*.pyc"))
    assert not list(root.rglob("__pycache__"))

    second = adapter()._load()
    assert second is not first
    assert sys.dont_write_bytecode is previous_flag
    assert sys.path == old_path
    assert verify_kronos_source(root, pin) == root.resolve()

    # A genuinely cold import, not merely another new adapter with a cached module.
    for name in tuple(sys.modules):
        if name == "model" or name.startswith("model."):
            del sys.modules[name]
    third = adapter()._load()
    assert third is not second
    assert sys.dont_write_bytecode is previous_flag
    assert sys.path == old_path
    assert not list(root.rglob("__pycache__"))
    assert not list(root.rglob("*.pyc"))
    assert verify_kronos_source(root, pin) == root.resolve()
    assert len(snapshot_calls) == 6


def test_init_exception_restores_path_and_flag_and_retry_works(pinned_stub, monkeypatch):
    root, pin, adapter, _ = pinned_stub
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    # Existing path entry must be retained, not removed by our finally handler.
    monkeypatch.syspath_prepend(str(root))
    old_path = sys.path[:]
    with pytest.raises(RuntimeError, match="synthetic model initialization failure"):
        adapter(root / "fail_weight")._load()
    assert sys.path == old_path
    assert sys.dont_write_bytecode is False
    assert not list(root.rglob("__pycache__"))
    assert verify_kronos_source(root, pin) == root.resolve()
    assert adapter()._load().model is not None
    assert sys.path == old_path
    assert sys.dont_write_bytecode is False


def test_source_import_exception_restores_interpreter_state(pinned_stub, monkeypatch):
    root, _, adapter, _ = pinned_stub
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    tracked = root / "model" / "kronos.py"
    original = tracked.read_text(encoding="utf-8")
    tracked.write_text("raise RuntimeError('synthetic import failure')\n" + original,
                       encoding="utf-8")
    _git(root, "add", "model/kronos.py")
    _git(root, "-c", "user.name=synthetic", "-c", "user.email=test@example.invalid",
         "commit", "-qm", "pinned synthetic import failure")
    monkeypatch.setattr(kronos_adapter, "KRONOS_COMMIT", _git(root, "rev-parse", "HEAD"))
    old_path = sys.path[:]

    with pytest.raises(RuntimeError, match="synthetic import failure"):
        adapter()._load()
    assert sys.path == old_path
    assert sys.dont_write_bytecode is False
    assert not list(root.rglob("__pycache__"))

    tracked.write_text(original, encoding="utf-8")
    _git(root, "add", "model/kronos.py")
    _git(root, "-c", "user.name=synthetic", "-c", "user.email=test@example.invalid",
         "commit", "-qm", "restore synthetic pinned source")
    monkeypatch.setattr(kronos_adapter, "KRONOS_COMMIT", _git(root, "rev-parse", "HEAD"))
    assert adapter()._load().model is not None
    assert sys.path == old_path
    assert sys.dont_write_bytecode is False
    assert not list(root.rglob("__pycache__"))


@pytest.mark.parametrize("hostile", ["ignored_package", "ignored_pyc", "ignored_py"])
def test_ignored_executable_import_shadow_still_rejected(pinned_stub, monkeypatch, hostile):
    root, pin, adapter, _ = pinned_stub
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    assert adapter()._load().model is not None
    # A non-executable ignored cache remains acceptable by documented policy.
    (root / "cache").mkdir()
    (root / "cache" / "weights.bin").write_bytes(b"synthetic non-code data")
    assert verify_kronos_source(root, pin) == root.resolve()

    if hostile == "ignored_package":
        (root / "model" / "kronos").mkdir()
        bad = root / "model" / "kronos" / "__init__.py"
    elif hostile == "ignored_pyc":
        (root / "model" / "__pycache__").mkdir()
        bad = root / "model" / "__pycache__" / "__init__.cpython-312.pyc"
    else:
        (root / "model" / "kronos").mkdir()
        bad = root / "model" / "kronos" / "shadow.py"
    bad.write_bytes(b"malicious ignored synthetic code")
    assert not _git(root, "status", "--porcelain")
    with pytest.raises(RuntimeError, match="ignored executable/import-shadowing"):
        adapter()._load()
    assert sys.dont_write_bytecode is False


def test_foreign_cached_model_module_remains_forbidden(pinned_stub, monkeypatch):
    root, _, adapter, _ = pinned_stub
    old_path = sys.path[:]
    old_flag = sys.dont_write_bytecode
    foreign = types.ModuleType("model")
    foreign.__file__ = str(root.parent / "foreign" / "__init__.py")
    monkeypatch.setitem(sys.modules, "model", foreign)
    with pytest.raises(RuntimeError, match="foreign preloaded Kronos module"):
        adapter()._load()
    assert sys.path == old_path
    assert sys.dont_write_bytecode is old_flag
    assert not list(root.rglob("__pycache__"))


def test_simultaneous_fresh_adapters_do_not_clobber_interpreter_state(pinned_stub, monkeypatch):
    root, pin, adapter, _ = pinned_stub
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    old_path = sys.path[:]
    barrier = threading.Barrier(2)
    def load():
        barrier.wait(timeout=5)
        return adapter()._load()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(lambda _: load(), range(2)))
    assert first is not second
    assert sys.path == old_path
    assert sys.dont_write_bytecode is False
    assert not list(root.rglob("__pycache__"))
    assert verify_kronos_source(root, pin) == root.resolve()
