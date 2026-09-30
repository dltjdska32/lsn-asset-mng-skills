"""Persisted provider bodies and explicit source excerpts for re-verification."""

from investment_stack.storage.migrations import Migration


MIGRATION = Migration(
    version=3,
    migration_id="run-0003-source-documents",
    statements=(
        """
        CREATE TABLE source_documents (
            document_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES run_metadata(run_id),
            evidence_id TEXT NOT NULL REFERENCES evidence(evidence_id),
            parser_id TEXT NOT NULL,
            content_sha256 TEXT NOT NULL,
            payload_text TEXT NOT NULL,
            UNIQUE(run_id, evidence_id)
        )
        """,
        """
        CREATE TRIGGER source_documents_append_only_update
        BEFORE UPDATE ON source_documents BEGIN
            SELECT RAISE(ABORT, 'source documents are append-only');
        END
        """,
        """
        CREATE TRIGGER source_documents_append_only_delete
        BEFORE DELETE ON source_documents BEGIN
            SELECT RAISE(ABORT, 'source documents are append-only');
        END
        """,
    ),
)
