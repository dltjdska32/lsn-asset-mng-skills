"""Initial isolated run evidence schema."""

from investment_stack.storage.migrations import Migration


MIGRATION = Migration(
    version=1,
    migration_id="run-0001-initial",
    statements=(
        """
        CREATE TABLE run_metadata (
            run_id TEXT PRIMARY KEY,
            request_mode TEXT,
            analysis_as_of TEXT,
            analysis_timezone TEXT,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            run_status TEXT NOT NULL,
            metadata_json TEXT
        )
        """,
        """
        CREATE TABLE pinned_personal_state (
            pinned_state_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES run_metadata(run_id),
            state_version INTEGER NOT NULL,
            pinned_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE instrument_resolutions (
            resolution_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES run_metadata(run_id),
            requested_identifier TEXT NOT NULL,
            resolved_identifier TEXT,
            resolution_status TEXT NOT NULL,
            metadata_json TEXT
        )
        """,
        """
        CREATE TABLE provider_states (
            provider_state_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES run_metadata(run_id),
            provider_name TEXT NOT NULL,
            provider_status TEXT NOT NULL,
            metadata_json TEXT,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE task_states (
            task_state_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES run_metadata(run_id),
            task_name TEXT NOT NULL,
            task_status TEXT NOT NULL,
            metadata_json TEXT,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE evidence (
            evidence_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES run_metadata(run_id),
            evidence_type TEXT NOT NULL,
            source_uri TEXT,
            retrieved_at TEXT,
            content_hash TEXT,
            metadata_json TEXT
        )
        """,
        """
        CREATE TABLE market_observations (
            observation_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES run_metadata(run_id),
            evidence_id TEXT REFERENCES evidence(evidence_id),
            instrument_id TEXT,
            observed_at TEXT,
            value_numeric NUMERIC,
            unit TEXT,
            metadata_json TEXT
        )
        """,
        """
        CREATE TABLE observation_selections (
            selection_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES run_metadata(run_id),
            observation_id TEXT NOT NULL REFERENCES market_observations(observation_id),
            selection_reason TEXT,
            selected_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE financial_observations (
            observation_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES run_metadata(run_id),
            evidence_id TEXT REFERENCES evidence(evidence_id),
            metric_name TEXT NOT NULL,
            period_end TEXT,
            value_numeric NUMERIC,
            unit TEXT,
            metadata_json TEXT
        )
        """,
        """
        CREATE TABLE macro_observations (
            observation_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES run_metadata(run_id),
            evidence_id TEXT REFERENCES evidence(evidence_id),
            series_name TEXT NOT NULL,
            observed_at TEXT,
            value_numeric NUMERIC,
            unit TEXT,
            metadata_json TEXT
        )
        """,
        """
        CREATE TABLE calculations (
            calculation_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES run_metadata(run_id),
            calculation_name TEXT NOT NULL,
            formula TEXT NOT NULL,
            inputs_json TEXT NOT NULL,
            result_json TEXT,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE conflicts (
            conflict_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES run_metadata(run_id),
            conflict_type TEXT NOT NULL,
            status TEXT NOT NULL,
            details_json TEXT,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE freshness_assessments (
            freshness_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES run_metadata(run_id),
            evidence_id TEXT REFERENCES evidence(evidence_id),
            status TEXT NOT NULL,
            assessed_at TEXT NOT NULL,
            details_json TEXT
        )
        """,
        """
        CREATE TABLE materiality_decisions (
            decision_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES run_metadata(run_id),
            subject TEXT NOT NULL,
            decision TEXT NOT NULL,
            rationale TEXT,
            decided_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE review_findings (
            finding_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES run_metadata(run_id),
            severity TEXT NOT NULL,
            status TEXT NOT NULL,
            finding_text TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE report_sections (
            section_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES run_metadata(run_id),
            section_name TEXT NOT NULL,
            section_status TEXT NOT NULL,
            content_reference TEXT,
            metadata_json TEXT,
            updated_at TEXT NOT NULL
        )
        """,
        "CREATE INDEX idx_provider_states_run_id ON provider_states(run_id)",
        "CREATE INDEX idx_task_states_run_id ON task_states(run_id)",
        "CREATE INDEX idx_evidence_run_id ON evidence(run_id)",
    ),
)
