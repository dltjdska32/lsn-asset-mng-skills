from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from .contracts import EnsembleForecast, ModelForecast
from ..storage.identity import get_path_identity
from ..evidence.manager import validate_run_database


def _strict_dumps(obj):
    if obj is None:
        return None
    def _check(o):
        import math
        if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
            raise ValueError("NaN/Inf not allowed")
        if isinstance(o, dict):
            for k, v in o.items():
                _check(v)
        if isinstance(o, (list, tuple)):
            for v in o:
                _check(v)
        if not isinstance(o, (dict, list, tuple, str, int, float, bool, type(None))):
            raise ValueError("unsupported JSON value")
    _check(obj)
    return json.dumps(obj, sort_keys=True, allow_nan=False)


def _assert_active_component_binding(ensemble: EnsembleForecast,
                                     models: Sequence[ModelForecast]) -> None:
    """Bind *every* active ensemble component to the exact persisted payload.

    A model_id/context match alone is insufficient: a caller could persist a
    different point, quantiles, status or provenance under the same identity.
    Inactive/error models may still be stored as separate audit records.
    """
    active = {mid for mid, weight in ensemble.component_weights.items() if weight > 0}
    components = [m for m in ensemble.components if m.model_id in active]
    supplied = [m for m in models if m.model_id in active]
    if (len(components) != len(active) or len(supplied) != len(active) or
            {m.model_id for m in components} != active or
            {m.model_id for m in supplied} != active):
        raise ValueError("active ensemble components must have exactly one matching persisted model")
    by_id = {m.model_id: m for m in supplied}
    for component in components:
        # Ensure the complete model record (incl. quantiles, status, observed_at,
        # error, point semantics, validation level, details/provenance) matches.
        component.validate()
        _strict_dumps(component.quantiles)
        _strict_dumps(component.details)
        try:
            identical = component == by_id[component.model_id]
            if identical is not True:
                raise ValueError("active component payload differs from persisted model")
        except (TypeError, ValueError) as exc:
            raise ValueError("active component payload differs from persisted model") from exc
        if component.observed_at is not None:
            raise ValueError("active component observed_at cannot be serialized by the current run schema")


