from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence
import math

from .contracts import EnsembleForecast, ForecastRequest, FundamentalAnchor, ModelForecast
from .guardrails import anchor_ratio_guard


@dataclass(frozen=True)
class EnsemblePolicy:
    # Bootstrap priors only. Walk-forward OOS evidence should replace these multipliers.
    anchor_weight: float = 0.60
    model_priors: Mapping[str, float] = field(default_factory=lambda: {
        "Vincent05R/FinCast-v1": 0.05,
        "NeoQuasar/Kronos-mini": 0.15,
        "autogluon/chronos-2-small": 0.20,
        "xgboost-tabular-5y": 0.10,
        "lightgbm-tabular-5y": 0.10,
    })
    min_models_for_complete_output: int = 2
    reject_anchor_ratio_outliers: bool = True


class ForecastEnsembler:
    def __init__(self, policy: EnsemblePolicy | None = None):
        self.policy = policy or EnsemblePolicy()

    @staticmethod
    def _normalize(weights: Mapping[str, float]) -> dict[str, float]:
        for v in weights.values():
            if not isinstance(v, (int, float)) or math.isnan(v) or math.isinf(v) or v < 0:
                raise ValueError("weights must be finite and non-negative")
        s = sum(weights.values())
        if s <= 0:
            return {}
        return {k: float(v) / s for k, v in weights.items() if v > 0}

    @staticmethod
    def _weighted_geo(values: Sequence[float], weights: Sequence[float]) -> float:
        if not values or len(values) != len(weights):
            raise ValueError("values/weights mismatch")
        if any(v <= 0 for v in values):
            raise ValueError("geometric blend requires positive values")
        sw = sum(weights)
        if sw <= 0:
            raise ValueError("weights must be positive")
        return math.exp(sum((w / sw) * math.log(v) for v, w in zip(values, weights)))

    def combine(
        self,
        request: ForecastRequest,
        forecasts: Sequence[ModelForecast],
        anchor: FundamentalAnchor | None,
        reliability: Mapping[str, float] | None = None,
    ) -> EnsembleForecast:
        request.validate()
        excluded: dict[str, str] = {}
        usable: list[ModelForecast] = []
        model_ids = set()

        # An unqualified anchor must have *no* effect on peer eligibility,
        # price basis, or the guardrail. Validate its own contract first.
        eligible_anchor = None
        if anchor is not None:
            try:
                anchor.validate()
                if anchor.as_of is None:
                    raise ValueError("anchor as_of unknown; cannot establish PIT provenance")
                if anchor.as_of > request.as_of:
                    raise ValueError("future anchor as_of exceeds request as_of")
                if anchor.value_kind != "terminal_price":
                    raise ValueError("anchor value_kind must be terminal_price")
                if (anchor.instrument_id != request.instrument_id or
                    anchor.currency != request.currency or
                    anchor.target_date != request.target_date):
                    raise ValueError("anchor binding mismatch")
                if anchor.price_basis != request.metadata["price_basis"]:
                    raise ValueError("anchor price_basis mismatch")
                if anchor.status not in {"COMPLETE", "PARTIAL"}:
                    raise ValueError(f"anchor status {anchor.status} is not usable")
                if anchor.base is None or anchor.base <= 0:
                    raise ValueError("missing or invalid base")
                eligible_anchor = anchor
            except (ValueError, TypeError, KeyError) as exc:
                excluded["fundamental-anchor"] = f"anchor ineligible: {exc}"

        for f in forecasts:
            try:
                f.validate()
            except Exception as e:
                excluded[f.model_id] = f"validation failed: {e}"
                continue
            if f.model_id in model_ids:
                excluded[f.model_id] = "duplicate model identity"
                continue
            model_ids.add(f.model_id)

            if f.status not in {"COMPLETE", "PARTIAL"}:
                excluded[f.model_id] = f"status is {f.status}"
                continue
            if f.point is None or f.point <= 0:
                excluded[f.model_id] = "invalid or missing point"
                continue
            if f.instrument_id != request.instrument_id or f.currency != request.currency:
                excluded[f.model_id] = "instrument or currency mismatch"
                continue
            if f.as_of != request.as_of or f.target_date != request.target_date:
                excluded[f.model_id] = "as_of or target_date mismatch"
                continue
            if f.horizon_steps != request.horizon_steps or f.frequency != request.frequency:
                excluded[f.model_id] = "horizon or frequency mismatch"
                continue
            if f.target_semantics != request.target_semantics:
                excluded[f.model_id] = "target_semantics mismatch"
                continue
            if f.price_basis != request.metadata.get("price_basis"):
                excluded[f.model_id] = "price_basis mismatch"
                continue

            if self.policy.reject_anchor_ratio_outliers and eligible_anchor is not None:
                ok, reason = anchor_ratio_guard(f, eligible_anchor)
                if not ok:
                    excluded[f.model_id] = reason or "guardrail rejected"
                    continue
            usable.append(f)

        anchor_model = None
        if eligible_anchor is not None:
            anchor_model = ModelForecast(
                model_id="fundamental-anchor",
                status=eligible_anchor.status,
                instrument_id=eligible_anchor.instrument_id,
                currency=eligible_anchor.currency,
                as_of=request.as_of,
                target_date=eligible_anchor.target_date,
                price_basis=eligible_anchor.price_basis,
                horizon_steps=request.horizon_steps,
                frequency=request.frequency,
                target_semantics=request.target_semantics,
                point=eligible_anchor.base,
                quantiles={},
                details={"anchor_provenance_as_of": eligible_anchor.as_of.isoformat(),
                         "anchor_evidence_refs": list(eligible_anchor.evidence_refs),
                         "anchor_assumption_refs": list(eligible_anchor.assumption_refs)},
            )
            anchor_model.validate()

        components: list[ModelForecast] = list(usable)
        raw_weights: dict[str, float] = {}
        if anchor_model is not None:
            components.insert(0, anchor_model)
            raw_weights[anchor_model.model_id] = self.policy.anchor_weight

        reliability = reliability or {}
        for f in usable:
            prior = self.policy.model_priors.get(f.model_id)
            if prior is None:
                excluded[f.model_id] = "unknown model prior"
                continue
            if isinstance(prior, bool) or not isinstance(prior, (int, float)) or math.isnan(prior) or math.isinf(prior) or prior < 0:
                excluded[f.model_id] = "invalid prior"
                continue
            score = reliability.get(f.model_id, 1.0)
            if not isinstance(score, (int, float)) or math.isnan(score) or math.isinf(score) or score < 0:
                excluded[f.model_id] = "invalid reliability score"
                continue
            w = prior * score
            if w <= 0:
                excluded[f.model_id] = "zero effective weight"
                continue
            raw_weights[f.model_id] = w

        components = [c for c in components if c.model_id in raw_weights]
        
        try:
            weights = self._normalize(raw_weights)
        except ValueError as e:
            weights = {}

        if not components or not weights:
            return EnsembleForecast(
                instrument_id=request.instrument_id, currency=request.currency, as_of=request.as_of,
                target_date=request.target_date, price_basis=request.metadata.get('price_basis', 'unknown'),
                horizon_steps=request.horizon_steps, frequency=request.frequency, target_semantics=request.target_semantics,
                status="UNAVAILABLE", point=None, quantiles={}, component_weights={}, components=tuple(forecasts), 
                point_semantics="geometric_representative", validation_level="EXPERIMENTAL", anchor=eligible_anchor,
                details={"reason": "no usable components", "excluded": excluded},
            )

        pvals, pweights = [], []
        has_partial = False
        model_count = 0
        for c in components:
            if c.model_id != "fundamental-anchor":
                model_count += 1
            if c.status == "PARTIAL":
                has_partial = True
            if c.point is not None and c.model_id in weights:
                pvals.append(float(c.point))
                pweights.append(weights[c.model_id])
            
        point = self._weighted_geo(pvals, pweights) if pvals else None

        status = "COMPLETE" if not has_partial and anchor_model is not None and model_count >= self.policy.min_models_for_complete_output else "PARTIAL"
        
        if point is None:
            status = "UNAVAILABLE"
            
        out = EnsembleForecast(
            instrument_id=request.instrument_id,
            currency=request.currency,
            as_of=request.as_of,
            target_date=request.target_date,
            price_basis=request.metadata['price_basis'],
            horizon_steps=request.horizon_steps,
            frequency=request.frequency,
            target_semantics=request.target_semantics,
            status=status,
            point=float(point) if point else None,
            quantiles={},
            component_weights=weights,
            components=tuple(components),
            point_semantics="geometric_representative",
            validation_level="EXPERIMENTAL",
            anchor=eligible_anchor,
            details={
                "usable_model_count": model_count,
                "excluded": excluded,
                "blend_space": "log-price",
                "rule": "fundamental-anchored reliability-weighted ensemble",
                "reliability_source": "unverified override unless actual scoped evidence provided",
                "uncertainty": "UNAVAILABLE",
            },
        )
        out.validate()
        return out
