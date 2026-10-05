"""Optional portfolio comparison inside the existing single-asset Review step."""
from uuid import uuid4
from investment_stack.reporting.models import Availability, ReportSectionInput
from investment_stack.reporting.portfolio_modes import PortfolioAnalysisRequest, analyze_portfolio
from .capital_competition import render_capital_competition


def render_optional_capital_context(run, request, loader, candidate_ids):
    if request.payload.get('portfolio_context') is not True:
        return None
    portfolio=loader(request) if loader is not None else request.payload.get('portfolio_request')
    if not isinstance(portfolio,PortfolioAnalysisRequest):
        return ReportSectionInput('candidate_portfolio_context','신규 후보와 기존 보유의 자본 경쟁',
            ('검증된 포트폴리오 입력이 없어 후보의 상대 우위·재배치 순편익은 확인 불가입니다.',),
            status=Availability.PARTIAL)
    pin=run.fetch_phase6_context()['pinned_personal_state'] or {}
    meta=run.fetch_phase6_context()['run_metadata']
    if (portfolio.pinned_state.state_version!=pin.get('state_version')
        or portfolio.pinned_state.snapshot_ref!=pin.get('portfolio_snapshot_id')
        or portfolio.pinned_state.analysis_as_of!=meta['analysis_as_of']):
        raise ValueError('candidate comparison requires the same pinned portfolio and clock')
    result=analyze_portfolio(portfolio)
    refs=tuple(row['evidence_id'] for row in run.fetch_phase6_context()['evidence']
               if row.get('selection_state')=='SELECTED')
    cid='calc:portfolio-context:'+uuid4().hex
    run.add_calculation(calculation_id=cid,calculation_name='portfolio_analysis',
        formula='pinned portfolio context for explicit candidate relative opportunity comparison',
        inputs={'evidence_ids':list(refs),'state_version':result.state_version,'snapshot_ref':result.snapshot_ref},
        result={'gross_assets':str(result.gross_assets) if result.gross_assets is not None else None,
                'subject':'personal_portfolio','missing_inputs':list(result.missing_inputs)})
    return render_capital_competition(run,portfolio,result,
        optionalpolicyinputs=request.payload.get('capital_competition_policy_inputs'),candidate_ids=candidate_ids)
