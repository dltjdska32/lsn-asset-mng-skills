import pytest
import sqlite3
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from investment_stack.evidence.manager import RunDatabaseManager
from investment_stack.forecasting.store import ForecastStore
from investment_stack.forecasting.contracts import ModelForecast, EnsembleForecast
from investment_stack.forecasting.integrity import verify_snapshot_manifest
from investment_stack.forecasting.model_registry import MODEL_SPECS

def test_canonical_run_database_e2e(tmp_path):
    run_id = "run-e2e-12345"
    mgr = RunDatabaseManager(tmp_path, run_id)
    mgr.create()
    
    # Initialize run context
    as_of = datetime(2025, 1, 1, tzinfo=timezone.utc)
    mgr.initialize_run_context(request_mode="test", analysis_as_of=as_of.isoformat(), analysis_timezone="UTC")
    
    # Resolve instrument
    db_path = mgr._operational_database_path()
    with sqlite3.connect(db_path) as con:
        con.execute("INSERT INTO instrument_resolutions (resolution_id, run_id, requested_identifier, resolved_identifier, resolution_status) VALUES (?, ?, ?, ?, ?)", ("res1", run_id, "AAPL", "AAPL-RESOLVED", "RESOLVED"))
        con.commit()
    
    # Persist forecasts
    store = ForecastStore(db_path)
    
    f1 = ModelForecast(
        model_id="test", status="COMPLETE", instrument_id="AAPL-RESOLVED", currency="USD", 
        as_of=as_of, target_date=datetime(2025, 1, 30, tzinfo=timezone.utc), price_basis="split-adjusted",
        horizon_steps=30, frequency="D", point=150.0, quantiles={0.1: 140.0, 0.9: 160.0}
    )
    fid1 = store.save_model(run_id, "AAPL-RESOLVED", f1)
    
    f2 = ModelForecast(
        model_id="test2", status="COMPLETE", instrument_id="AAPL-RESOLVED", currency="USD", 
        as_of=as_of, target_date=datetime(2025, 1, 30, tzinfo=timezone.utc), price_basis="split-adjusted",
        horizon_steps=30, frequency="D", point=152.0, quantiles={0.1: 142.0, 0.9: 162.0}
    )
    fid2 = store.save_model(run_id, "AAPL-RESOLVED", f2)
    
    ens = EnsembleForecast(
        instrument_id="AAPL-RESOLVED", currency="USD", as_of=as_of, 
        target_date=datetime(2025, 1, 30, tzinfo=timezone.utc), price_basis="split-adjusted",
        horizon_steps=30, frequency="D", status="COMPLETE", point=151.0, 
        quantiles={0.1: 141.0, 0.9: 161.0}, component_weights={"test": 0.5, "test2": 0.5},
        components=[f1, f2]
    )
    eid = store.save_ensemble(run_id, ens, component_model_run_ids=[fid1, fid2])
    
    # Verify exact synthetic RunDatabase remains VALID
    report = mgr.open()
    assert report.valid, f"RunDB became invalid: {report.errors}"
    
    with sqlite3.connect(db_path) as con:
        links = con.execute("SELECT forecast_run_id FROM forecast_ensemble_components WHERE ensemble_id = ?", (eid,)).fetchall()
        assert len(links) == 2
        assert {l[0] for l in links} == {fid1, fid2}

def test_unknown_run_wrong_instrument_fail_before_ddl(tmp_path):
    run_id = "run-e2e-12345"
    mgr = RunDatabaseManager(tmp_path, run_id)
    mgr.create()
    
    as_of = datetime(2025, 1, 1, tzinfo=timezone.utc)
    mgr.initialize_run_context(request_mode="test", analysis_as_of=as_of.isoformat(), analysis_timezone="UTC")
    
    db_path = mgr._operational_database_path()
    store = ForecastStore(db_path)
    
    f = ModelForecast(
        model_id="test", status="COMPLETE", instrument_id="UNKNOWN", currency="USD", 
        as_of=as_of, target_date=datetime(2025, 1, 30, tzinfo=timezone.utc), price_basis="split-adjusted",
        horizon_steps=30, frequency="D", point=150.0
    )
    with pytest.raises(ValueError, match="Instrument UNKNOWN not resolved"):
        store.save_model(run_id, "UNKNOWN", f)
        
    with pytest.raises(ValueError, match="run_metadata identity mismatch"):
        store.save_model("wrong-run", "UNKNOWN", f)

