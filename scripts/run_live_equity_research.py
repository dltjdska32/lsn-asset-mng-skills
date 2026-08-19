"""Run one evidence-backed equity deep research job from a structured web bundle.

This helper is intended for Codex/local tool use: external search is performed by
Codex, structured hits are written to JSON, and this script forces those facts
through the investment-stack freshness/evidence/calculation runtime.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from investment_stack.asset_analysis import Phase5AssetAnalysisRuntime
from investment_stack.calculations import BusinessType
from investment_stack.deep_research import EquityResearchSpec, LiveDeepResearchRuntime
from investment_stack.evidence import EvidenceResearchStore, RunDatabaseManager
from investment_stack.materiality import MaterialityEngine, load_materiality_config
from investment_stack.providers import build_default_provider_executor
from investment_stack.research import Phase4ResearchRuntime
from investment_stack.web_research import WebResearchAdapter, WebResearchBundleBackend


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--project-root", type=Path, default=Path.cwd())
    result.add_argument("--workspace", type=Path)
    result.add_argument("--run-id", required=True)
    result.add_argument("--analysis-as-of", required=True)
    result.add_argument("--timezone", required=True)
    result.add_argument("--spec", type=Path, required=True)
    result.add_argument("--research-bundle", type=Path, required=True)
    return result


def main() -> int:
    args = parser().parse_args()
    project_root = args.project_root.resolve()
    workspace = (args.workspace or (project_root / "workspace")).resolve()
    spec_data = json.loads(args.spec.read_text(encoding="utf-8"))
    if not isinstance(spec_data, dict):
        raise ValueError("spec root must be a JSON object")

    run = RunDatabaseManager(workspace, args.run_id)
    report = run.create()
    if not report.valid:
        raise RuntimeError("failed to create run database: " + "; ".join(report.errors))
    run.initialize_run_context(
        request_mode="SINGLE_ASSET_ANALYSIS",
        analysis_as_of=args.analysis_as_of,
        analysis_timezone=args.timezone,
        state_version=0,
        personal_db_instance_id="NONE:LIVE_RESEARCH",
    )
    run.update_metadata(
        run_status="RUNNING",
        request_mode="SINGLE_ASSET_ANALYSIS",
        metadata={"source": "structured_web_research_bundle"},
    )

    web = WebResearchAdapter(WebResearchBundleBackend.from_json_file(args.research_bundle))
    research = Phase4ResearchRuntime(
        providers=build_default_provider_executor(),
        evidence=EvidenceResearchStore(run),
        web_research=web,
    )
    phase5 = Phase5AssetAnalysisRuntime(
        run,
        materiality=MaterialityEngine(load_materiality_config(project_root / "config" / "materiality.yaml")),
    )
    live = LiveDeepResearchRuntime(
        research=research,
        analysis=phase5,
        analysis_as_of=args.analysis_as_of,
        analysis_timezone=args.timezone,
    )
    spec = EquityResearchSpec(
        instrument_id=str(spec_data["instrument_id"]),
        display_name=str(spec_data.get("display_name") or spec_data["instrument_id"]),
        country=str(spec_data["country"]),
        currency=str(spec_data["currency"]),
        business_type=BusinessType(str(spec_data.get("business_type", BusinessType.STABLE_CASH_FLOW.value))),
        ticker=None if spec_data.get("ticker") is None else str(spec_data.get("ticker")),
        market_query=None if spec_data.get("market_query") is None else str(spec_data.get("market_query")),
        fundamentals_query=None if spec_data.get("fundamentals_query") is None else str(spec_data.get("fundamentals_query")),
        news_query=None if spec_data.get("news_query") is None else str(spec_data.get("news_query")),
        market_parameters=dict(spec_data.get("market_parameters") or {}),
        fundamentals_parameters=dict(spec_data.get("fundamentals_parameters") or {}),
    )
    outcome = live.analyze_equity(spec)
    run.update_metadata(
        run_status="PARTIAL" if outcome.market.selected.observation is None or not outcome.normalized_metrics else "COMPLETE",
        request_mode="SINGLE_ASSET_ANALYSIS",
        metadata={"source": "structured_web_research_bundle", "instrument_id": spec.instrument_id},
    )
    context = run.fetch_phase6_context()
    payload = {
        "run_id": run.run_id,
        "run_db": str(run.database_path),
        "instrument_id": spec.instrument_id,
        "market_selected_evidence": outcome.market.selected.evidence_id,
        "financial_selected_count": len([
            row for row in context["evidence"]
            if row.get("instrument_id") == spec.instrument_id
            and row.get("evidence_type") == "financial"
            and row.get("selection_state") == "SELECTED"
        ]),
        "normalized_metrics": {key: str(value) for key, value in outcome.normalized_metrics.items()},
        "fundamental_status": outcome.analysis.fundamental.status.value,
        "valuation_status": outcome.analysis.valuation.status.value,
        "fundamental_calculation_id": outcome.analysis.fundamental.metadata.get("calculation_id"),
        "valuation_calculation_id": outcome.analysis.valuation.metadata.get("calculation_id"),
        "provider_states": [
            {"provider": row["provider_name"], "capability": row.get("capability"), "status": row["provider_status"]}
            for row in context["provider_states"]
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
