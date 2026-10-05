"""Explicit host composition for the seven fixed request modes.

The host opens only the run workspace and personal database paths the caller
supplies. It does not search for a personal database, call a live provider, or
post an order.
"""

from __future__ import annotations
from contextlib import closing

from decimal import Decimal
from datetime import datetime, timedelta
from dataclasses import replace
from investment_stack.providers.http import urllib_transport
from investment_stack.execution.portfolio_evidence import PortfolioEvidence
from investment_stack.providers.instruments import InstrumentResolver
from pathlib import Path

from investment_stack.asset_analysis import Phase5AssetAnalysisRuntime
from investment_stack.calculations import BusinessType
from investment_stack.deep_research import EquityResearchSpec
from investment_stack.deep_research import LiveDeepResearchRuntime
from investment_stack.decisions.policy_b_market import load_policy_b_market_evidence
from investment_stack.evidence import EvidenceResearchStore, RunDatabaseManager
from investment_stack.execution.analysis_modes import equity_analysis_services
from investment_stack.execution.dispatcher import RuntimeServices
from investment_stack.execution.models import ModeRequest
from investment_stack.execution.selected_asset_research import LiveSelectedAssetResearch
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
from investment_stack.web_research import WebResearchAdapter, WebResearchBundleBackend


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


def _posted_portfolio_request(run: RunDatabaseManager, ledger: PersonalLedgerService, request: ModeRequest, live: PortfolioEvidence | None = None) -> PortfolioAnalysisRequest | None:
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
        selected = live.quotes.get(position.instrument_id) if live else None
        quote = selected.observation if selected else None
        market_value = position.quantity * Decimal(str(quote.value)) if quote and quote.currency == position.currency.upper() else None
        reason = None if market_value is not None else "verified quote unavailable"
        info = live.instruments.get(position.instrument_id, {}) if live else {}
        positions.append(PortfolioPosition(
            position.instrument_id, market_value, position.currency.upper(),
            asset_class=info.get('asset_class'), account=position.account_id,
            unvalued_reason=reason,
        ))
    def cash_balance(balance):
        amount, reason = balance.balance, None
        if live and live.snapshot.get('cash_details'):
            details=live.snapshot['cash_details'].get(balance.account_id+'_'+balance.currency, {})
            try:
                declared=Decimal(str(details['deposit']))
                cutoff=datetime.fromisoformat(as_of.replace('Z','+00:00'))
                observed=datetime.fromisoformat(str(live.snapshot['data_as_of']).replace('Z','+00:00'))
                valid=(declared.is_finite() and declared == amount
                    and live.snapshot['state_version'] == verified.state_version
                    and timedelta(0) <= cutoff-observed <= timedelta(days=1))
            except (KeyError,ValueError,TypeError,ArithmeticError):
                valid=False
            if not valid:
                amount, reason=None, 'cash snapshot/ledger reconciliation unverified'
        return MoneyBalance(f"{balance.account_id}:{balance.currency.upper()}",amount,balance.currency.upper(),reason)
    cash = tuple(cash_balance(balance) for balance in verified.projection.cash_balances)
    # Portfolio exposure is per instrument; ledger P&L stays per account.
    grouped={}
    for position in positions:
        prior=grouped.get(position.instrument_id)
        if prior is None:
            grouped[position.instrument_id]=position
        else:
            if prior.currency != position.currency:
                raise ValueError('same instrument has conflicting ledger currencies')
            combined=(prior.market_value+position.market_value
                      if prior.market_value is not None and position.market_value is not None else None)
            grouped[position.instrument_id]=replace(prior,market_value=combined,
                account='|'.join(sorted(set((prior.account or '').split('|')+[position.account or '']))),
                unvalued_reason=None if combined is not None else 'one or more account quotes unavailable')
    positions=list(grouped.values())
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
        fx_evidence=live.typed_fx() if live else (),
    )


