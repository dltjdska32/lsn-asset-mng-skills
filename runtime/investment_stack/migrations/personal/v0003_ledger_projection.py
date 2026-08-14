"""Phase 3 ledger metadata, exact decimal storage, and append-only guards."""

from investment_stack.storage.migrations import Migration


MIGRATION = Migration(
    version=3,
    migration_id="personal-0003-ledger-projection",
    statements=(
        "ALTER TABLE accounts ADD COLUMN timezone TEXT",
        "ALTER TABLE transactions ADD COLUMN intent_id TEXT",
        "ALTER TABLE transactions ADD COLUMN source_account_id TEXT REFERENCES accounts(account_id)",
        "ALTER TABLE transactions ADD COLUMN destination_account_id TEXT REFERENCES accounts(account_id)",
        "ALTER TABLE transactions ADD COLUMN external_reference TEXT",
        "ALTER TABLE transactions ADD COLUMN replacement_for_transaction_id TEXT REFERENCES transactions(transaction_id)",
        "ALTER TABLE transactions ADD COLUMN fingerprint TEXT",
        "ALTER TABLE transactions ADD COLUMN operation_sequence INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE transactions ADD COLUMN confirmation_state TEXT NOT NULL DEFAULT 'CONFIRMED'",
        "ALTER TABLE transactions ADD COLUMN metadata_json TEXT",
        "ALTER TABLE transactions ADD COLUMN quantity_decimal TEXT",
        "ALTER TABLE transactions ADD COLUMN unit_price_decimal TEXT",
        "ALTER TABLE transactions ADD COLUMN gross_amount_decimal TEXT",
        "ALTER TABLE transactions ADD COLUMN fee_amount_decimal TEXT",
        "ALTER TABLE transactions ADD COLUMN tax_amount_decimal TEXT",
        "ALTER TABLE transactions ADD COLUMN cash_amount_decimal TEXT",
        "ALTER TABLE transactions ADD COLUMN fx_rate_decimal TEXT",
        "ALTER TABLE transaction_entries ADD COLUMN entry_sequence INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE transaction_entries ADD COLUMN unit TEXT",
        "ALTER TABLE transaction_entries ADD COLUMN liability_reference TEXT",
        "ALTER TABLE transaction_entries ADD COLUMN quantity_delta_decimal TEXT",
        "ALTER TABLE transaction_entries ADD COLUMN amount_delta_decimal TEXT",
        "ALTER TABLE transaction_entries ADD COLUMN cost_basis_delta_decimal TEXT",
        "ALTER TABLE transaction_entries ADD COLUMN cost_basis_status TEXT",
        "ALTER TABLE transaction_entries ADD COLUMN state_version INTEGER REFERENCES state_versions(state_version)",
        "ALTER TABLE transaction_entries ADD COLUMN metadata_json TEXT",
        "ALTER TABLE positions ADD COLUMN quantity_decimal TEXT",
        "ALTER TABLE positions ADD COLUMN total_cost_decimal TEXT",
        "ALTER TABLE positions ADD COLUMN average_unit_cost_decimal TEXT",
        "ALTER TABLE positions ADD COLUMN currency_code TEXT",
        "ALTER TABLE positions ADD COLUMN updated_state_version INTEGER REFERENCES state_versions(state_version)",
        "ALTER TABLE cash_balances ADD COLUMN balance_decimal TEXT",
        "ALTER TABLE liabilities ADD COLUMN principal_decimal TEXT",
        "ALTER TABLE cashflow ADD COLUMN amount_decimal TEXT",
        "ALTER TABLE portfolio_snapshots ADD COLUMN valuation_status TEXT",
        "ALTER TABLE portfolio_snapshots ADD COLUMN market_data_as_of TEXT",
        "ALTER TABLE portfolio_snapshots ADD COLUMN fx_data_as_of TEXT",
        "ALTER TABLE portfolio_snapshots ADD COLUMN total_assets_decimal TEXT",
        "ALTER TABLE portfolio_snapshots ADD COLUMN total_liabilities_decimal TEXT",
        "ALTER TABLE portfolio_snapshots ADD COLUMN net_worth_decimal TEXT",
        "CREATE INDEX idx_transactions_fingerprint ON transactions(fingerprint)",
        "CREATE INDEX idx_transactions_state_type ON transactions(state_version, transaction_type)",
        "CREATE INDEX idx_transaction_entries_state ON transaction_entries(state_version, entry_sequence)",
        """
        CREATE TRIGGER transactions_append_only_update
        BEFORE UPDATE ON transactions BEGIN
            SELECT RAISE(ABORT, 'posted transactions are append-only');
        END
        """,
        """
        CREATE TRIGGER transactions_append_only_delete
        BEFORE DELETE ON transactions BEGIN
            SELECT RAISE(ABORT, 'posted transactions are append-only');
        END
        """,
        """
        CREATE TRIGGER transaction_entries_append_only_update
        BEFORE UPDATE ON transaction_entries BEGIN
            SELECT RAISE(ABORT, 'transaction entries are append-only');
        END
        """,
        """
        CREATE TRIGGER transaction_entries_append_only_delete
        BEFORE DELETE ON transaction_entries BEGIN
            SELECT RAISE(ABORT, 'transaction entries are append-only');
        END
        """,
        """
        CREATE TRIGGER portfolio_snapshots_append_only_update
        BEFORE UPDATE ON portfolio_snapshots BEGIN
            SELECT RAISE(ABORT, 'portfolio snapshots are append-only');
        END
        """,
        """
        CREATE TRIGGER portfolio_snapshots_append_only_delete
        BEFORE DELETE ON portfolio_snapshots BEGIN
            SELECT RAISE(ABORT, 'portfolio snapshots are append-only');
        END
        """,
    ),
)
