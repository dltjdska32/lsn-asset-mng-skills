"""Storage-only indexes used by validation and recovery checks."""

from investment_stack.storage.migrations import Migration


MIGRATION = Migration(
    version=2,
    migration_id="personal-0002-storage-indexes",
    statements=(
        "CREATE INDEX idx_transaction_entries_transaction_id ON transaction_entries(transaction_id)",
        "CREATE INDEX idx_transactions_state_version ON transactions(state_version)",
        "CREATE INDEX idx_positions_state_version ON positions(state_version)",
        "CREATE INDEX idx_import_records_status ON import_records(status)",
    ),
)
