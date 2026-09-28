"""Safe adapter from the portfolio materiality gate to live equity research.

The adapter receives an already approved selection and resolved specs. It never
opens personal state, resolves identities, applies a materiality policy, or posts
orders. Phase 4 evidence and Phase 5 calculations remain in the bound run.db.
"""

from __future__ import annotations

import json
from typing import Mapping

from investment_stack.deep_research import EquityResearchSpec, LiveDeepResearchRuntime
from investment_stack.execution.models import ModeRequest
from investment_stack.execution.portfolio_thesis_modes import SelectedAssetResearchResult
from investment_stack.reporting.models import Availability as ReportAvailability, ReportSectionInput
from investment_stack.routing import RequestMode


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
        if request.mode is not RequestMode.PERSONAL_PORTFOLIO_ANALYSIS:
            return self._unsupported(instrument_ids,
                                     "selected asset research is only available in PERSONAL_PORTFOLIO_ANALYSIS")
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
        run_evidence = {row["evidence_id"]: row for row in context["evidence"]}
        run_calculations = {row["calculation_id"]: row for row in context["calculations"]}

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
            analysis_context = run_db.fetch_phase6_context()
            run_evidence = {row["evidence_id"]: row for row in analysis_context["evidence"]}
            run_calculations = {row["calculation_id"]: row for row in analysis_context["calculations"]}
            evidence: tuple[str, ...] = tuple(dict.fromkeys(
                ref for ref in outcome.evidence_ids
                if ref in run_evidence and run_evidence[ref].get("instrument_id") == instrument_id
            ))
            for ref in outcome.evidence_ids:
                if ref not in run_evidence or run_evidence[ref].get("instrument_id") != instrument_id:
                    missing.append(f"run_db_evidence_binding:{instrument_id}:{ref}")
            raw_calculations = tuple(dict.fromkeys(
                ref for ref in (
                    outcome.analysis.fundamental.metadata.get("calculation_id"),
                    outcome.analysis.valuation.metadata.get("calculation_id"),
                ) if isinstance(ref, str) and ref
            ))
            calculations: tuple[str, ...] = tuple(
                ref for ref in raw_calculations
                if self._calculation_matches(run_calculations.get(ref), instrument_id, evidence)
            )
            for ref in raw_calculations:
                if not self._calculation_matches(run_calculations.get(ref), instrument_id, evidence):
                    missing.append(f"run_db_calculation_binding:{instrument_id}:{ref}")
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
            lines.extend(f"재무 분석: {item}" for item in outcome.analysis.fundamental.findings)
            lines.extend(f"가치평가: {item}" for item in outcome.analysis.valuation.findings)
            dcf_values = []
            for metric in outcome.analysis.valuation.metrics:
                if metric.value is None:
                    continue
                if not metric.evidence_ids or not set(metric.evidence_ids).issubset(evidence):
                    missing_marker = f"valuation_metric_evidence:{instrument_id}"
                    if missing_marker not in missing:
                        missing.append(missing_marker)
                    continue
                valuation_calculation_id = outcome.analysis.valuation.metadata.get("calculation_id")
                valuation_calculation = run_calculations.get(valuation_calculation_id)
                if (not calculations or valuation_calculation_id not in calculations
                        or not self._metric_matches_persisted(valuation_calculation, metric)):
                    missing_marker = f"valuation_metric_persistence:{instrument_id}"
                    if missing_marker not in missing:
                        missing.append(missing_marker)
                    continue
                unit = f" {metric.unit}" if metric.unit else ""
                if metric.name.startswith("dcf_"):
                    dcf_values.append(metric)
                    lines.append(
                        f"명시 가정에 따른 조건부 평가값, 매수 가격 아님: {metric.name}={metric.value}{unit}"
                    )
                else:
                    lines.append(f"근거 연결 평가 지표: {metric.name}={metric.value}{unit}")
            lines.extend(f"미확인: {item}" for item in (*outcome.analysis.fundamental.unknowns, *outcome.analysis.valuation.unknowns))
            asset_missing = tuple(item for item in missing if item.endswith(":" + instrument_id))
            lines.extend(f"미완료 입력: {item}" for item in asset_missing)
            sections.append(ReportSectionInput(
                name=f"selected_asset:{instrument_id}",
                title=f"선택 자산 분석: {self.specs[instrument_id].display_name}",
                lines=tuple(lines),
                status=ReportAvailability.PARTIAL if any(item.endswith(":" + instrument_id) for item in missing)
                else ReportAvailability.AVAILABLE,
                evidence_ids=evidence,
                calculation_ids=calculations,
                metadata={"instrument_id": instrument_id, "analysis_as_of": self.runtime.analysis_as_of,
                          "currency": self.specs[instrument_id].currency,
                          "missing_inputs": asset_missing,
                          "conditional_dcf_values_present": bool(dcf_values)},
            ))
            evidence_refs.extend(evidence)
            calculation_refs.extend(calculations)
        return SelectedAssetResearchResult(tuple(sections), evidence_refs=tuple(evidence_refs),
                                           calculation_refs=tuple(calculation_refs), missing_inputs=tuple(missing))

    @staticmethod
    def _partial(instrument_ids: tuple[str, ...], missing: str) -> SelectedAssetResearchResult:
        sections = tuple(ReportSectionInput(
            name=f"selected_asset:{item}", title=f"선택 자산 분석: {item}",
            lines=("WAIT: 선택 자산 분석에 필요한 입력이 없어 분석하지 않았습니다.",
                   f"미완료 사유: {missing}"),
            status=ReportAvailability.UNAVAILABLE, metadata={"instrument_id": item},
        ) for item in instrument_ids)
        return SelectedAssetResearchResult(sections, missing_inputs=(missing,))

    @classmethod
    def _unsupported(cls, instrument_ids: tuple[str, ...], reason: str) -> SelectedAssetResearchResult:
        result = cls._partial(instrument_ids, reason)
        return SelectedAssetResearchResult(result.sections, missing_inputs=(), unsupported_reasons=(reason,))

    @staticmethod
    def _calculation_matches(
        row: Mapping[str, object] | None, instrument_id: str, evidence_ids: tuple[str, ...],
    ) -> bool:
        if row is None:
            return False
        try:
            inputs = json.loads(str(row.get("inputs_json") or "{}"))
        except (TypeError, json.JSONDecodeError):
            return False
        if not isinstance(inputs, dict) or inputs.get("subject") != instrument_id:
            return False
        input_evidence = inputs.get("evidence_ids")
        return (isinstance(input_evidence, list)
                and set(evidence_ids).issubset(set(input_evidence)))

    @staticmethod
    def _metric_matches_persisted(row: Mapping[str, object] | None, metric: object) -> bool:
        if row is None:
            return False
        try:
            result = json.loads(str(row.get("result_json") or "{}"))
        except (TypeError, json.JSONDecodeError):
            return False
        if not isinstance(result, dict) or not isinstance(result.get("metrics"), list):
            return False
        name = getattr(metric, "name", None)
        value = getattr(metric, "value", None)
        unit = getattr(metric, "unit", None)
        status = getattr(getattr(metric, "status", None), "value", None)
        evidence_ids = tuple(getattr(metric, "evidence_ids", ()))
        for stored in result["metrics"]:
            if not isinstance(stored, dict) or stored.get("name") != name:
                continue
            stored_evidence = stored.get("evidence_ids")
            if not isinstance(stored_evidence, list):
                continue
            if (stored.get("value") == (str(value) if value is not None else None)
                    and stored.get("unit") == unit
                    and stored.get("status") == status
                    and tuple(stored_evidence) == evidence_ids):
                return True
        return False