class ForecastStore:
    def __init__(self, run_db_path: str | Path):
        self.path = Path(run_db_path)
        if not self.path.exists():
            raise FileNotFoundError(f"Run database file not found: {self.path}")
        self._validate_identity()

    def _validate_identity(self):
        try:
            pid = get_path_identity(self.path, require_target=False)
            paths_to_check = [str(pid.lexical_path), str(pid.resolved_path)]
        except Exception:
            paths_to_check = [str(self.path)]
            
        for p in paths_to_check:
            name = Path(p).name.lower()
            if "personal" in name or "personal.db" in name:
                raise ValueError(f"Personal DB cannot be used for forecast runs: {self.path}")

    def _check_run_context(self, con: sqlite3.Connection, run_id: str, instrument_id: str, as_of: str | None):
        con.execute("PRAGMA foreign_keys=ON")
        # Verify the official run migration history and complete catalog schema
        # before mutating any rows, not just a six-table name approximation.
        report = validate_run_database(self.path, expected_run_id=run_id)
        if not report.valid:
            raise ValueError("not a canonical migrated run database: " + "; ".join(report.errors))
        # Retain the additional instrument/as-of checks for the requested forecast.
        required = {"run_metadata", "instrument_resolutions", "forecast_model_runs", "forecast_ensembles", "forecast_ensemble_components", "schema_migrations"}
        present = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not required.issubset(present):
            raise ValueError("not a canonical migrated run database")
        has_accounts = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='accounts'").fetchone()
        if has_accounts:
            raise ValueError(f"Database contains personal schema ('accounts' table): {self.path}")
            
        has_run_meta = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='run_metadata'").fetchone()
        if not has_run_meta:
            raise ValueError(f"Database missing run_metadata table; not a valid run DB: {self.path}")
            
        row = con.execute("SELECT analysis_as_of FROM run_metadata WHERE run_id = ?", (run_id,)).fetchone()
        if not row:
            raise ValueError(f"run_id {run_id} not found in run_metadata")
            
        run_as_of = row[0]
        if as_of and run_as_of and datetime.fromisoformat(run_as_of).astimezone(timezone.utc) != datetime.fromisoformat(as_of).astimezone(timezone.utc):
            raise ValueError(f"as_of mismatch: request {as_of} vs run {run_as_of}")

        inst_row2 = con.execute("SELECT 1 FROM instrument_resolutions WHERE run_id = ? AND (requested_identifier = ? OR resolved_identifier = ?)", (run_id, instrument_id, instrument_id)).fetchone()
        if not inst_row2:
            raise ValueError(f"Instrument {instrument_id} not resolved for run {run_id}")

    def migrate(self) -> None:
        raise RuntimeError("run migration must use RunDatabaseManager; NO dummy-run migrate")

    def save_model(self, run_id: str, instrument_id: str, f: ModelForecast) -> str:
        f.validate()
        if instrument_id != f.instrument_id:
            raise ValueError("caller instrument does not match forecast instrument")
        
        fid = f"forecast:{uuid.uuid4().hex}"
        now = datetime.now(timezone.utc).isoformat()
        
        as_of_iso = f.as_of.isoformat() if f.as_of else None
        
        con = sqlite3.connect(self.path)
        try:
            self._check_run_context(con, run_id, instrument_id, as_of_iso)
            
            val_level = getattr(f, "validation_level", f.details.get("validation_level", "EXPERIMENTAL"))
            pt_sem = getattr(f, "point_semantics", "point")
            prov = getattr(f, "provenance", f.details.get("provenance", "UNKNOWN"))
            
            with con:
                con.execute(
                    """INSERT INTO forecast_model_runs (
                        forecast_run_id, run_id, instrument_id, model_id, status, as_of, target_date, 
                        price_basis, point_forecast, quantiles_json, horizon_steps, frequency, error, 
                        details_json, created_at, target_semantics, validation_level, point_semantics, 
                        provenance, currency
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (fid, run_id, instrument_id, f.model_id, f.status, 
                     as_of_iso, 
                     f.target_date.isoformat() if f.target_date else None, 
                     f.price_basis,
                     f.point,
                     _strict_dumps(f.quantiles) if f.quantiles is not None else None, 
                     f.horizon_steps, f.frequency,
                     f.error, 
                     _strict_dumps(f.details) if f.details is not None else None, 
                     now,
                     f.target_semantics, 
                     val_level,
                     pt_sem,
                     prov,
                     f.currency),
                )
        finally:
            con.close()
        return fid

    def save_ensemble(self, run_id: str, f: EnsembleForecast, assessment: dict | None = None, component_model_run_ids: Sequence[str] | None = None) -> str:
        f.validate()
        active = {mid for mid, weight in f.component_weights.items() if weight > 0}
        if active and component_model_run_ids is None:
            raise ValueError("active ensemble components require explicit persisted model links")
        if component_model_run_ids is None:
            component_model_run_ids = ()
        
        eid = f"ensemble:{uuid.uuid4().hex}"
        now = datetime.now(timezone.utc).isoformat()
        
        as_of_iso = f.as_of.isoformat() if f.as_of else None
        
        con = sqlite3.connect(self.path)
        try:
            self._check_run_context(con, run_id, f.instrument_id, as_of_iso)
            _strict_dumps(assessment)
            
            val_level = getattr(f, "validation_level", f.details.get("validation_level", "EXPERIMENTAL"))
            pt_sem = getattr(f, "point_semantics", "point")
            prov = getattr(f, "provenance", f.details.get("provenance", "UNKNOWN"))
            
            with con:
                con.execute(
                    """INSERT INTO forecast_ensembles (
                        ensemble_id, run_id, instrument_id, status, as_of, target_date, price_basis, 
                        point_forecast, quantiles_json, weights_json, details_json, assessment_json, 
                        created_at, target_semantics, validation_level, point_semantics, provenance, currency
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (eid, run_id, f.instrument_id, f.status, 
                     as_of_iso,
                     f.target_date.isoformat() if f.target_date else None,
                     f.price_basis,
                     f.point,
                     _strict_dumps(f.quantiles) if f.quantiles is not None else None,
                     _strict_dumps(f.component_weights) if f.component_weights is not None else None,
                     _strict_dumps(f.details) if f.details is not None else None, 
                     _strict_dumps(assessment) if assessment else None,
                     now,
                     f.target_semantics,
                     val_level,
                     pt_sem,
                     prov,
                     f.currency),
                )
                
                if component_model_run_ids is not None:
                    if len(component_model_run_ids) != len(set(component_model_run_ids)):
                        raise ValueError("duplicate component links")
                    matched = []
                    components = {c.model_id: c for c in f.components
                                  if f.component_weights.get(c.model_id, 0) > 0}
                    if len(components) != len([c for c in f.components
                                               if f.component_weights.get(c.model_id, 0) > 0]):
                        raise ValueError("duplicate active ensemble component identity")
                    for cid in component_model_run_ids:
                        row = con.execute("""SELECT run_id,instrument_id,as_of,target_date,price_basis,
                          horizon_steps,frequency,target_semantics,currency,model_id FROM forecast_model_runs
                          WHERE forecast_run_id=?""", (cid,)).fetchone()
                        if row is None or row[:2] != (run_id,f.instrument_id) or row[2] is None or (
                            datetime.fromisoformat(row[2]) != f.as_of or
                            datetime.fromisoformat(row[3]) != f.target_date or
                            row[4:9] != (f.price_basis,f.horizon_steps,f.frequency,f.target_semantics,f.currency)):
                            raise ValueError("ensemble component context mismatch")
                        matched.append(row[9])
                        component = components.get(row[9])
                        if component is None:
                            raise ValueError("ensemble links include a non-active model")
                        if component.observed_at is not None:
                            raise ValueError("active component observed_at cannot be serialized by the current run schema")
                        saved = con.execute("""SELECT status,point_forecast,quantiles_json,error,
                              details_json,validation_level,point_semantics,provenance
                              FROM forecast_model_runs WHERE forecast_run_id=?""", (cid,)).fetchone()
                        # ModelForecast has no `provenance` attribute: it is
                        # serialized from details, so compare both fields.
                        expected = (component.status, component.point,
                                    _strict_dumps(component.quantiles), component.error,
                                    _strict_dumps(component.details),component.validation_level,
                                    component.point_semantics,
                                    component.details.get("provenance", "UNKNOWN"))
                        if saved != expected:
                            raise ValueError("ensemble linked model payload differs from active component")
                    weighted = {mid for mid, weight in f.component_weights.items() if weight > 0}
                    if set(matched) != weighted or len(matched) != len(weighted):
                        raise ValueError("ensemble links must match active component weights")
                    con.executemany(
                        "INSERT INTO forecast_ensemble_components (ensemble_id, forecast_run_id) VALUES (?, ?)",
                        [(eid, cid) for cid in component_model_run_ids]
                    )
        finally:
            con.close()
        return eid

    def save_bundle(self, run_id: str, instrument_id: str, models: Sequence[ModelForecast],
                    ensemble: EnsembleForecast, assessment: dict | None = None) -> tuple[list[str], str]:
        """Persist models, ensemble and same-run component links in one transaction."""
        models = tuple(models)
        ensemble.validate()
        if ensemble.instrument_id != instrument_id:
            raise ValueError("ensemble instrument mismatch")
        # Reject invalid JSON and model bindings before opening a write transaction.
        for obj in (ensemble.details, ensemble.quantiles, ensemble.component_weights, assessment):
            _strict_dumps(obj)
        for model in models:
            model.validate()
            if (model.instrument_id != instrument_id or model.as_of != ensemble.as_of
                or model.target_date != ensemble.target_date or model.currency != ensemble.currency
                or model.price_basis != ensemble.price_basis or model.horizon_steps != ensemble.horizon_steps
                or model.frequency != ensemble.frequency or model.target_semantics != ensemble.target_semantics):
                raise ValueError("component binding mismatch")
            _strict_dumps(model.details)
            _strict_dumps(model.quantiles)
        model_ids = [m.model_id for m in models]
        if len(set(model_ids)) != len(model_ids):
            raise ValueError("duplicate component model IDs")
        weighted = {mid for mid, weight in ensemble.component_weights.items() if weight > 0}
        if not weighted.issubset(set(model_ids)):
            raise ValueError("positive component weight without a saved model")
        _assert_active_component_binding(ensemble, models)
        con = sqlite3.connect(self.path)
        ids = []
        eid = "ensemble:" + uuid.uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        try:
            con.execute("PRAGMA foreign_keys=ON")
            self._check_run_context(con, run_id, instrument_id, ensemble.as_of.isoformat())
            with con:
                for f in models:
                    mid = "forecast:" + uuid.uuid4().hex
                    con.execute("""INSERT INTO forecast_model_runs
                        (forecast_run_id,run_id,instrument_id,model_id,status,as_of,target_date,price_basis,
                         point_forecast,quantiles_json,horizon_steps,frequency,error,details_json,created_at,
                         target_semantics,validation_level,point_semantics,provenance,currency)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (mid,run_id,instrument_id,f.model_id,f.status,f.as_of.isoformat(),f.target_date.isoformat(),
                         f.price_basis,f.point,_strict_dumps(f.quantiles),f.horizon_steps,f.frequency,f.error,
                         _strict_dumps(f.details),now,f.target_semantics,f.validation_level,f.point_semantics,
                         f.details.get("provenance","UNKNOWN"),f.currency))
                    ids.append(mid)
                con.execute("""INSERT INTO forecast_ensembles
                    (ensemble_id,run_id,instrument_id,status,as_of,target_date,price_basis,point_forecast,
                     quantiles_json,weights_json,details_json,assessment_json,created_at,target_semantics,
                     validation_level,point_semantics,provenance,currency)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (eid,run_id,instrument_id,ensemble.status,ensemble.as_of.isoformat(),ensemble.target_date.isoformat(),
                     ensemble.price_basis,ensemble.point,_strict_dumps(ensemble.quantiles),
                     _strict_dumps(ensemble.component_weights),_strict_dumps(ensemble.details),
                     _strict_dumps(assessment),now,ensemble.target_semantics,ensemble.validation_level,
                     ensemble.point_semantics,ensemble.details.get("provenance","UNKNOWN"),ensemble.currency))
                for mid, model in zip(ids, models):
                    if model.model_id in ensemble.component_weights and ensemble.component_weights[model.model_id] > 0:
                        con.execute("INSERT INTO forecast_ensemble_components(ensemble_id,forecast_run_id) VALUES (?,?)",(eid,mid))
        finally:
            con.close()
        return ids, eid