def compose_configured_host(run: RunDatabaseManager, ledger: PersonalLedgerService, *, web_research_bundle: Path | None = None, live_providers: bool = False, transport=None, special_rules=None, include_reference_assets: bool = False, research_all_held: bool = False, instrument_registry: Path | None = None, previous_run_db: Path | None = None) -> RuntimeServices:
    """Compose all seven modes around one explicit run database and ledger."""
    metadata = run.fetch_phase6_context()["run_metadata"]
    context = run.fetch_phase6_context()
    pin = context["pinned_personal_state"]
    verified = ledger.get_verified_portfolio_snapshot_projection(
        expected_personal_db_instance_id=pin["personal_db_instance_id"],
        expected_state_version=pin["state_version"],
        expected_snapshot_id=pin["portfolio_snapshot_id"],
        expected_data_as_of=pin["portfolio_data_as_of"],
    )
    chosen_transport = transport or (urllib_transport if live_providers else _refuse_live_fetch)
    resolver = InstrumentResolver.from_database(ledger.manager.database_path,
        registry_path=instrument_registry, transport=chosen_transport)
    held_ids = tuple(p.instrument_id for p in verified.projection.positions if p.quantity != 0)
    resolved = resolver.portfolio(held_ids) if metadata["request_mode"] in {"PERSONAL_PORTFOLIO_ANALYSIS","THESIS_REVIEW","PORTFOLIO_SCENARIO"} else {}
    listings = {iid: asset.listing_id for iid, asset in resolved.items()}
    providers = build_default_provider_executor(
        credentials=EnvironmentCredentials(), transport=chosen_transport, listings=listings, instrument_resolver=resolver,
    )
    backend = WebResearchBundleBackend.from_json_file(web_research_bundle) if web_research_bundle is not None else None
    if live_providers:
        from investment_stack.web_research.live_news import LiveNewsBackend
        previous_cutoff = None
        seen_articles, seen_events = set(), set()
        if previous_run_db is not None:
            from contextlib import closing
            import sqlite3, json
            with closing(sqlite3.connect(previous_run_db.resolve().as_uri() + '?mode=ro', uri=True)) as prior:
                row = prior.execute('SELECT analysis_as_of,request_mode FROM run_metadata').fetchone()
                if not row or row[1] != metadata['request_mode'] or row[0] >= metadata['analysis_as_of']:
                    raise ValueError('previous run must use the same mode and an earlier pinned clock')
                previous_cutoff = row[0]
                for (raw,) in prior.execute("SELECT metadata_json FROM evidence WHERE evidence_type='news'"):
                    item = json.loads(raw or '{}')
                    if item.get('article_id'): seen_articles.add(item['article_id'])
                    if item.get('event_cluster_id'): seen_events.add(item['event_cluster_id'])
        backend = LiveNewsBackend(resolver, chosen_transport, preferred=backend,
                                  previous_run_as_of=previous_cutoff,
                                  seen_article_ids=seen_articles, seen_event_ids=seen_events)
    web = WebResearchAdapter(backend) if backend is not None else None
    research = Phase4ResearchRuntime(providers=providers, evidence=EvidenceResearchStore(run), web_research=web)
    analysis = Phase5AssetAnalysisRuntime(
        run, materiality=MaterialityEngine(MaterialityConfig(
            "host-posted-positions", Decimal("1"), Decimal("1"), Decimal("1"),
        )),
    )
    live = PortfolioEvidence(run, ledger, research, analysis, special_rules=special_rules)
    live.projection = verified.projection
    live.resolver = resolver
    for iid, reason in resolver.failures.items():
        live.missing.append(iid + ':instrument_resolution:' + reason)
    for iid, asset in resolved.items():
        run.record_task_state(task_name='instrument_resolution:'+iid, task_status='COMPLETE',
            metadata={'listing_id':asset.listing_id,'asset_class':asset.asset_class,
                      'currency':asset.currency,**asset.provenance})
    for iid, reason in resolver.failures.items():
        run.record_task_state(task_name='instrument_resolution:'+iid, task_status='PARTIAL',metadata={'reason':reason})
    deep = LiveDeepResearchRuntime(
        research=research, analysis=analysis,
        analysis_as_of=str(metadata["analysis_as_of"]),
        analysis_timezone=str(metadata["analysis_timezone"]),
    )
    def resolve_request_specs(request):
        requested = resolver.request_specs(request)
        for spec in requested:
            asset = resolver.resolved[spec.instrument_id]
            run.record_task_state(task_name='instrument_resolution:'+asset.instrument_id,
                task_status='COMPLETE', metadata={'listing_id':asset.listing_id,**asset.provenance})
        return requested

    live.held_ids = tuple(dict.fromkeys(p.instrument_id for p in verified.projection.positions if p.quantity != 0))
    def capital_context_loader(request):
        payload={**request.payload,'portfolio_source':'pinned_ledger',
                 'evaluation_currency':request.payload.get('evaluation_currency') or 'KRW'}
        bound_request=ModeRequest(request.run_id,request.mode,payload)
        live.lightweight(bound_request)
        return _posted_portfolio_request(run,ledger,bound_request,live)
    equity = equity_analysis_services(
        deep_research=deep, phase6=Phase6ReportReviewRuntime(run), run_db=run,
        asset_resolver=resolve_request_specs,
        portfolio_context_loader=capital_context_loader,
    )

    specs = {iid: asset.equity_spec() for iid, asset in resolved.items() if asset.asset_class == 'EQUITY'}
    live_selected = LiveSelectedAssetResearch(deep, specs)
    live.held_ids = tuple(p.instrument_id for p in verified.projection.positions if p.quantity != 0)
    live.research_all_held = research_all_held

    def research_selected(ids: tuple[str, ...], request: ModeRequest) -> SelectedAssetResearchResult:
        sections=[]; refs=[]; calcs=[]; missing=[]
        equity_ids = tuple(item for item in ids if item in specs)
        if equity_ids and live_selected:
            result=live_selected(equity_ids, request)
            sections.extend(result.sections); refs.extend(result.evidence_refs); calcs.extend(result.calculation_refs); missing.extend(result.missing_inputs)
        elif equity_ids:
            missing.extend(item+":persisted_research" for item in equity_ids)
        for iid in ids:
            if live.instruments.get(iid,{}).get('asset_class') == 'FUND':
                result=live.fund(iid)
                sections.extend(result.sections); refs.extend(result.evidence_refs); calcs.extend(result.calculation_refs); missing.extend(result.missing_inputs)
            elif iid not in specs:
                missing.append(iid+":unsupported_asset_framework")
        if include_reference_assets:
            from investment_stack.execution.alternative_evidence import reference_alternatives
            result=reference_alternatives(live,transport or (urllib_transport if live_providers else _refuse_live_fetch))
            sections.extend(result.sections); refs.extend(result.evidence_refs); calcs.extend(result.calculation_refs); missing.extend(result.missing_inputs)
        import json
        rows = {r['calculation_id']: r for r in run.fetch_phase6_context()['calculations']}
        for iid in ids:
            expected = {'EQUITY_FUNDAMENTAL', 'EQUITY_VALUATION'} if iid in specs else ({'FUND'} if live.instruments.get(iid,{}).get('asset_class') == 'FUND' else set())
            produced = {row['calculation_name'] for ref, row in rows.items() if ref in calcs
                        and json.loads(row['result_json'] or '{}').get('subject') == iid}
            if expected - produced:
                raise RuntimeError('RESEARCH_STAGE_NOT_EXECUTED:' + iid)
        # Do not emit a buy action when a personal/event rule lacks release evidence.
        for rule in (*live.rules,*live.external_rules):
            iid=rule.get('instrument_id')
            if iid in ids and rule.get('action') == 'BLOCK_ADDITIONAL_BUY':
                sections.append(ReportSectionInput('rule_'+iid,'특별 운용 규칙 '+iid,
                    ('추가매수 보류. 이벤트 발생과 실적·가이던스·마진 검토 완료 근거가 확인될 때까지 제한을 유지합니다.',
                     '규칙 출처: '+str(rule.get('source','personal.db'))),status=Availability.PARTIAL))
                missing.append(iid+':special_rule_release_evidence')
        return SelectedAssetResearchResult(tuple(sections), evidence_refs=tuple(refs), calculation_refs=tuple(calcs), missing_inputs=tuple(missing))

    portfolio = portfolio_thesis_services(
        run_db=run,
        base_services=equity,
        personal_ledger=ledger,
        portfolio_loader=lambda request: _posted_portfolio_request(run, ledger, request, live),
        lightweight_research=live.lightweight,
        materiality_selector=live.select,
        selected_asset_research=research_selected,
        fund_inputs_loader=lambda: dict(live.fund_inputs),
    )
    return compose_seven_mode_services(
        run_db=run, ledger=ledger, equity_services=equity, portfolio_thesis_services=portfolio,
    )


def open_configured_host(run_workspace: Path, run_id: str, personal_db: Path, *,
                         live_providers=False, web_research_bundle=None,
                         market_captures=None, instrument_registry=None,
                         offline_captures=False) -> RuntimeServices:
    transport = None
    if market_captures is not None:
        from investment_stack.providers.capture import CapturedMarketTransport
        transport = CapturedMarketTransport(market_captures, allow_live_fallback=not offline_captures)
    return compose_configured_host(
        open_run_database(run_workspace, run_id), open_personal_ledger(personal_db),
        live_providers=live_providers, web_research_bundle=web_research_bundle,
        transport=transport, instrument_registry=instrument_registry,
    )
