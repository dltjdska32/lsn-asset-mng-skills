"""Safe adapter from the portfolio materiality gate to live equity research.

The adapter receives an already approved selection and resolved specs. It never
opens personal state, resolves identities, applies a materiality policy, or posts
orders. Phase 4 evidence and Phase 5 calculations remain in the bound run.db.
"""

from __future__ import annotations

from typing import Mapping

from investment_stack.deep_research import EquityResearchSpec, LiveDeepResearchRuntime
from investment_stack.execution.models import ModeRequest
from investment_stack.execution.portfolio_thesis_modes import SelectedAssetResearchResult
from investment_stack.reporting.models import Availability as ReportAvailability, ReportSectionInput


class LiveSelectedAssetResearch:
    """Callable implementation of ``SelectedAssetResearch`` for portfolio mode."""

    def __init__(
        self,
        runtime: LiveDeepResearchRuntime,
        specs: Mapping[str, EquityResearchSpec],
    ) -> None:
        self.runtime = runtime
        self.specs = dict(specs)

    def __call__(self, instrument_ids: tuple[str, ...], request: ModeRequest) -> SelectedAssetResearchResult:
        run_db = self.runtime.analysis.run_db
        if self.runtime.research.evidence.run_db is not run_db:
            return self._unsupported(instrument_ids,
                                     "Phase 4 evidence store and Phase 5 analysis must share the same run.db")
        if request.run_id != run_db.run_id:
            return self._unsupported(instrument_ids, "request run_id does not match selected asset research run.db")

        try:
            context = run_db.fetch_phase6_context()
            metadata = context["run_metadata"]
        except (KeyError, TypeError, ValueError):
            return self._partial(instrument_ids, "pinned_run_clock")
        if (metadata.get("analysis_as_of") != self.runtime.analysis_as_of
                or metadata.get("analysis_timezone") != self.runtime.analysis_timezone):
            return self._unsupported(instrument_ids, "deep research clock does not match the pinned run.db clock")

        selected = tuple(instrument_ids)
        if not selected:
            return self._partial((), "selected_assets_for_deep_research")
        if len(selected) != len(set(selected)):
            return self._unsupported(selected, "selected instrument IDs contain duplicates")
        unknown = tuple(item for item in selected if item not in self.specs)
        if unknown:
            return self._partial(selected, "resolved_equity_research_spec:" + ",".join(unknown))
        malformed = tuple(item for item in selected if not isinstance(self.specs[item], EquityResearchSpec))
        if malformed:
            return self._unsupported(selected, "selected assets require resolved EquityResearchSpec values")
        mismatches = tuple(item for item in selected if self.specs[item].instrument_id != item)
        if mismatches:
            return self._unsupported(selected, "resolved research spec instrument ID mismatch: " + ",".join(mismatches))

        sections: list[ReportSectionInput] = []
        evidence_refs: list[str] = []
        calculation_refs: list[str] = []
        missing: list[str] = []
        for instrument_id in selected:
            outcome = self.runtime.analyze_equity(self.specs[instrument_id])
            if outcome.instrument_id != instrument_id:
                return self._unsupported(selected, "live research returned a different instrument ID")
            evidence = tuple(dict.fromkeys(outcome.evidence_ids))
            calculations = tuple(dict.fromkeys(
                ref for ref in (
                    outcome.analysis.fundamental.metadata.get("calculation_id"),
                    outcome.analysis.valuation.metadata.get("calculation_id"),
                ) if isinstance(ref, str) and ref
            ))
            if not calculations:
                missing.append(f"phase5_calculation:{instrument_id}")
            if outcome.market.selected.observation is None:
                missing.append(f"current_price:{instrument_id}")
            if not outcome.fundamentals.selected.selected_observations and outcome.fundamentals.selected.observation is None:
                missing.append(f"fundamentals:{instrument_id}")
            partial_analysis = any(result.status.value != "COMPLETE" for result in (
                outcome.analysis.fundamental, outcome.analysis.valuation,
            ))
            if partial_analysis:
                missing.append(f"phase5_partial:{instrument_id}")
            lines = [f"대상 자산: {self.specs[instrument_id].display_name} ({instrument_id})"]
            lines.append(f"현재가: {outcome.analysis.valuation.status.value}; 통화 {self.specs[instrument_id].currency}")
            lines.extend(f"재무 분석: {item}" for item in outcome.analysis.fundamental.findings)
            lines.extend(f"가치평가: {item}" for item in outcome.analysis.valuation.findings)
            lines.extend(f"미확인: {item}" for item in (*outcome.analysis.fundamental.unknowns, *outcome.analysis.valuation.unknowns))
            sections.append(ReportSectionInput(
                name=f"selected_asset:{instrument_id}",
                title=f"선택 자산 분석: {self.specs[instrument_id].display_name}",
                lines=tuple(lines),
                status=ReportAvailability.PARTIAL if any(item.endswith(":" + instrument_id) for item in missing)
                else ReportAvailability.AVAILABLE,
                evidence_ids=evidence,
                calculation_ids=calculations,
                metadata={"instrument_id": instrument_id, "analysis_as_of": self.runtime.analysis_as_of,
                          "currency": self.specs[instrument_id].currency},
            ))
            evidence_refs.extend(evidence)
            calculation_refs.extend(calculations)
        return SelectedAssetResearchResult(tuple(sections), evidence_refs=tuple(evidence_refs),
                                           calculation_refs=tuple(calculation_refs), missing_inputs=tuple(missing))

    @staticmethod
    def _partial(instrument_ids: tuple[str, ...], missing: str) -> SelectedAssetResearchResult:
        sections = tuple(ReportSectionInput(
            name=f"selected_asset:{item}", title=f"선택 자산 분석: {item}",
            lines=("WAIT: 해석된 종목 스펙 또는 고정 실행 시계가 없어 분석하지 않았습니다.",),
            status=ReportAvailability.UNAVAILABLE, metadata={"instrument_id": item},
        ) for item in instrument_ids)
        return SelectedAssetResearchResult(sections, missing_inputs=(missing,))

    @classmethod
    def _unsupported(cls, instrument_ids: tuple[str, ...], reason: str) -> SelectedAssetResearchResult:
        result = cls._partial(instrument_ids, reason)
        return SelectedAssetResearchResult(result.sections, missing_inputs=(), unsupported_reasons=(reason,))
