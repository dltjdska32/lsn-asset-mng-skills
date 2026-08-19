"""Execute the supplied 2026-08-14 portfolio snapshot in a fresh auditable run."""

from __future__ import annotations

import hashlib
import json
import sys
from decimal import Decimal
from pathlib import Path

from investment_stack.asset_analysis import Phase5AssetAnalysisRuntime
from investment_stack.calculations import (
    BusinessType,
    AssetRiskInput,
    PortfolioReconciliationInput,
    PositionExposure,
    ReconciliationStatus,
    load_reconciliation_config,
    reconcile_portfolio_total,
)
from investment_stack.deep_research import EquityResearchSpec, LiveDeepResearchRuntime
from investment_stack.evidence import EvidenceResearchStore, RunDatabaseManager
from investment_stack.materiality import LightweightAsset, MaterialityEngine, load_materiality_config
from investment_stack.providers import build_default_provider_executor
from investment_stack.research import Phase4ResearchRuntime
from investment_stack.reporting import Availability, Confidence, ReportSectionInput
from investment_stack.reporting.runtime import Phase6ReportReviewRuntime
from investment_stack.review.models import ReviewContext
from investment_stack.web_research import WebResearchAdapter, WebResearchBundleBackend


D = Decimal
ANALYSIS_AS_OF = "2026-08-14T09:42:00+09:00"
PIPELINE = (
    "pin_personal_state",
    "lightweight_all_assets",
    "apply_materiality_gate",
    "deep_research_selected_assets",
    "calculate_allocation_and_risk",
    "conditional_review",
    "render_partial_aware_report",
)
IMAGES = (
    Path(r"C:\Users\dltjd\Documents\카카오톡 받은 파일\KakaoTalk_20260814_094301683.jpg"),
    Path(r"C:\Users\dltjd\Documents\카카오톡 받은 파일\KakaoTalk_20260814_094301683_01.jpg"),
    Path(r"C:\Users\dltjd\Documents\카카오톡 받은 파일\KakaoTalk_20260814_094301683_02.jpg"),
    Path(r"C:\Users\dltjd\Documents\카카오톡 받은 파일\KakaoTalk_20260814_094301683_03.jpg"),
)
HOLDINGS = (
    ("FANUC", "6954", D("7"), D("407710"), "EQUITY", "JAPAN", "JPY", "FACTORY_AUTOMATION", D("-3.04"), True),
    ("MITSUBISHI_HEAVY", "7011", D("4"), D("151449"), "EQUITY", "JAPAN", "JPY", "SHIPBUILDING_DEFENSE", D("10.08"), True),
    ("HANWHA_OCEAN", "042660", D("1"), D("95400"), "EQUITY", "KOREA", "KRW", "SHIPBUILDING_DEFENSE", D("13.71"), False),
    ("SAMSUNG_HEAVY", "010140", D("2"), D("44700"), "EQUITY", "KOREA", "KRW", "SHIPBUILDING_DEFENSE", D("5.18"), False),
    ("HMM", "011200", D("2"), D("42000"), "EQUITY", "KOREA", "KRW", "SHIPPING", D("1.45"), False),
    ("HYUNDAI_MOVEX", "319400", D("1"), D("29100"), "EQUITY", "KOREA", "KRW", "LOGISTICS_AUTOMATION", D("34.41"), False),
    ("KOREAN_AIR", "003490", D("1"), D("26400"), "EQUITY", "KOREA", "KRW", "AIRLINE", D("-0.75"), False),
    ("POSCO_DX", "022100", D("1"), D("22100"), "EQUITY", "KOREA", "KRW", "INDUSTRIAL_DIGITALIZATION", D("17.05"), False),
)
CASH = (
    ("JPY_CASH", D("15677"), D("139106"), "JPY"),
    ("USD_CASH", D("144"), D("204707"), "USD"),
)


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def execute(project_root: Path, run_id: str, research_bundle: Path | None = None) -> Path:
    workspace = project_root / "workspace"
    manager = RunDatabaseManager(workspace, run_id)
    manager.create()
    manager.initialize_run_context(
        request_mode="PERSONAL_PORTFOLIO_ANALYSIS",
        analysis_as_of=ANALYSIS_AS_OF,
        analysis_timezone="Asia/Seoul",
        state_version=0,
        personal_db_instance_id="NONE:USER_PROVIDED_SNAPSHOT",
        portfolio_snapshot_id="USER_PROVIDED_SNAPSHOT-v1",
        portfolio_data_as_of=ANALYSIS_AS_OF,
    )
    manager.update_metadata(
        run_status="RUNNING",
        request_mode="PERSONAL_PORTFOLIO_ANALYSIS",
        metadata={"pipeline": list(PIPELINE), "source": "USER_PROVIDED_SNAPSHOT"},
    )
    manager.record_task_state(task_name=PIPELINE[0], task_status="COMPLETED", metadata={"state_version": 0})

    evidence_ids: list[str] = []
    for index, image in enumerate(IMAGES, start=1):
        evidence_id = f"evidence:screenshot:{index}"
        evidence_ids.append(evidence_id)
        manager.add_phase4_evidence(
            evidence_id=evidence_id,
            evidence_type="portfolio_snapshot",
            source_uri=str(image),
            retrieved_at=ANALYSIS_AS_OF,
            source_name="NH Investment screenshot supplied by user",
            source_tier=1,
            observed_at=ANALYSIS_AS_OF,
            freshness_status="UNKNOWN",
            provider_id="user-provided-snapshot",
            official_confirmation_status="USER_PROVIDED",
            relevance_reason="portfolio holdings and balance observation",
            metadata={"sha256": _hash(image), "authoritative_current_price": False},
        )
        manager.mark_evidence_selected(evidence_id=evidence_id, reason="selected as user-provided portfolio snapshot")
        manager.add_freshness_assessment(
            freshness_id=f"freshness:screenshot:{index}",
            evidence_id=evidence_id,
            status="UNKNOWN",
            details={"reason": "screenshot observation is not authoritative current market data"},
        )
    manager.record_provider_state(
        provider_name="user-provided-snapshot",
        provider_status="AVAILABLE",
        capability="portfolio_state",
    )
    if research_bundle is None:
        manager.record_provider_state(
            provider_name="authoritative-market-data",
            provider_status="UNAVAILABLE",
            capability="current_price",
            error_reason="structured live research bundle not supplied",
        )

    for index, row in enumerate(HOLDINGS, start=1):
        instrument_id, ticker, quantity, value, *_ = row
        manager.add_market_observation(
            observation_id=f"obs:holding:{index}",
            evidence_id=evidence_ids[3],
            instrument_id=instrument_id,
            observed_at=ANALYSIS_AS_OF,
            value=str(value),
            unit="KRW_EVALUATION_VALUE",
            currency="KRW",
            claimed_market_time=None,
            market_session_date="2026-08-14",
            provider_id="user-provided-snapshot",
            freshness_status="UNKNOWN",
            metadata={
                "ticker": ticker,
                "quantity": str(quantity),
                "pnl_rate_percent": str(row[8]),
                "asset_class": row[4],
                "country": row[5],
                "economic_currency": row[6],
                "sector": row[7],
                "authoritative_current_price": False,
            },
        )
        manager.add_observation_selection(
            selection_id=f"selection:holding:{index}",
            observation_id=f"obs:holding:{index}",
            selection_reason="selected as portfolio component value, not current price",
        )

    reconciliation = reconcile_portfolio_total(
        PortfolioReconciliationInput(
            reported_total=D("1046450"),
            group_totals={"stocks": D("817062"), "cash": D("343971")},
            group_components={
                "stocks": tuple(row[3] for row in HOLDINGS),
                "cash": tuple(row[2] for row in CASH),
            },
        ),
        load_reconciliation_config(project_root / "config" / "reconciliation.yaml"),
    )
    reconciliation_id = "calc:portfolio-reconciliation"
    manager.add_calculation(
        calculation_id=reconciliation_id,
        calculation_name="portfolio_total_reconciliation",
        formula="reported_total_vs_non_overlapping_group_totals",
        inputs={"evidence_ids": evidence_ids, "reported_total": "1046450"},
        result={
            "status": reconciliation.status.value,
            "authoritative_total": reconciliation.authoritative_total,
            "confirmed_group_total": reconciliation.confirmed_group_total,
            "naive_component_total": reconciliation.naive_component_total,
            "reported_difference": reconciliation.reported_difference,
            "group_differences": reconciliation.group_differences,
            "reasons": reconciliation.reasons,
            "config_version": reconciliation.config_version,
        },
    )
    if reconciliation.status is ReconciliationStatus.UNRESOLVED:
        manager.add_conflict(
            conflict_id="conflict:portfolio-total",
            conflict_type="PORTFOLIO_RECONCILIATION",
            status="OPEN",
            details={"calculation_id": reconciliation_id, "reasons": reconciliation.reasons},
        )

    holdings_payload = [
        {
            "instrument_id": row[0], "ticker": row[1], "quantity": row[2],
            "value_krw": row[3], "asset_class": row[4], "country": row[5],
            "currency": row[6], "sector": row[7], "pnl_rate_percent": row[8],
        }
        for row in HOLDINGS
    ]
    cash_payload = [
        {"instrument_id": row[0], "native_balance": row[1], "value_krw": row[2], "currency": row[3]}
        for row in CASH
    ]
    japanese_equity = sum((row[3] for row in HOLDINGS if row[5] == "JAPAN"), D("0"))
    korean_equity = sum((row[3] for row in HOLDINGS if row[5] == "KOREA"), D("0"))
    jpy_cash = next(row[2] for row in CASH if row[3] == "JPY")
    usd_cash = next(row[2] for row in CASH if row[3] == "USD")
    fanuc = next(row[3] for row in HOLDINGS if row[0] == "FANUC")
    shipbuilding = sum((row[3] for row in HOLDINGS if row[7] == "SHIPBUILDING_DEFENSE"), D("0"))
    automation = sum((row[3] for row in HOLDINGS if row[7] in {"FACTORY_AUTOMATION", "LOGISTICS_AUTOMATION", "INDUSTRIAL_DIGITALIZATION"}), D("0"))
    components_id = "calc:confirmed-components-and-scenarios"
    manager.add_calculation(
        calculation_id=components_id,
        calculation_name="confirmed_components_and_absolute_scenarios",
        formula="deterministic_absolute_exposure_without_total_denominator",
        inputs={"evidence_ids": evidence_ids, "reconciliation_id": reconciliation_id},
        result={
            "status": "PARTIAL",
            "percentage_impacts_status": "PARTIAL",
            "holdings": holdings_payload,
            "cash": cash_payload,
            "stock_group_total_krw": D("817062"),
            "cash_group_total_krw": D("343971"),
            "currency_exposure_krw": {"JPY": japanese_equity + jpy_cash, "KRW": korean_equity, "USD": usd_cash},
            "country_equity_exposure_krw": {"JAPAN": japanese_equity, "KOREA": korean_equity},
            "exclusive_sector_exposure_krw": {
                "FACTORY_AUTOMATION": fanuc,
                "SHIPBUILDING_DEFENSE": shipbuilding,
                "SHIPPING": D("42000"),
                "LOGISTICS_AUTOMATION": D("29100"),
                "AIRLINE": D("26400"),
                "INDUSTRIAL_DIGITALIZATION": D("22100"),
                "CASH_COMPONENTS": jpy_cash + usd_cash,
            },
            "overlapping_theme_exposure_krw": {"AUTOMATION": automation, "SHIPBUILDING_DEFENSE": shipbuilding},
            "concentration_exposure_krw": {
                "FANUC": fanuc,
                "JAPAN_EQUITY": japanese_equity,
                "JPY": japanese_equity + jpy_cash,
                "AUTOMATION": automation,
                "SHIPBUILDING_DEFENSE": shipbuilding,
            },
            "scenarios": [
                {"name": "JPY +10%", "impact_krw": (japanese_equity + jpy_cash) * D("0.10"), "largest_contributor": "FANUC"},
                {"name": "JPY -10%", "impact_krw": (japanese_equity + jpy_cash) * D("-0.10"), "largest_contributor": "FANUC"},
                {"name": "FANUC +20%", "impact_krw": fanuc * D("0.20"), "largest_contributor": "FANUC"},
                {"name": "FANUC -20%", "impact_krw": fanuc * D("-0.20"), "largest_contributor": "FANUC"},
                {"name": "조선/방산 -15%", "impact_krw": shipbuilding * D("-0.15"), "largest_contributor": "MITSUBISHI_HEAVY"},
                {"name": "한국주식 -10%", "impact_krw": korean_equity * D("-0.10"), "largest_contributor": "HANWHA_OCEAN"},
                {"name": "일본주식 -10%", "impact_krw": japanese_equity * D("-0.10"), "largest_contributor": "FANUC"},
            ],
        },
    )

    manager.record_task_state(task_name=PIPELINE[1], task_status="COMPLETED", metadata={"assets": len(HOLDINGS) + len(CASH)})
    materiality = MaterialityEngine(load_materiality_config(project_root / "config" / "materiality.yaml"))
    lightweight = tuple(
        LightweightAsset(
            instrument_id=row[0],
            confirmed_quantity=row[2],
            valued_weight=None,
            liquidity_score=None,
            risk_proxy=None,
            data_uncertainty=D("0.90"),
            user_specified=row[9],
            strategic_relevance=False,
        )
        for row in HOLDINGS
    )
    exposures = tuple(
        PositionExposure(
            row[0], row[3], account="NH_CMA", asset_class=row[4], country=row[5],
            currency=row[6], sector=row[7], liquidity="UNKNOWN", custody="NH_INVESTMENT",
        )
        for row in HOLDINGS
    ) + tuple(
        PositionExposure(
            row[0], row[2], account="NH_CMA", asset_class="CASH", country=None,
            currency=row[3], sector="CASH", liquidity="HIGH", custody="NH_INVESTMENT",
        )
        for row in CASH
    )
    phase5_runtime = Phase5AssetAnalysisRuntime(manager, materiality=materiality)
    deep_analyzers: dict[str, object] = {}
    if research_bundle is not None:
        web_backend = WebResearchBundleBackend.from_json_file(research_bundle)
        phase4 = Phase4ResearchRuntime(
            providers=build_default_provider_executor(),
            evidence=EvidenceResearchStore(manager),
            web_research=WebResearchAdapter(web_backend),
        )
        live = LiveDeepResearchRuntime(
            research=phase4,
            analysis=phase5_runtime,
            analysis_as_of=ANALYSIS_AS_OF,
            analysis_timezone="Asia/Seoul",
        )
        for row in HOLDINGS:
            instrument_id, ticker, _, _, _, country, currency, _, _, _ = row
            spec = EquityResearchSpec(
                instrument_id=instrument_id,
                display_name=instrument_id.replace("_", " "),
                ticker=ticker,
                country=country,
                currency=currency,
                business_type=BusinessType.STABLE_CASH_FLOW,
                news_query=f"{instrument_id.replace('_', ' ')} {ticker} latest relevant official news",
            )
            deep_analyzers[instrument_id] = live.equity_callback(spec)

    phase5 = phase5_runtime.analyze_portfolio(
        lightweight_assets=lightweight,
        exposures=exposures,
        risk_assets=tuple(),
        deep_analyzers=deep_analyzers,
        allocation_denominator=None,
        denominator_resolved=False,
        calculation_evidence_ids=tuple(evidence_ids),
    )
    manager.record_task_state(task_name=PIPELINE[2], task_status="COMPLETED", metadata={"config_version": materiality.config.version})
    researched = len(phase5.deep_results)
    selected = sum(item.decision.value != "FAIL" for item in phase5.materiality)
    manager.record_task_state(
        task_name=PIPELINE[3],
        task_status="COMPLETED" if researched and researched == selected else "PARTIAL",
        metadata={
            "selected_assets": selected,
            "executed_deep_research": researched,
            "structured_research_bundle": research_bundle is not None,
        },
    )
    manager.record_task_state(task_name=PIPELINE[4], task_status="PARTIAL", metadata={"reconciliation": reconciliation.status.value})

    context = manager.fetch_phase6_context()
    portfolio_calc_ids = tuple(row["calculation_id"] for row in context["calculations"])
    deep_lines: list[str] = []
    deep_evidence: list[str] = []
    deep_calculations: list[str] = []
    for instrument_id, outcome in sorted(phase5.deep_results.items()):
        if hasattr(outcome, "analysis"):
            valuation = outcome.analysis.valuation
            deep_lines.append(f"{instrument_id}: valuation {valuation.status.value}; normalized metrics={len(outcome.normalized_metrics)}")
            deep_evidence.extend(outcome.evidence_ids)
            calculation_id = valuation.metadata.get("calculation_id")
            if calculation_id:
                deep_calculations.append(str(calculation_id))
    valuation_status = Availability.PARTIAL if deep_lines else Availability.UNAVAILABLE
    if not deep_lines:
        deep_lines = ["VALUATION DATA UNAVAILABLE"]

    report_runtime = Phase6ReportReviewRuntime(manager)
    phase6 = report_runtime.generate(
        title="Verified Personal Portfolio Snapshot",
        sections=(
            ReportSectionInput(
                "portfolio_snapshot",
                "Portfolio Snapshot",
                (
                    "Portfolio Total: UNRESOLVED",
                    "Stock group total: 817062 KRW (screen observation)",
                    "Cash group total: 343971 KRW (screen observation)",
                    "Total-based weights and scenario percentages: PARTIAL",
                ),
                status=Availability.PARTIAL,
                evidence_ids=tuple(evidence_ids),
                calculation_ids=portfolio_calc_ids,
                metadata={"reconciliation": reconciliation.status.value},
            ),
            ReportSectionInput(
                "valuation",
                "Valuation",
                tuple(deep_lines),
                status=valuation_status,
                evidence_ids=tuple(dict.fromkeys(deep_evidence)),
                calculation_ids=tuple(dict.fromkeys(deep_calculations)),
            ),
        ),
        review_context=ReviewContext(
            critical_evidence_ids=tuple(evidence_ids),
            high_materiality=True,
            requested_confidence=Confidence.LOW,
        ),
    )
    manager.record_task_state(task_name=PIPELINE[5], task_status="COMPLETED", metadata={"findings": len(phase6.review.findings)})
    manager.record_task_state(task_name=PIPELINE[6], task_status="COMPLETED", metadata={"availability": phase6.report.availability.value})
    manager.update_metadata(
        run_status="COMPLETED",
        request_mode="PERSONAL_PORTFOLIO_ANALYSIS",
        metadata={
            "pipeline": list(PIPELINE),
            "source": "USER_PROVIDED_SNAPSHOT",
            "report_availability": phase6.report.availability.value,
        },
    )
    report_directory = manager.database_path.parent / "report"
    report_directory.mkdir(parents=True, exist_ok=True)
    (report_directory / "report.md").write_text(phase6.report.markdown, encoding="utf-8")
    summary = {
        "run_id": run_id,
        "run_db": str(manager.database_path),
        "reconciliation": reconciliation.status.value,
        "report": str(report_directory / "report.md"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return manager.database_path


if __name__ == "__main__":
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    if len(sys.argv) < 3:
        raise SystemExit("usage: replay_portfolio_snapshot.py PROJECT_ROOT RUN_ID [RESEARCH_BUNDLE.json]")
    bundle = Path(sys.argv[3]).resolve() if len(sys.argv) >= 4 else None
    execute(root, sys.argv[2], bundle)