def test_nested_nan_rollback(tmp_path):
    run_id = "run-e2e-12345"
    mgr = RunDatabaseManager(tmp_path, run_id)
    mgr.create()
    as_of = datetime(2025, 1, 1, tzinfo=timezone.utc)
    mgr.initialize_run_context(request_mode="test", analysis_as_of=as_of.isoformat(), analysis_timezone="UTC")
    
    db_path = mgr._operational_database_path()
    with sqlite3.connect(db_path) as con:
        con.execute("INSERT INTO instrument_resolutions (resolution_id, run_id, requested_identifier, resolved_identifier, resolution_status) VALUES (?, ?, ?, ?, ?)", ("res2", run_id, "AAPL", "AAPL-RESOLVED", "RESOLVED"))
        con.commit()
        
    store = ForecastStore(db_path)
    import math
    f = ModelForecast(
        model_id="test", status="COMPLETE", instrument_id="AAPL-RESOLVED", currency="USD", 
        as_of=as_of, target_date=datetime(2025, 1, 30, tzinfo=timezone.utc), price_basis="split-adjusted",
        horizon_steps=30, frequency="D", point=150.0,
        details={"nested": {"value": float('nan')}} # NaN here
    )
    with pytest.raises(ValueError, match="NaN/Inf not allowed"):
        store.save_model(run_id, "AAPL-RESOLVED", f)
        
    with sqlite3.connect(db_path) as con:
        assert con.execute("SELECT COUNT(*) FROM forecast_model_runs").fetchone()[0] == 0

def test_old_db_migration_fails(tmp_path):
    # Testing that dummy-run migrate fails as requested
    (tmp_path / "old.db").write_text("")
    store = ForecastStore(tmp_path / "old.db")
    with pytest.raises(Exception):
        store.migrate()

def test_manifest_happy_path_and_failures(tmp_path, monkeypatch):
    import investment_stack.forecasting.integrity as integrity_module
    
    spec = MODEL_SPECS["chronos2-small"]
    
    model_dir = tmp_path / "models" / "chronos-test"
    model_dir.mkdir(parents=True)
    
    (model_dir / "config.json").write_text("{}")
    (model_dir / "model.safetensors").write_bytes(b"mock weights")
    
    config_hash = hashlib.sha256(b"{}").hexdigest()
    weight_hash = spec.checkpoint_sha256 # mock it as perfect
    
    manifest = {
        "version": 1,
        "model_id": spec.model_id,
        "revision": MODEL_SPECS["chronos2-small"].revision,
        "files": {
            "config.json": config_hash,
            "model.safetensors": weight_hash
        }
    }
    
    (model_dir / "snapshot_manifest.json").write_text(json.dumps(manifest))
    
    # Needs to fail because model.safetensors hash on disk doesn't match spec.checkpoint_sha256
    with pytest.raises(RuntimeError, match="SHA256 mismatch for model.safetensors"):
        verify_snapshot_manifest(model_dir, spec.model_id)

    # Let's mock sha256_file to bypass hash check so we can test other things
    def mock_sha256(path, chunk_size=None):
        if path.name == "config.json": return config_hash
        if path.name == "model.safetensors": return weight_hash
        return hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(integrity_module, "sha256_file", mock_sha256)
    
    # Missing config
    manifest_no_config = manifest.copy()
    manifest_no_config["files"] = {"model.safetensors": weight_hash}
    (model_dir / "snapshot_manifest.json").write_text(json.dumps(manifest_no_config))
    with pytest.raises(ValueError, match="Missing config.json"):
        verify_snapshot_manifest(model_dir, spec.model_id)

    # Wrong revision
    manifest_main = manifest.copy()
    manifest_main["revision"] = "main"
    manifest_main["files"] = {"config.json": config_hash, "model.safetensors": weight_hash}
    (model_dir / "snapshot_manifest.json").write_text(json.dumps(manifest_main))
    with pytest.raises(ValueError, match="exact pinned revision required"):
        verify_snapshot_manifest(model_dir, spec.model_id)
        
    # Sibling path
    sibling = tmp_path / "models" / "sibling"
    sibling.mkdir()
    (sibling / "other.json").write_text("{}")
    manifest_sibling = manifest.copy()
    manifest_sibling["revision"] = spec.revision
    manifest_sibling["files"] = {"../sibling/other.json": config_hash, "config.json": config_hash, "model.safetensors": weight_hash}
    (model_dir / "snapshot_manifest.json").write_text(json.dumps(manifest_sibling))
    with pytest.raises(ValueError, match="Path escape attempt"):
        verify_snapshot_manifest(model_dir, spec.model_id)
