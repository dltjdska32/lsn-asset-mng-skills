"""Shared storage policy types.

Writable SQLite connections are intentionally not re-exported. Personal data
mutations must use ``PersonalDatabaseManager.guarded_write_transaction``.
"""

from investment_stack.storage.sqlite import ConnectionPolicy, sqlite_readonly_connection

__all__ = ["ConnectionPolicy", "sqlite_readonly_connection"]
