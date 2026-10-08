from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Sequence


VALID_STATUS = {"COMPLETE", "PARTIAL", "UNAVAILABLE", "ERROR"}
VALID_PRICE_BASIS = {"nominal", "real", "split-adjusted"}


@dataclass(frozen=True)
class ForecastRequest:
    instrument_id: str
    currency: str
    as_of: datetime
    current_price: float
    target_date: datetime
    horizon_steps: int
    frequency: str
    target: str = "close"
    target_semantics: str = "terminal_price"
    history: Sequence[float] = field(default_factory=tuple)
    timestamps: Sequence[datetime] = field(default_factory=tuple)
    ohlcv: Any | None = None
    covariates: Mapping[str, Sequence[Any]] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        import math
        import pandas as pd
        if not self.instrument_id or not isinstance(self.instrument_id, str) or not self.instrument_id.strip():
            raise ValueError("instrument_id is required and must be string")
        if not self.currency or not isinstance(self.currency, str) or not self.currency.strip():
            raise ValueError("currency is required and must be string")
        if not self.as_of or self.as_of.tzinfo is None:
            raise ValueError("offset-aware analysis_as_of is required")
        if not isinstance(self.current_price, (int, float)) or isinstance(self.current_price, bool):
            raise ValueError("current_price must be a number")
        if math.isnan(self.current_price) or math.isinf(self.current_price) or self.current_price <= 0:
            raise ValueError("current_price must be positive finite")
        if not isinstance(self.horizon_steps, int) or isinstance(self.horizon_steps, bool) or self.horizon_steps <= 0:
            raise ValueError("horizon_steps must be positive integer")
        if not self.frequency or not str(self.frequency).strip():
            raise ValueError("frequency is required")
        try:
            offset = pd.tseries.frequencies.to_offset(self.frequency)
            if offset is None:
                raise ValueError("invalid frequency")
        except Exception:
            raise ValueError("invalid frequency")
            
        if not self.target_date or self.target_date.tzinfo is None:
            raise ValueError("offset-aware target_date is required")
        if self.target_semantics in {"price_return", "total_return"}:
            raise ValueError("unsupported target_semantics: return models not implemented")
        if self.target_semantics not in {"terminal_price"}:
            raise ValueError("invalid target_semantics")
        if "price_basis" not in self.metadata or self.metadata["price_basis"] not in VALID_PRICE_BASIS:
             raise ValueError("explicit and valid price_basis is required from documented supported enum")
        if getattr(offset, 'n', 1) <= 0:
            raise ValueError("frequency offset n must be positive")

        if len(self.history):
            if len(self.history) < 8:
                raise ValueError("history requires at least 8 points when supplied")
            for h in self.history:
                if isinstance(h, bool) or not isinstance(h, (int, float)) or math.isnan(h) or math.isinf(h) or h <= 0:
                    raise ValueError("history prices must be positive finite numbers")
        
        if self.history and not self.timestamps:
            raise ValueError("timestamps are required when history is supplied")
            
        if self.timestamps:
            if len(self.timestamps) != len(self.history):
                raise ValueError("timestamps/history length mismatch")
            for i, ts in enumerate(self.timestamps):
                if ts.tzinfo is None:
                    raise ValueError("timestamps must be offset-aware")
                if ts > self.as_of:
                    raise ValueError("future observations not allowed")
                if i > 0 and ts <= self.timestamps[i-1]:
                    raise ValueError("timestamps must be strictly ascending (unsorted or duplicate)")
                    
            expected_ts = list(pd.date_range(end=self.timestamps[-1], periods=len(self.timestamps), freq=self.frequency).to_pydatetime())
            if list(self.timestamps) != expected_ts:
                raise ValueError("timestamps must be no-gap frequency-consistent")
                
        origin = self.timestamps[-1] if self.timestamps else self.as_of
        if self.timestamps:
            # The most recently completed observation must be adjacent to the
            # analysis month. Otherwise a nominal 5Y model is applied to a
            # shorter actual elapsed forecast horizon.
            if self.frequency == "ME":
                months_gap = (self.as_of.year - origin.year) * 12 + self.as_of.month - origin.month
                if months_gap > 1:
                    raise ValueError("stale monthly history relative to analysis_as_of")
        expected_target = origin + offset * self.horizon_steps
        if self.target_date != expected_target:
            raise ValueError("target_date must match origin plus horizon frequency exactly")
            
        if self.covariates:
            if "covariate_timestamps" not in self.metadata or "covariate_publication" not in self.metadata:
                raise ValueError("historical covariates require mandatory publication/timestamp bindings")
            cov_ts = self.metadata["covariate_timestamps"]
            cov_pub = self.metadata["covariate_publication"]
            if not cov_ts or not cov_pub:
                raise ValueError("covariate_timestamps and covariate_publication cannot be empty")
            if len(cov_ts) != len(cov_pub):
                raise ValueError("covariate timestamps and publications length mismatch")
            if self.history and len(cov_ts) != len(self.history):
                raise ValueError("covariate_timestamps must align with history")
            for ts, pub in zip(cov_ts, cov_pub):
                if ts.tzinfo is None or pub.tzinfo is None:
                    raise ValueError("covariate timestamps must be offset-aware")
                if pub < ts:
                    raise ValueError("publication before observation timestamp")
                if pub > self.as_of:
                    raise ValueError("covariate publication cannot be after analysis_as_of")
                if ts > self.as_of:
                    raise ValueError("future covariates explicitly rejected as no consumer supports them")
            if list(cov_ts) != list(self.timestamps):
                raise ValueError("covariate timestamps must exactly align with history")
            for k, v in self.covariates.items():
                if not v:
                    raise ValueError("covariate sequence cannot be empty")
                if len(v) != len(cov_ts):
                    raise ValueError("per-feature sequence length must match covariate_timestamps")
                for val in v:
                    if isinstance(val, bool) or not isinstance(val, (int, float)) or math.isnan(val) or math.isinf(val):
                        raise ValueError("covariate values must be finite numeric")


