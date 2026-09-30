"""Explicit host composition for the seven fixed request modes.

The host opens only the run workspace and personal database paths the caller
supplies. It does not search for a personal database, call a live provider, or
post an order.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from investment_stack.asset_analysis import Phase5AssetAnalysisRuntime
from investment_stack.deep_research import LiveDeepResearchRuntime
from investment_stack.decisions.policy_b_market import load_policy_b_market_evidence
from investment_stack.evidence import EvidenceResearchStore, RunDatabaseManager
from investment_stack.execution.analysis_modes import equity_analysis_services
from investment_stack.execution.dispatcher import RuntimeServices
from investment_stack.execution.models import ModeRequest
from investment_stack.execution.portfolio_thesis_modes import (
    SelectedAssetResearchResult,
    portfolio_thesis_services,
)
from investment_stack.execution.service_composition import compose_seven_mode_services
from investment_stack.materiality import MaterialityConfig, MaterialityEngine
from investment_stack.personal.ledger import PersonalLedgerService
from investment_stack.personal.manager import PersonalDatabaseManager
from investment_stack.providers.credentials import EnvironmentCredentials
from investment_stack.providers.factory import build_default_provider_executor
from investment_stack.reporting.models import Availability, ReportSectionInput
from investment_stack.reporting.portfolio_modes import (
    MoneyBalance,
    PinnedPortfolioState,
    PortfolioAnalysisRequest,
    PortfolioPosition,
)
from investment_stack.reporting.runtime import Phase6ReportReviewRuntime
from investment_stack.research import Phase4ResearchRuntime


def _refuse_live_fetch(url: str, headers: dict[str, str], timeout: float) -> bytes:
    del url, headers, timeout
    raise RuntimeError("configured host does not call live providers")


def open_personal_ledger(personal_db: Path) -> PersonalLedgerService:
    manager = PersonalDatabaseManager(
        personal_db, backup_directory=personal_db.parent / "backups",
    )
    started = manager.startup()
    if started.status.value != "VALID":
        raise ValueError(started.reason or "personal database is not valid for read-only host use")
    return PersonalLedgerService(manager)


def open_run_database(run_workspace: Path, run_id: str) -> RunDatabaseManager:
    run = RunDatabaseManager(run_workspace, run_id)
    report = run.open()
    if not report.valid:
        raise ValueError("run database is not valid")
    return run


def _posted_portfolio_request(run: RunDatabaseManager, ledger: PersonalLedgerService, request: ModeRequest) -> PortfolioAnalysisRequest | None:
    currency = str(request.payload.get("evaluation_currency") or "").strip().upper()
    if request.payload.get("portfolio_source") != "pinned_ledger" or not currency:
        value = request.payload.get("portfolio_request")
        return value if isinstance(value, PortfolioAnalysisRequest) else None
    context = run.fetch_phase6_context()
    pin = context.get("pinned_personal_state")
    metadata = context.get("run_metadata")
    if not isinstance(pin, dict) or not isinstance(metadata, dict):
        return None
    verified = ledger.get_verified_portfolio_snapshot_projection(
        expected_personal_db_instance_id=pin.get("personal_db_instance_id"),
        expected_state_version=pin.get("state_version"),
        expected_snapshot_id=pin.get("portfolio_snapshot_id"),
        expected_data_as_of=pin.get("portfolio_data_as_of"),
    )
    as_of = str(metadata.get("analysis_as_of") or "")
    positions = []
    for position in verified.projection.positions:
        if position.quantity == 0:
            continue
        market = load_policy_b_market_evidence(
            run.database_path, run_id=run.run_id, instrument_id=position.instrument_id, as_of=as_of,
        )
        quote = market.quote_per_share
        market_value = None
        reason = "verified quote unavailable"
        if quote is not None and quote.verified and quote.currency.upper() == currency:
            market_value = position.quantity * quote.amount
            reason = None
        positions.append(PortfolioPosition(
            position.instrument_id, market_value, currency, unvalued_reason=reason,
        ))
    cash = tuple(
        MoneyBalance(
            balance.account_id,
            balance.balance if balance.currency.upper() == currency else None,
            currency,
            None if balance.currency.upper() == currency else "FX conversion is not verified",
        )
        for balance in verified.projection.cash_balances
    )
    liabilities = tuple(
        MoneyBalance(
            balance.liability_id,
            balance.principal if balance.currency.upper() == currency else None,
            currency,
            None if balance.currency.upper() == currency else "FX conversion is not verified",
        )
        for balance in verified.projection.liabilities
    )
    return PortfolioAnalysisRequest(
        PinnedPortfolioState(
            verified.state_version, verified.snapshot_id, as_of, verified.data_as_of,
        ),
        currency, tuple(positions), cash, liabilities,
    )


def compose_configured_host(run: RunDatabaseManager, ledger: PersonalLedgerService) -> RuntimeServices:
    """Compose all seven modes around one explicit run database and ledger."""
    metadata = run.fetch_phase6_context()["run_metadata"]
    providers = build_default_provider_executor(
        credentials=EnvironmentCredentials({}), transport=_refuse_live_fetch,
    )
    research = Phase4ResearchRuntime(providers=providers, evidence=EvidenceResearchStore(run))
    analysis = Phase5AssetAnalysisRuntime(
        run, materiality=MaterialityEngine(MaterialityConfig(
            "host-posted-positions", Decimal("1"), Decimal("1"), Decimal("1"),
        )),
    )
    deep = LiveDeepResearchRuntime(
        research=research, analysis=analysis,
        analysis_as_of=str(metadata["analysis_as_of"]),
        analysis_timezone=str(metadata["analysis_timezone"]),
    )
    equity = equity_analysis_services(
        deep_research=deep, phase6=Phase6ReportReviewRuntime(run), run_db=run,
    )

    def research_selected(ids: tuple[str, ...], _request: ModeRequest) -> SelectedAssetResearchResult:
        missing = tuple(f"{item}:persisted_research" for item in ids) or ("selected_assets",)
        return SelectedAssetResearchResult(
            (ReportSectionInput(
                "selected_asset_research", "선택 자산",
                ("저장된 실행 근거만 사용합니다. 주문은 생성하지 않습니다.",),
                status=Availability.PARTIAL,
            ),),
            missing_inputs=missing,
        )

    portfolio = portfolio_thesis_services(
        run_db=run,
        base_services=equity,
        personal_ledger=ledger,
        portfolio_loader=lambda request: _posted_portfolio_request(run, ledger, request),
        materiality_selector=lambda portfolio_request, _request: tuple(
            position.instrument_id for position in portfolio_request.positions
        ),
        selected_asset_research=research_selected,
    )
    return compose_seven_mode_services(
        run_db=run, ledger=ledger, equity_services=equity, portfolio_thesis_services=portfolio,
    )


def open_configured_host(run_workspace: Path, run_id: str, personal_db: Path) -> RuntimeServices:
    return compose_configured_host(
        open_run_database(run_workspace, run_id), open_personal_ledger(personal_db),
    )
