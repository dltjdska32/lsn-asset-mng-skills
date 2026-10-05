"""Initial personal storage schema; no ledger business behavior lives here."""

from investment_stack.storage.migrations import Migration


MIGRATION = Migration(
    version=1,
    migration_id="personal-0001-initial",
    statements=(
        """
        CREATE TABLE accounts (
            account_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            account_type TEXT NOT NULL,
            currency TEXT,
            status TEXT NOT NULL DEFAULT 'ACTIVE',
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE instruments (
            instrument_id TEXT PRIMARY KEY,
            canonical_name TEXT NOT NULL,
            asset_class TEXT,
            currency TEXT,
            identifiers_json TEXT,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE instrument_aliases (
            alias_id TEXT PRIMARY KEY,
            instrument_id TEXT NOT NULL REFERENCES instruments(instrument_id),
            alias TEXT NOT NULL,
            provider TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(alias, provider)
        )
        """,
        """
        CREATE TABLE state_versions (
            state_version INTEGER PRIMARY KEY CHECK (state_version >= 0),
            created_at TEXT NOT NULL,
            reason TEXT NOT NULL,
            metadata_json TEXT
        )
        """,
        """
        INSERT INTO state_versions (state_version, created_at, reason, metadata_json)
        VALUES (0, '1970-01-01T00:00:00+00:00', 'storage-bootstrap', NULL)
        """,
        """
        CREATE TABLE liabilities (
            liability_id TEXT PRIMARY KEY,
            account_id TEXT REFERENCES accounts(account_id),
            name TEXT NOT NULL,
            currency TEXT NOT NULL,
            principal NUMERIC,
            state_version INTEGER NOT NULL REFERENCES state_versions(state_version),
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE transactions (
            transaction_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            occurred_at TEXT,
            occurred_timezone TEXT,
            posted_at TEXT,
            transaction_type TEXT,
            account_id TEXT REFERENCES accounts(account_id),
            instrument_id TEXT REFERENCES instruments(instrument_id),
            quantity NUMERIC,
            amount NUMERIC,
            currency TEXT,
            price NUMERIC,
            fee NUMERIC,
            fx_rate NUMERIC,
            related_liability_id TEXT REFERENCES liabilities(liability_id),
            source TEXT,
            note TEXT,
            reversal_of TEXT REFERENCES transactions(transaction_id),
            idempotency_key TEXT UNIQUE,
            state_version INTEGER NOT NULL REFERENCES state_versions(state_version),
            created_at TEXT NOT NULL,
            correction_id TEXT,
            correction_of TEXT REFERENCES transactions(transaction_id),
            correction_reason TEXT
        )
        """,
        """
        CREATE TABLE correction_relations (
            correction_id TEXT PRIMARY KEY,
            original_transaction_id TEXT NOT NULL REFERENCES transactions(transaction_id),
            reversal_transaction_id TEXT REFERENCES transactions(transaction_id),
            replacement_transaction_id TEXT REFERENCES transactions(transaction_id),
            correction_reason TEXT NOT NULL,
            state_version INTEGER NOT NULL REFERENCES state_versions(state_version),
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE transaction_entries (
            entry_id TEXT PRIMARY KEY,
            transaction_id TEXT NOT NULL REFERENCES transactions(transaction_id),
            account_id TEXT REFERENCES accounts(account_id),
            instrument_id TEXT REFERENCES instruments(instrument_id),
            liability_id TEXT REFERENCES liabilities(liability_id),
            entry_type TEXT,
            quantity_delta NUMERIC,
            amount_delta NUMERIC,
            currency TEXT,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE positions (
            position_id TEXT PRIMARY KEY,
            account_id TEXT NOT NULL REFERENCES accounts(account_id),
            instrument_id TEXT NOT NULL REFERENCES instruments(instrument_id),
            quantity NUMERIC NOT NULL,
            cost_basis_status TEXT,
            state_version INTEGER NOT NULL REFERENCES state_versions(state_version),
            updated_at TEXT NOT NULL,
            UNIQUE(account_id, instrument_id)
        )
        """,
        """
        CREATE TABLE position_history (
            position_history_id TEXT PRIMARY KEY,
            position_id TEXT NOT NULL REFERENCES positions(position_id),
            state_version INTEGER NOT NULL REFERENCES state_versions(state_version),
            quantity NUMERIC NOT NULL,
            recorded_at TEXT NOT NULL,
            UNIQUE(position_id, state_version)
        )
        """,
        """
        CREATE TABLE cash_balances (
            cash_balance_id TEXT PRIMARY KEY,
            account_id TEXT NOT NULL REFERENCES accounts(account_id),
            currency TEXT NOT NULL,
            balance NUMERIC NOT NULL,
            state_version INTEGER NOT NULL REFERENCES state_versions(state_version),
            updated_at TEXT NOT NULL,
            UNIQUE(account_id, currency)
        )
        """,
        """
        CREATE TABLE cashflow (
            cashflow_id TEXT PRIMARY KEY,
            account_id TEXT REFERENCES accounts(account_id),
            transaction_id TEXT REFERENCES transactions(transaction_id),
            category TEXT,
            amount NUMERIC,
            currency TEXT,
            occurred_at TEXT,
            state_version INTEGER NOT NULL REFERENCES state_versions(state_version),
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE goals (
            goal_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            target_amount NUMERIC,
            currency TEXT,
            target_date TEXT,
            state_version INTEGER NOT NULL REFERENCES state_versions(state_version),
            metadata_json TEXT,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE portfolio_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            state_version INTEGER NOT NULL REFERENCES state_versions(state_version),
            snapshot_type TEXT NOT NULL,
            as_of TEXT NOT NULL,
            data_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE import_records (
            import_id TEXT PRIMARY KEY,
            source_type TEXT NOT NULL,
            source_fingerprint TEXT NOT NULL,
            status TEXT NOT NULL,
            state_version INTEGER REFERENCES state_versions(state_version),
            metadata_json TEXT,
            imported_at TEXT NOT NULL,
            UNIQUE(source_type, source_fingerprint)
        )
        """,
        """
        CREATE TABLE storage_metadata (
            metadata_key TEXT PRIMARY KEY,
            metadata_value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        INSERT INTO storage_metadata (metadata_key, metadata_value, updated_at)
        VALUES (
            'personal_db_instance_id',
            lower(hex(randomblob(16))),
            '1970-01-01T00:00:00+00:00'
        )
        """,
    ),
)
