"""Run context, point-in-time public availability, and clock isolation models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from investment_stack.contracts.codec import CONTRACT_VERSION, register_decoder
from investment_stack.contracts.errors import (
    ContractValidationError,
    PointInTimeError,
    TimezoneValidationError,
)


class PublicAvailabilityKind(StrEnum):
    EXACT = "EXACT"
    DATE_INTERVAL = "DATE_INTERVAL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class PublicAvailability:
    """Represents verified public availability timing for point-in-time correctness."""

    kind: PublicAvailabilityKind
    public_available_at: datetime | None = None
    interval_start: datetime | None = None
    interval_end: datetime | None = None
    source_timezone: str | None = None
    source_locator: str | None = None

    def __post_init__(self) -> None:
        if str(self.kind) not in PublicAvailabilityKind.__members__:
            try:
                kind_enum = PublicAvailabilityKind(self.kind)
                object.__setattr__(self, "kind", kind_enum)
            except ValueError as exc:
                raise ContractValidationError(f"Invalid PublicAvailabilityKind: {self.kind!r}") from exc

        for dt, name in (
            (self.public_available_at, "public_available_at"),
            (self.interval_start, "interval_start"),
            (self.interval_end, "interval_end"),
        ):
            if dt is not None and dt.tzinfo is None:
                raise TimezoneValidationError(f"{name} must be timezone-aware, got naive: {dt}")

        if self.kind == PublicAvailabilityKind.EXACT:
            if self.public_available_at is None:
                raise PointInTimeError("EXACT public availability requires public_available_at")
            if not self.source_locator or not self.source_locator.strip():
                raise PointInTimeError("EXACT public availability requires non-empty source_locator")
            if self.interval_start is not None or self.interval_end is not None:
                raise PointInTimeError("EXACT public availability cannot specify interval dates")

        elif self.kind == PublicAvailabilityKind.DATE_INTERVAL:
            if self.interval_start is None or self.interval_end is None:
                raise PointInTimeError(
                    "DATE_INTERVAL public availability requires both interval_start and interval_end"
                )
            if self.interval_start > self.interval_end:
                raise PointInTimeError(
                    f"interval_start ({self.interval_start}) cannot be after interval_end ({self.interval_end})"
                )
            if not self.source_timezone or not self.source_timezone.strip():
                raise PointInTimeError("DATE_INTERVAL public availability requires verified source_timezone")
            try:
                ZoneInfo(self.source_timezone)
            except ZoneInfoNotFoundError as exc:
                raise TimezoneValidationError(
                    f"Invalid source_timezone in DATE_INTERVAL: {self.source_timezone}"
                ) from exc
            if self.public_available_at is not None:
                raise PointInTimeError("DATE_INTERVAL public availability cannot specify exact public_available_at")

        elif self.kind == PublicAvailabilityKind.UNKNOWN:
            if self.public_available_at is not None:
                raise PointInTimeError("UNKNOWN public availability cannot specify public_available_at")
            if self.interval_start is not None or self.interval_end is not None:
                raise PointInTimeError("UNKNOWN public availability cannot specify interval dates")

    def is_point_in_time_available(self, cutoff: datetime) -> bool:
        """Evaluate if this observation was verifiably available to the public at or before cutoff.

        Rule:
        - EXACT: public_available_at <= cutoff
        - DATE_INTERVAL: interval_end <= cutoff (conservative upper bound)
        - UNKNOWN: False (cannot verify availability at cutoff)
        """
        if cutoff.tzinfo is None:
            raise TimezoneValidationError("Cutoff datetime must be timezone-aware")
        if self.kind == PublicAvailabilityKind.EXACT:
            return self.public_available_at is not None and self.public_available_at <= cutoff
        if self.kind == PublicAvailabilityKind.DATE_INTERVAL:
            return self.interval_end is not None and self.interval_end <= cutoff
        return False

    @classmethod
    def exact(cls, available_at: datetime, *, locator: str) -> PublicAvailability:
        if not locator or not locator.strip():
            raise PointInTimeError("EXACT public availability requires non-empty source locator")
        return cls(
            kind=PublicAvailabilityKind.EXACT,
            public_available_at=available_at,
            source_locator=locator,
        )

    @classmethod
    def instant(cls, available_at: datetime, locator: str | None = None) -> PublicAvailability:
        resolved_locator = locator if (locator and locator.strip()) else "instant://observed"
        return cls.exact(available_at, locator=resolved_locator)

    @classmethod
    def date_interval(
        cls,
        start: datetime,
        end: datetime,
        *,
        source_timezone: str = "UTC",
        tz: str | None = None,
        locator: str | None = None,
    ) -> PublicAvailability:
        resolved_tz = tz or source_timezone
        return cls(
            kind=PublicAvailabilityKind.DATE_INTERVAL,
            interval_start=start,
            interval_end=end,
            source_timezone=resolved_tz,
            source_locator=locator,
        )

    @classmethod
    def from_source_date(
        cls,
        source_date: str | date,
        source_timezone: str | None = None,
        *,
        tz: str | None = None,
        locator: str | None = None,
    ) -> PublicAvailability:
        """Construct DATE_INTERVAL spanning local midnight to next local midnight in UTC."""
        resolved_tz = tz or source_timezone
        if not resolved_tz or not resolved_tz.strip():
            raise TimezoneValidationError("source_timezone cannot be empty")
        try:
            zone = ZoneInfo(resolved_tz)
        except ZoneInfoNotFoundError as exc:
            raise TimezoneValidationError(f"Invalid IANA timezone: {resolved_tz}") from exc

        if isinstance(source_date, str):
            try:
                parsed_date = date.fromisoformat(source_date.strip())
            except ValueError as exc:
                raise ContractValidationError(f"Invalid source_date format: {source_date}") from exc
        elif isinstance(source_date, date):
            parsed_date = source_date
        else:
            raise ContractValidationError(f"source_date must be str or date, got {type(source_date).__name__}")

        local_start = datetime.combine(parsed_date, time.min, tzinfo=zone)
        local_end = datetime.combine(parsed_date + timedelta(days=1), time.min, tzinfo=zone)

        utc_start = local_start.astimezone(timezone.utc)
        utc_end = local_end.astimezone(timezone.utc)

        return cls(
            kind=PublicAvailabilityKind.DATE_INTERVAL,
            interval_start=utc_start,
            interval_end=utc_end,
            source_timezone=resolved_tz,
            source_locator=locator,
        )

    @classmethod
    def unknown(cls, *, locator: str | None = None) -> PublicAvailability:
        return cls(kind=PublicAvailabilityKind.UNKNOWN, source_locator=locator)



@dataclass(frozen=True, slots=True)
class PinnedPersonalState:
    """Immutable snapshot reference to personal ledger/portfolio state for a run."""

    state_version: int
    personal_db_instance_id: str | None = None
    portfolio_snapshot_id: str | None = None
    portfolio_data_as_of: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.state_version, bool) or not isinstance(self.state_version, int):
            raise ContractValidationError(
                f"state_version must be integer, got {type(self.state_version).__name__}"
            )
        if self.state_version < 0:
            raise ContractValidationError(f"state_version must be non-negative: {self.state_version}")


@dataclass(frozen=True, slots=True)
class RunContext:
    """Execution context and isolated clock for deterministic runs."""

    run_id: str
    request_mode: str
    analysis_as_of: datetime
    analysis_timezone: str
    runtime_version: str = "0.1.0"
    config_version: str = "1.3"
    contract_version: str = CONTRACT_VERSION
    source_manifest_hash: str | None = None
    pinned_personal_state: PinnedPersonalState | None = None

    def __post_init__(self) -> None:
        if not self.run_id or not isinstance(self.run_id, str):
            raise ContractValidationError("run_id must be a non-empty string")
        if not isinstance(self.analysis_as_of, datetime) or self.analysis_as_of.tzinfo is None:
            raise TimezoneValidationError(
                f"analysis_as_of must be timezone-aware datetime: {self.analysis_as_of}"
            )
        try:
            ZoneInfo(self.analysis_timezone)
        except ZoneInfoNotFoundError as exc:
            raise TimezoneValidationError(
                f"analysis_timezone must be a valid IANA timezone: {self.analysis_timezone}"
            ) from exc

    def is_public_data_available(self, availability: PublicAvailability) -> bool:
        """Check if an item's availability satisfies this run's cutoff."""
        return availability.is_point_in_time_available(self.analysis_as_of)


# Register decoders
def _decode_public_availability(payload: dict[str, Any]) -> PublicAvailability:
    allowed_keys = {
        "kind",
        "public_available_at",
        "interval_start",
        "interval_end",
        "source_timezone",
        "source_locator",
    }
    extra = set(payload.keys()) - allowed_keys
    if extra:
        raise ContractValidationError(f"PublicAvailability payload has extra keys: {sorted(extra)}")

    if "kind" not in payload:
        raise ContractValidationError("PublicAvailability payload missing required key: 'kind'")

    pub_at = datetime.fromisoformat(payload["public_available_at"]) if payload.get("public_available_at") else None
    start = datetime.fromisoformat(payload["interval_start"]) if payload.get("interval_start") else None
    end = datetime.fromisoformat(payload["interval_end"]) if payload.get("interval_end") else None
    return PublicAvailability(
        kind=payload["kind"],
        public_available_at=pub_at,
        interval_start=start,
        interval_end=end,
        source_timezone=payload.get("source_timezone"),
        source_locator=payload.get("source_locator"),
    )


def _decode_pinned_personal_state(payload: dict[str, Any]) -> PinnedPersonalState:
    allowed_keys = {
        "state_version",
        "personal_db_instance_id",
        "portfolio_snapshot_id",
        "portfolio_data_as_of",
    }
    extra = set(payload.keys()) - allowed_keys
    if extra:
        raise ContractValidationError(f"PinnedPersonalState payload has extra keys: {sorted(extra)}")

    if "state_version" not in payload:
        raise ContractValidationError("PinnedPersonalState payload missing required key: 'state_version'")

    return PinnedPersonalState(
        state_version=int(payload["state_version"]),
        personal_db_instance_id=payload.get("personal_db_instance_id"),
        portfolio_snapshot_id=payload.get("portfolio_snapshot_id"),
        portfolio_data_as_of=payload.get("portfolio_data_as_of"),
    )


def _decode_run_context(payload: dict[str, Any]) -> RunContext:
    allowed_keys = {
        "run_id",
        "request_mode",
        "analysis_as_of",
        "analysis_timezone",
        "runtime_version",
        "config_version",
        "contract_version",
        "source_manifest_hash",
        "pinned_personal_state",
    }
    extra = set(payload.keys()) - allowed_keys
    if extra:
        raise ContractValidationError(f"RunContext payload has extra keys: {sorted(extra)}")

    required_keys = {"run_id", "request_mode", "analysis_as_of", "analysis_timezone"}
    missing = required_keys - set(payload.keys())
    if missing:
        raise ContractValidationError(f"RunContext payload missing required keys: {sorted(missing)}")

    pinned = (
        _decode_pinned_personal_state(payload["pinned_personal_state"])
        if payload.get("pinned_personal_state")
        else None
    )
    return RunContext(
        run_id=payload["run_id"],
        request_mode=payload["request_mode"],
        analysis_as_of=datetime.fromisoformat(payload["analysis_as_of"]),
        analysis_timezone=payload["analysis_timezone"],
        runtime_version=payload.get("runtime_version", "0.1.0"),
        config_version=payload.get("config_version", "1.3"),
        contract_version=payload.get("contract_version", CONTRACT_VERSION),
        source_manifest_hash=payload.get("source_manifest_hash"),
        pinned_personal_state=pinned,
    )


register_decoder("PublicAvailability", _decode_public_availability)
register_decoder("PinnedPersonalState", _decode_pinned_personal_state)
register_decoder("RunContext", _decode_run_context)