@dataclass(frozen=True)
class ModelForecast:
    model_id: str
    status: str
    instrument_id: str
    currency: str
    as_of: datetime
    target_date: datetime
    price_basis: str
    horizon_steps: int
    frequency: str
    target_semantics: str = "terminal_price"
    point_semantics: str = "point"
    validation_level: str = "EXPERIMENTAL"
    point: float | None = None
    quantiles: Mapping[float, float] = field(default_factory=dict)
    observed_at: datetime | None = None
    details: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None

    def validate(self) -> None:
        import math
        import pandas as pd
        if not self.instrument_id or not isinstance(self.instrument_id, str) or not self.instrument_id.strip():
            raise ValueError("instrument_id is required and must be string")
        if not self.currency or not isinstance(self.currency, str) or not self.currency.strip():
            raise ValueError("currency is required and must be string")
        if self.price_basis not in VALID_PRICE_BASIS:
            raise ValueError("explicit compatible price basis is required from documented supported enum")
        if not self.as_of or self.as_of.tzinfo is None:
            raise ValueError("offset-aware as_of is required")
        if not self.target_date or self.target_date.tzinfo is None:
            raise ValueError("offset-aware target_date is required")
        if not isinstance(self.horizon_steps, int) or isinstance(self.horizon_steps, bool) or self.horizon_steps <= 0:
            raise ValueError("horizon_steps must be positive int")
        if not self.frequency or not str(self.frequency).strip():
            raise ValueError("frequency is required")
        try:
            offset = pd.tseries.frequencies.to_offset(self.frequency)
            if offset is None or getattr(offset, 'n', 1) <= 0:
                raise ValueError("positive known frequency is required")
        except Exception:
            raise ValueError("invalid frequency")
        if self.target_semantics not in {"terminal_price"}:
            raise ValueError("supported target semantics required")
        if self.point_semantics not in {"point", "mean", "median", "mode", "geometric_representative"}:
            raise ValueError("supported point semantics required")

        if self.status not in VALID_STATUS:
            raise ValueError(f"invalid status: {self.status}")
        if self.status == "COMPLETE" and self.point is None:
            raise ValueError("COMPLETE model must have a point forecast")
        if self.point is not None:
            if isinstance(self.point, bool) or not isinstance(self.point, (int, float)) or math.isnan(self.point) or math.isinf(self.point) or self.point <= 0:
                raise ValueError("point forecast must be positive finite number")
                
        if any(isinstance(k, bool) for k in self.quantiles.keys()):
            raise ValueError("quantile keys must not be bool")
        if any(isinstance(v, bool) for v in self.quantiles.values()):
            raise ValueError("quantile values must not be bool")
            
        q = sorted((float(k), float(v)) for k, v in self.quantiles.items())
        if q:
            if q[0][0] < 0 or q[-1][0] > 1:
                raise ValueError("quantile keys must be within [0, 1]")
            for k, _ in q:
                if math.isnan(k) or math.isinf(k):
                    raise ValueError("quantile keys must be finite")
            vals = [v for _, v in q]
            if any(math.isnan(v) or math.isinf(v) or v <= 0 for v in vals):
                raise ValueError("quantile values must be positive finite")
            if any(b < a for a, b in zip(vals, vals[1:])):
                raise ValueError("quantile values must be non-decreasing")


