"""Domain errors and validation exceptions for investment stack contracts."""

from __future__ import annotations


class ContractError(Exception):
    """Base exception for all contract-related errors."""


class ContractValidationError(ContractError):
    """Raised when data fails contract validation rules."""


class KindValidationError(ContractValidationError):
    """Raised when an unrecognized or disallowed contract envelope kind is encountered."""


class DecimalValidationError(ContractValidationError):
    """Raised when a Decimal value is non-finite, NaN, Infinity, or unparseable."""


class TimezoneValidationError(ContractValidationError):
    """Raised when a timestamp lacks timezone or timezone is invalid."""


class PointInTimeError(ContractValidationError):
    """Raised when data is not point-in-time available at cutoff."""


class SlotCoherenceError(ContractValidationError):
    """Raised when a slot specification has inconsistent or contradictory constraints."""


class RevisionConflictError(ContractError):
    """Raised on compare-and-swap (CAS) failure during snapshot persistence."""


class PayloadSizeExceededError(ContractError):
    """Raised when a serialized payload exceeds the maximum allowed budget."""


class TamperDetectionError(ContractError):
    """Raised when content hash verification fails or data tampering is detected."""


class HistoryPreservationError(ContractError):
    """Raised when an attempt is made to overwrite or erase contract history."""


class EvidenceNotFoundError(ContractError):
    """Raised when a snapshot or calculation references evidence not found in the run."""


class InputIntegrityError(ContractError):
    """Raised when bound inputs do not match snapshot or calculation constraints."""


class CorruptedStorageError(ContractError):
    """Raised when persisted contract storage in database is corrupted or malformed."""


class UnapprovedPolicyError(ContractValidationError):
    """Raised when an unapproved policy is attempted to be used in calculation."""


class AmbiguousSnapshotError(ContractError):
    """Raised when multiple active snapshots match a query without specific instrument or request key."""
