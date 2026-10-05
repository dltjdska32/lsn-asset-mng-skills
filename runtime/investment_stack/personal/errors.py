"""Phase 3 ledger domain errors; raw SQLite errors do not cross this boundary."""


class LedgerError(RuntimeError):
    """Base class for personal ledger failures."""


class IntentValidationError(LedgerError):
    pass


class ConfirmationRequired(IntentValidationError):
    pass


class DuplicateTransactionError(LedgerError):
    pass


class PostingError(LedgerError):
    pass


class ProjectionError(LedgerError):
    pass


class ReversalError(LedgerError):
    pass


class UnsupportedTransactionError(IntentValidationError):
    pass