@dataclass(frozen=True)
class FundamentalAnchor:
    status: str
    instrument_id: str
    currency: str
    target_date: datetime
    price_basis: str
    value_kind: str
    as_of: datetime | None = None
    bear: float | None = None
    base: float | None = None
    bull: float | None = None
    evidence_refs: Sequence[str] = field(default_factory=tuple)
    assumption_refs: Sequence[str] = field(default_factory=tuple)
    details: Mapping[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        import math
        if self.status not in VALID_STATUS:
            raise ValueError(f"invalid status: {self.status}")
        if not self.instrument_id or not isinstance(self.instrument_id, str) or not self.instrument_id.strip():
            raise ValueError("instrument_id is required and must be string")
        if not self.currency or not isinstance(self.currency, str) or not self.currency.strip():
            raise ValueError("currency is required and must be string")
        if not self.target_date:
            raise ValueError("target_date is required")
        if self.price_basis not in VALID_PRICE_BASIS:
            raise ValueError("price_basis must be from supported enum")
        if self.target_date.tzinfo is None:
            raise ValueError("target_date must be offset-aware")
        if self.as_of is not None and self.as_of.tzinfo is None:
            raise ValueError("as_of must be offset-aware if provided")
            
        if self.value_kind not in {"terminal_price", "current_fair_value", "presentDCF"}:
            raise ValueError(f"invalid kind: {self.value_kind}")
        
        vals = [x for x in (self.bear, self.base, self.bull) if x is not None]
        for v in vals:
            if isinstance(v, bool) or not isinstance(v, (int, float)) or math.isnan(v) or math.isinf(v) or v <= 0:
                raise ValueError("anchor prices must be positive finite numbers")
        
        if all(x is not None for x in (self.bear, self.base, self.bull)):
            if not (self.bear <= self.base <= self.bull):
                raise ValueError("anchor must satisfy bear <= base <= bull")
                
        if self.status == "COMPLETE":
            if not self.evidence_refs or not self.assumption_refs:
                raise ValueError("COMPLETE anchor requires both evidence and assumption references")


@dataclass(frozen=True)
class EnsembleForecast:
    instrument_id: str
    currency: str
    as_of: datetime
    target_date: datetime
    price_basis: str
    horizon_steps: int
    frequency: str
    status: str
    point: float | None
    quantiles: Mapping[float, float]
    component_weights: Mapping[str, float]
    components: Sequence[ModelForecast]
    target_semantics: str = "terminal_price"
    point_semantics: str = "geometric_representative"
    validation_level: str = "EXPERIMENTAL"
    anchor: FundamentalAnchor | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        import math
        if not self.instrument_id or not isinstance(self.instrument_id, str) or not self.instrument_id.strip():
            raise ValueError("instrument_id is required and must be string")
        if not self.currency or not isinstance(self.currency, str) or not self.currency.strip():
            raise ValueError("currency is required and must be string")
        if self.price_basis not in VALID_PRICE_BASIS:
            raise ValueError("price_basis must be from supported enum")
        if not self.as_of or self.as_of.tzinfo is None:
            raise ValueError("offset-aware as_of is required")
        if not self.target_date or self.target_date.tzinfo is None:
            raise ValueError("offset-aware target_date is required")
        if not isinstance(self.horizon_steps, int) or isinstance(self.horizon_steps, bool) or self.horizon_steps <= 0:
            raise ValueError("horizon_steps must be positive int")
        if not self.frequency or not str(self.frequency).strip():
            raise ValueError("frequency is required")
        if self.target_semantics not in {"terminal_price"}:
            raise ValueError("supported target semantics required")
        if self.point_semantics not in {"geometric_representative"}:
            raise ValueError("point_semantics must be geometric_representative")
        if self.status not in VALID_STATUS:
            raise ValueError(f"invalid status: {self.status}")
        if self.status == "COMPLETE" and self.point is None:
            raise ValueError("COMPLETE model must have a point forecast")
        if self.point is not None:
            if isinstance(self.point, bool) or not isinstance(self.point, (int, float)) or math.isnan(self.point) or math.isinf(self.point) or self.point <= 0:
                raise ValueError("point forecast must be positive finite number")
        
        if any(isinstance(k, bool) for k in self.quantiles.keys()):
            raise ValueError("quantile keys must not be bool")
        if any(isinstance(v, bool) for v in self.quantiles.values()):
            raise ValueError("quantile values must not be bool")

        q = sorted((float(k), float(v)) for k, v in self.quantiles.items())
        if q:
            if q[0][0] < 0 or q[-1][0] > 1:
                raise ValueError("quantile keys must be within [0, 1]")
            for k, _ in q:
                if math.isnan(k) or math.isinf(k):
                     raise ValueError("quantile keys must be finite")
            vals = [v for _, v in q]
            if any(math.isnan(v) or math.isinf(v) or v <= 0 for v in vals):
                raise ValueError("quantile values must be positive finite")
            if any(b < a for a, b in zip(vals, vals[1:])):
                raise ValueError("quantile values must be non-decreasing")

        total = sum(self.component_weights.values())
        if self.component_weights and abs(total - 1.0) > 1e-6:
            raise ValueError(f"weights must sum to 1, got {total}")
        
        for w in self.component_weights.values():
            if isinstance(w, bool) or not isinstance(w, (int, float)) or math.isnan(w) or math.isinf(w) or w < 0:
                raise ValueError("weights must be non-negative finite")

        model_ids = [c.model_id for c in self.components]
        if len(model_ids) != len(set(model_ids)):
            raise ValueError("duplicate model identities in components")
        
        # Check components binding
        for c in self.components:
            if c.instrument_id != self.instrument_id or c.currency != self.currency or c.target_date != self.target_date or c.price_basis != self.price_basis:
                raise ValueError(f"component {c.model_id} binding mismatch")
            if c.as_of != self.as_of or c.horizon_steps != self.horizon_steps or c.frequency != self.frequency:
                raise ValueError(f"component {c.model_id} time properties mismatch")
            c.validate()
            
        if self.anchor is not None:
            if self.anchor.instrument_id != self.instrument_id or self.anchor.currency != self.currency or self.anchor.target_date != self.target_date or self.anchor.price_basis != self.price_basis:
                raise ValueError("anchor binding mismatch")
            if self.anchor.value_kind in {"current_fair_value", "presentDCF"}:
                raise ValueError("current fair value cannot be used as terminal anchor")
            self.anchor.validate()
