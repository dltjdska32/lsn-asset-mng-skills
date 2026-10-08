"""Forecast runs, ensembles, and component linkages."""

from investment_stack.storage.migrations import Migration

MIGRATION = Migration(
    version=4,
    migration_id="run-0004-forecasts",
    statements=(
        """
        CREATE TABLE forecast_model_runs (
            forecast_run_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES run_metadata(run_id),
            instrument_id TEXT NOT NULL,
            model_id TEXT NOT NULL,
            status TEXT NOT NULL,
            as_of TEXT,
            target_date TEXT,
            price_basis TEXT,
            point_forecast REAL,
            quantiles_json TEXT,
            horizon_steps INTEGER,
            frequency TEXT,
            error TEXT,
            details_json TEXT,
            created_at TEXT NOT NULL,
            target_semantics TEXT,
            validation_level TEXT,
            point_semantics TEXT,
            provenance TEXT,
            currency TEXT
        )
        """,
        """
        CREATE INDEX idx_forecast_model_runs_run_instrument
        ON forecast_model_runs(run_id, instrument_id)
        """,
        """
        CREATE TABLE forecast_ensembles (
            ensemble_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES run_metadata(run_id),
            instrument_id TEXT NOT NULL,
            status TEXT NOT NULL,
            as_of TEXT,
            target_date TEXT,
            price_basis TEXT,
            point_forecast REAL,
            quantiles_json TEXT,
            weights_json TEXT,
            details_json TEXT,
            assessment_json TEXT,
            created_at TEXT NOT NULL,
            target_semantics TEXT,
            validation_level TEXT,
            point_semantics TEXT,
            provenance TEXT,
            currency TEXT
        )
        """,
        """
        CREATE INDEX idx_forecast_ensembles_run_instrument
        ON forecast_ensembles(run_id, instrument_id)
        """,
        """
        CREATE TABLE forecast_ensemble_components (
            ensemble_id TEXT NOT NULL REFERENCES forecast_ensembles(ensemble_id),
            forecast_run_id TEXT NOT NULL REFERENCES forecast_model_runs(forecast_run_id),
            PRIMARY KEY (ensemble_id, forecast_run_id)
        )
        """,
    ),
)
