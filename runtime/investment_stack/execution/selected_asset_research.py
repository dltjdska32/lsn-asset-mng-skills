"""Safe adapter from the portfolio materiality gate to live equity research.

The adapter receives an already approved selection and resolved specs. It never
opens personal state, resolves identities, applies a materiality policy, or posts
orders. Phase 4 evidence and Phase 5 calculations remain in the bound run.db.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from investment_stack.deep_research import EquityResearchSpec, LiveDeepResearchRuntime
from investment_stack.execution.models import ModeRequest
from investment_stack.execution.portfolio_thesis_modes import SelectedAssetResearchResult
from investment_stack.freshness import FreshnessStatus
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
            close_note = self._last_valid_close_note(
                outcome, self.specs[instrument_id], analysis_context, run_evidence,
            )
            raw_calculations = tuple(dict.fromkeys(
                ref for ref in (
                    outcome.analysis.fundamental.metadata.get("calculation_id"),
                    outcome.analysis.valuation.metadata.get("calculation_id"),
                ) if isinstance(ref, str) and ref
            ))
            analyses = (
                ("fundamental", outcome.analysis.fundamental),
                ("valuation", outcome.analysis.valuation),
            )
            validated: dict[str, bool] = {}
            calculations_list: list[str] = []
            for name, analysis_result in analyses:
                ref = analysis_result.metadata.get("calculation_id")
                row = run_calculations.get(ref) if isinstance(ref, str) else None
                validated[name] = self._analysis_result_matches_persisted(
                    row, analysis_result, instrument_id, run_evidence,
                    permitted_finding=close_note if name == "valuation" else None,
                )
                if validated[name] and isinstance(ref, str):
                    calculations_list.append(ref)
                elif isinstance(ref, str):
                    missing.append(f"phase5_result_binding:{instrument_id}:{name}")
            calculations = tuple(dict.fromkeys(calculations_list))
            if not calculations:
                missing.append(f"phase5_calculation:{instrument_id}")
            if outcome.market.selected.observation is None:
                missing.append(f"current_price:{instrument_id}")
            if not outcome.fundamentals.selected.selected_observations and outcome.fundamentals.selected.observation is None:
                missing.append(f"fundamentals:{instrument_id}")
            partial_analysis = any(not validated[name] or result.status.value != "COMPLETE"
                                    for name, result in analyses)
            if partial_analysis:
                missing.append(f"phase5_partial:{instrument_id}")
            lines = [f"대상 자산: {self.specs[instrument_id].display_name} ({instrument_id})"]
            if validated["fundamental"]:
                lines.extend(f"재무 분석: {item}" for item in outcome.analysis.fundamental.findings)
                lines.extend(f"위험: {item}" for item in outcome.analysis.fundamental.risks)
                lines.extend(f"미확인: {self._display_metric_name(item)}"
                             for item in outcome.analysis.fundamental.unknowns)
            else:
                lines.append("재무 분석 결과는 저장된 계산 근거와 일치하지 않아 표시하지 않았습니다.")
            if validated["valuation"]:
                findings = list(outcome.analysis.valuation.findings)
                if close_note and close_note in findings:
                    findings.remove(close_note)
                lines.extend(f"가치평가: {item}" for item in findings)
                lines.extend(f"위험: {item}" for item in outcome.analysis.valuation.risks)
                lines.extend(f"미확인: {self._display_metric_name(item)}"
                             for item in outcome.analysis.valuation.unknowns)
                if close_note:
                    lines.append(close_note)
            else:
                lines.append("가치평가 결과는 저장된 계산 근거와 일치하지 않아 표시하지 않았습니다.")
            dcf_values = []
            for metric in outcome.analysis.valuation.metrics if validated["valuation"] else ():
                if metric.value is None:
                    continue
                if metric.status.value != "COMPLETE":
                    continue
                if not metric.evidence_ids or not set(metric.evidence_ids).issubset(evidence):
                    missing_marker = f"valuation_metric_evidence:{instrument_id}"
                    if missing_marker not in missing:
                        missing.append(missing_marker)
                    continue
                valuation_calculation_id = outcome.analysis.valuation.metadata.get("calculation_id")
                if not calculations or valuation_calculation_id not in calculations:
                    missing_marker = f"valuation_metric_persistence:{instrument_id}"
                    if missing_marker not in missing:
                        missing.append(missing_marker)
                    continue
                unit = f" {metric.unit}" if metric.unit else ""
                if metric.name.startswith("dcf_"):
                    dcf_values.append(metric)
                    lines.append(
                        f"명시 가정에 따른 조건부 평가값, 매수 가격 아님: "
                        f"{self._display_metric_name(metric.name)}={metric.value}{unit}"
                    )
                else:
                    lines.append(f"근거 연결 평가 지표: {self._display_metric_name(metric.name)}={metric.value}{unit}")
            asset_missing = tuple(item for item in missing
                                  if item.endswith(":" + instrument_id) or f":{instrument_id}:" in item)
            lines.extend(f"미완료 입력: {item}" for item in asset_missing)
            sections.append(ReportSectionInput(
                name=f"selected_asset:{instrument_id}",
                title=f"선택 자산 분석: {self.specs[instrument_id].display_name}",
                lines=tuple(lines),
                status=ReportAvailability.PARTIAL if asset_missing
                else ReportAvailability.AVAILABLE,
                evidence_ids=evidence,
                calculation_ids=calculations,
                metadata={"instrument_id": instrument_id, "analysis_as_of": self.runtime.analysis_as_of,
                          "currency": self.specs[instrument_id].currency,
                          "missing_inputs": asset_missing,
                          "conditional_dcf_values_present": bool(dcf_values)},
            ))
            if outcome.news is not None:
                from investment_stack.reporting.news_delta import news_delta_section
                sections.append(news_delta_section(run_db, instrument_id))
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

    @classmethod
    def _analysis_result_matches_persisted(
        cls, row: Mapping[str, object] | None, result: object, instrument_id: str,
        run_evidence: Mapping[str, Mapping[str, object]], *, permitted_finding: str | None = None,
    ) -> bool:
        if row is None:
            return False
        try:
            inputs = json.loads(str(row.get("inputs_json") or "{}"))
            stored_result = json.loads(str(row.get("result_json") or "{}"))
        except (TypeError, json.JSONDecodeError):
            return False
        if not isinstance(inputs, dict) or inputs.get("subject") != instrument_id:
            return False
        input_evidence = inputs.get("evidence_ids")
        if not isinstance(input_evidence, list):
            return False
        result_evidence = tuple(sorted({
            evidence_id
            for metric in getattr(result, "metrics", ())
            for evidence_id in getattr(metric, "evidence_ids", ())
        }))
        if (set(result_evidence) != set(input_evidence)
                or any(evidence_id not in run_evidence
                       or run_evidence[evidence_id].get("instrument_id") != instrument_id
                       for evidence_id in result_evidence)):
            return False
        if not isinstance(stored_result, dict):
            return False
        expected = cls._serialize_analysis_result(result)
        if stored_result == expected:
            return True
        if permitted_finding is None:
            return False
        findings = list(expected["findings"])
        try:
            findings.remove(permitted_finding)
        except ValueError:
            return False
        expected["findings"] = findings
        return stored_result == expected

    @staticmethod
    def _last_valid_close_note(
        outcome: object, spec: EquityResearchSpec, context: Mapping[str, object],
        run_evidence: Mapping[str, Mapping[str, object]],
    ) -> str | None:
        market = getattr(outcome, "market", None)
        selected = getattr(market, "selected", None)
        observation = getattr(selected, "observation", None)
        assessment = getattr(selected, "freshness", None)
        evidence_id = getattr(selected, "evidence_id", None)
        if (observation is None or assessment is None or evidence_id not in run_evidence
                or getattr(assessment, "status", None) is not FreshnessStatus.LAST_VALID_CLOSE
                or getattr(observation, "evidence_type", None) != "market"
                or getattr(observation, "instrument_id", None) != spec.instrument_id
                or getattr(observation, "currency", None) != spec.currency
                or getattr(observation, "market_session_date", None) != getattr(assessment, "market_session_date", None)
                or run_evidence[evidence_id].get("instrument_id") != spec.instrument_id
                or run_evidence[evidence_id].get("selection_state") != "SELECTED"):
            return None
        market_rows = [row for row in context.get("market_observations", ())
                       if row.get("evidence_id") == evidence_id]
        freshness_rows = [row for row in context.get("freshness_assessments", ())
                          if row.get("evidence_id") == evidence_id]
        if len(market_rows) != 1 or len(freshness_rows) != 1:
            return None
        market_row, freshness_row = market_rows[0], freshness_rows[0]
        try:
            details = json.loads(str(freshness_row.get("details_json") or "{}"))
        except (TypeError, json.JSONDecodeError):
            return None
        session_date = getattr(assessment, "market_session_date", None)
        claimed_time = getattr(observation, "claimed_market_time", None)
        calendar_id = getattr(assessment, "calendar_id", None)
        public_time = getattr(assessment, "public_available_time", None)
        try:
            pinned = LiveSelectedAssetResearch._parse_aware_time(
                str(context["run_metadata"]["analysis_as_of"]),
            )
            effective = LiveSelectedAssetResearch._parse_aware_time(
                str(getattr(assessment, "effective_time", None)),
            )
            claimed = LiveSelectedAssetResearch._parse_aware_time(str(claimed_time))
            observed = LiveSelectedAssetResearch._parse_aware_time(str(getattr(observation, "observed_at", None)))
            published = LiveSelectedAssetResearch._parse_aware_time(str(public_time))
            stored_observed = LiveSelectedAssetResearch._parse_aware_time(str(market_row.get("observed_at")))
            run_timezone = ZoneInfo(str(context["run_metadata"]["analysis_timezone"]))
            session_day = date.fromisoformat(str(session_date))
        except (KeyError, TypeError, ValueError, ZoneInfoNotFoundError):
            return None
        cutoff = pinned.astimezone(timezone.utc)
        if (any(item > cutoff for item in (effective, claimed, observed, published, stored_observed))
                or observed != stored_observed
                or session_day > pinned.astimezone(run_timezone).date()
                or claimed.date() != session_day):
            return None
        try:
            stored_value = Decimal(str(market_row.get("value_numeric")))
            selected_value = Decimal(str(getattr(observation, "value", None)))
        except (InvalidOperation, TypeError, ValueError):
            return None
        if (market_row.get("instrument_id") != spec.instrument_id
                or market_row.get("currency") != spec.currency
                or market_row.get("unit") != getattr(observation, "unit", None)
                or market_row.get("observation_id") != getattr(selected, "observation_id", None)
                or market_row.get("provider_id") != getattr(observation, "provider_id", None)
                or not stored_value.is_finite() or stored_value != selected_value
                or market_row.get("freshness_status") != FreshnessStatus.LAST_VALID_CLOSE.value
                or market_row.get("claimed_market_time") != claimed_time
                or market_row.get("market_session_date") != session_date
                or freshness_row.get("status") != FreshnessStatus.LAST_VALID_CLOSE.value
                or not isinstance(details, dict)
                or details.get("market_session_date") != session_date
                or details.get("effective_time") != getattr(assessment, "effective_time", None)
                or details.get("quote_kind") != getattr(assessment, "quote_kind", None)
                or details.get("calendar_id") != calendar_id
                or details.get("public_available_time") != public_time
                or not all(isinstance(item, str) and item for item in (session_date, claimed_time, calendar_id, public_time))):
            return None
        return (
            f"가격 입력 기준: {session_date} 마지막 유효 거래일 종가 ({spec.currency}); "
            f"종가 시각 {claimed_time}; 공개시각 {public_time}; 달력 {calendar_id}. 실시간 시세가 아닙니다."
        )

    @staticmethod
    def _parse_aware_time(value: str) -> datetime:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("timestamp is required")
        normalized = value.strip()
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        return parsed

    @staticmethod
    def _serialize_analysis_result(result: object) -> dict[str, object]:
        metadata = dict(getattr(result, "metadata", {}))
        metadata.pop("calculation_id", None)
        metrics = []
        for metric in getattr(result, "metrics", ()):
            value = getattr(metric, "value", None)
            status = getattr(getattr(metric, "status", None), "value", None)
            metrics.append({
                "name": getattr(metric, "name", None),
                "value": LiveSelectedAssetResearch._jsonable(value),
                "unit": getattr(metric, "unit", None),
                "formula": getattr(metric, "formula", None),
                "status": status,
                "reason": getattr(metric, "reason", None),
                "evidence_ids": list(getattr(metric, "evidence_ids", ())),
            })
        return {
            "analysis_type": getattr(result, "analysis_type", None),
            "findings": list(getattr(result, "findings", ())),
            "metadata": LiveSelectedAssetResearch._jsonable(metadata),
            "metrics": metrics,
            "risks": list(getattr(result, "risks", ())),
            "status": getattr(getattr(result, "status", None), "value", None),
            "subject": getattr(result, "subject", None),
            "unknowns": list(getattr(result, "unknowns", ())),
        }

    @staticmethod
    def _jsonable(value: object) -> object:
        if isinstance(value, Mapping):
            return {str(key): LiveSelectedAssetResearch._jsonable(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [LiveSelectedAssetResearch._jsonable(item) for item in value]
        if isinstance(value, str) or value is None or isinstance(value, (int, bool)):
            return value
        if hasattr(value, "value") and isinstance(getattr(value, "value"), str):
            return getattr(value, "value")
        if isinstance(value, Decimal):
            return str(value)
        return value

    @staticmethod
    def _display_metric_name(metric_name: str) -> str:
        labels = {
            "current_ratio": "유동비율",
            "free_cash_flow": "영업현금흐름에서 자본적지출을 뺀 값",
            "free_cash_flow_margin": "영업현금흐름-자본적지출 마진",
            "revenue_growth": "매출 성장률",
            "roe": "자기자본이익률", "roic": "투하자본이익률", "dcf_value_per_share": "DCF 주당 평가 참고값",
            "ev_to_ebitda": "기업가치 대비 EBITDA", "pb": "주가순자산비율",
            "pe": "주가수익비율", "price_to_sales": "매출 대비 시가총액",
            "dividend_yield": "배당수익률", "sotp_explicit_value": "사업부 합산 평가 참고값",
            "net_asset_value": "순자산 평가 참고값", "high_growth_scenario": "고성장 시나리오 평가 참고값",
        }
        if metric_name.startswith("dcf_scenario_"):
            scenario = metric_name.removeprefix("dcf_scenario_")
            scenario_label = {"conservative": "보수", "base": "기준", "optimistic": "낙관"}.get(scenario, "조건부")
            return f"DCF {scenario_label} 시나리오 주당 평가 참고값"
        if metric_name.startswith("dcf_sensitivity_"):
            return "DCF 민감도 분석 평가 참고값"
        if metric_name.startswith("scenario_"):
            return "고성장 시나리오 평가 참고값"
        return labels.get(metric_name, "평가 지표")
