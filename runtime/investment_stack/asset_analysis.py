"""Fixed Phase 5 asset-analysis runtime built on validated Phase 4 evidence inputs."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Callable, Mapping

from investment_stack.calculations import (
    AllocationAnalyzer,
    AllocationResult,
    AlternativeAssetAnalyzer,
    AlternativeAssetInput,
    AnalysisResult,
    AssetRiskInput,
    EquityFundamentalAnalyzer,
    EquityFundamentalInput,
    EquityValuationAnalyzer,
    EquityValuationInput,
    FundAnalysisInput,
    FundAnalyzer,
    InstrumentProfile,
    PortfolioRiskAnalyzer,
    PortfolioRiskResult,
    PositionExposure,
    resolve_instrument,
)
from investment_stack.evidence import RunDatabaseManager
from investment_stack.materiality import LightweightAsset, MaterialityDecision, MaterialityEngine, MaterialityResult


@dataclass(frozen=True, slots=True)
class EquityDeepResult:
    fundamental: AnalysisResult
    valuation: AnalysisResult


@dataclass(frozen=True, slots=True)
class PortfolioPhase5Result:
    materiality: tuple[MaterialityResult, ...]
    deep_results: Mapping[str, object]
    allocation: AllocationResult
    risk: PortfolioRiskResult


class Phase5AssetAnalysisRuntime:
    """Deterministic Phase 5 flow; does not fetch data and never mutates personal.db."""

    def __init__(self, run_db: RunDatabaseManager, *, materiality: MaterialityEngine) -> None:
        self.run_db = run_db
        self.materiality = materiality
        self.equity = EquityFundamentalAnalyzer()
        self.valuation = EquityValuationAnalyzer()
        self.fund = FundAnalyzer()
        self.alternative = AlternativeAssetAnalyzer()
        self.allocation = AllocationAnalyzer()
        self.risk = PortfolioRiskAnalyzer()

    def analyze_equity(self, fundamental: EquityFundamentalInput, valuation: EquityValuationInput) -> EquityDeepResult:
        if fundamental.instrument_id != valuation.instrument_id:
            raise ValueError("fundamental and valuation inputs must refer to the same instrument")
        f_result = self._persist_result(self.equity.analyze(fundamental))
        v_result = self._persist_result(self.valuation.analyze(valuation))
        return EquityDeepResult(f_result, v_result)

    def analyze_fund(self, data: FundAnalysisInput) -> AnalysisResult:
        return self._persist_result(self.fund.analyze(data))

    def analyze_alternative(self, data: AlternativeAssetInput) -> AnalysisResult:
        return self._persist_result(self.alternative.analyze(data))

    def resolve(self, profile: InstrumentProfile):
        return resolve_instrument(profile)

    def analyze_portfolio(
        self,
        *,
        lightweight_assets: tuple[LightweightAsset, ...],
        exposures: tuple[PositionExposure, ...],
        risk_assets: tuple[AssetRiskInput, ...],
        deep_analyzers: Mapping[str, Callable[[], object]],
        allocation_denominator: Decimal | None = None,
        denominator_resolved: bool = True,
        calculation_evidence_ids: tuple[str, ...] = (),
    ) -> PortfolioPhase5Result:
        decisions = self.materiality.evaluate_all(lightweight_assets)
        for decision in decisions:
            self._persist_materiality(decision)
        selected_ids = {
            item.instrument_id
            for item in decisions
            if item.decision in {
                MaterialityDecision.PASS,
                MaterialityDecision.AUTO_PASS_USER_SPECIFIED,
                MaterialityDecision.PASS_UNCERTAINTY,
            }
        }
        # Deep research is invoked only after every lightweight decision has been produced.
        deep_results: dict[str, object] = {}
        for instrument_id in sorted(selected_ids):
            callback = deep_analyzers.get(instrument_id)
            if callback is not None:
                deep_results[instrument_id] = callback()
        allocation = self.allocation.analyze(
            exposures,
            denominator=allocation_denominator,
            denominator_resolved=denominator_resolved,
        )
        risk = self.risk.analyze(risk_assets)
        self._persist_portfolio_calculation("cross_asset_allocation", allocation, calculation_evidence_ids)
        self._persist_portfolio_calculation("portfolio_risk", risk, calculation_evidence_ids)
        return PortfolioPhase5Result(decisions, deep_results, allocation, risk)

    def _persist_result(self, result: AnalysisResult) -> AnalysisResult:
        calculation_id = f"calc:{uuid.uuid4().hex}"
        self.run_db.add_calculation(
            calculation_id=calculation_id,
            calculation_name=result.analysis_type,
            formula="deterministic_phase5_asset_analysis",
            inputs={"subject": result.subject, "evidence_ids": sorted({eid for metric in result.metrics for eid in metric.evidence_ids})},
            result=self._jsonable(result),
        )
        return AnalysisResult(
            result.subject,
            result.analysis_type,
            result.status,
            result.metrics,
            result.findings,
            result.risks,
            result.unknowns,
            {**dict(result.metadata), "calculation_id": calculation_id},
        )

    def _persist_materiality(self, result: MaterialityResult) -> None:
        self.run_db.add_materiality_decision(
            decision_id=f"materiality:{uuid.uuid4().hex}",
            subject=result.instrument_id,
            decision=result.decision.value,
            rationale="; ".join(result.reasons) + f"; config={result.config_version}",
        )

    def _persist_portfolio_calculation(
        self,
        name: str,
        result: object,
        evidence_ids: tuple[str, ...] = (),
    ) -> None:
        self.run_db.add_calculation(
            calculation_id=f"calc:{uuid.uuid4().hex}",
            calculation_name=name,
            formula="deterministic_phase5_portfolio_calculation",
            inputs={"evidence_ids": list(evidence_ids)},
            result=self._jsonable(result),
        )

    @classmethod
    def _jsonable(cls, value: object) -> object:
        if isinstance(value, Decimal):
            return str(value)
        if hasattr(value, "value") and isinstance(getattr(value, "value"), str):
            return getattr(value, "value")
        if hasattr(value, "__dataclass_fields__"):
            return {key: cls._jsonable(item) for key, item in asdict(value).items()}
        if isinstance(value, Mapping):
            return {str(key): cls._jsonable(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [cls._jsonable(item) for item in value]
        return value
