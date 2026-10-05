"""Same-run capital-competition bridge, without personal ledger access or orders."""
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from decimal import Decimal
import json
from uuid import uuid4

from investment_stack.calculations.capital_competition import (
    CapitalCandidate, CompetitionPolicy, CompetitionResult, CATEGORY_LABELS, DIMENSIONS,
    analyze_capital_competition,
)
from investment_stack.reporting.models import ReportSectionInput, Availability
from investment_stack.reporting.portfolio_modes import _convert


@dataclass(frozen=True)
class AuthorizedCapitalInput:
    candidate: CapitalCandidate
    run_id: str
    as_of: str
    calculation_id: str
    approval_evidence_id: str
    approval_ref: str


@dataclass(frozen=True)
class AuthorizedFriction:
    from_instrument: str
    to_instrument: str
    total_fraction: Decimal
    run_id: str
    as_of: str
    calculation_id: str
    approval_evidence_id: str
    approval_ref: str


@dataclass(frozen=True)
class CapitalCompetitionPolicyInputs:
    assets: tuple[AuthorizedCapitalInput, ...] = ()
    policy: CompetitionPolicy = field(default_factory=CompetitionPolicy)
    frictions: tuple[AuthorizedFriction, ...] = ()
    policy_calculation_id: str | None = None
    policy_approval_evidence_id: str | None = None
    policy_approval_ref: str | None = None


@dataclass(frozen=True)
class CapitalCompetitionReport:
    sections: tuple[ReportSectionInput, ...]
    result: CompetitionResult
    calculation_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    review_triggers: tuple[str, ...]
    missing_inputs: tuple[str, ...]


def json_value(value):
    """Stable persisted input representation, also available to authorized hosts."""
    if hasattr(value, '__dataclass_fields__'):
        return json_value(asdict(value))
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(k): json_value(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_value(v) for v in value]
    return value


def _time(value):
    if not isinstance(value, str):
        raise ValueError('timestamp string required')
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('aware pinned clock required')
    return stamp


def _decode(value):
    try:
        result = json.loads(value or '{}')
    except (TypeError, ValueError):
        return {}
    return result if isinstance(result, dict) else {}


def _eligible(evidence, run_id, cutoff, *, instrument=None):
    if not evidence or evidence.get('run_id') != run_id or evidence.get('selection_state') != 'SELECTED':
        return False
    if instrument is not None and evidence.get('instrument_id') != instrument:
        return False
    if evidence.get('freshness_status') not in {'FRESH', 'LAST_VALID_CLOSE'}:
        return False
    if evidence.get('official_confirmation_status') in {'RUMOR', 'UNVERIFIED'}:
        return False
    try:
        observed, published, retrieved = (_time(evidence.get(k)) for k in ('observed_at', 'published_at', 'retrieved_at'))
        return observed <= cutoff and published <= cutoff and retrieved >= max(observed, published)
    except (ValueError, TypeError):
        return False


def _authorized(snapshot, *, calculation_id, approval_evidence_id, approval_ref, name, payload, cutoff, instrument=None):
    run_id = snapshot['run_metadata']['run_id']
    calculations = {r['calculation_id']: r for r in snapshot['calculations']}
    evidences = {r['evidence_id']: r for r in snapshot['evidence']}
    row = calculations.get(calculation_id)
    approval = evidences.get(approval_evidence_id)
    if not row or row.get('run_id') != run_id or row.get('calculation_name') != name or not _eligible(approval, run_id, cutoff, instrument=instrument):
        return False
    metadata = _decode(approval.get('metadata_json'))
    if metadata.get('policy_approved') is not True or not approval_ref or metadata.get('approval_ref') != approval_ref:
        return False
    inputs, result = _decode(row.get('inputs_json')), _decode(row.get('result_json'))
    refs = inputs.get('evidence_ids')
    if not isinstance(refs, list) or approval_evidence_id not in refs or result != json_value(payload):
        return False
    if not all(_eligible(evidences.get(ref), run_id, cutoff) for ref in refs):
        return False
    source_ids = inputs.get('source_calculation_ids')
    if not isinstance(source_ids, list) or not source_ids:
        return False
    for ref in source_ids:
        source = calculations.get(ref)
        if not source or source.get('run_id') != run_id or source.get('calculation_name') in {'CAPITAL_COMPETITION_INPUT', 'CAPITAL_COMPETITION_POLICY', 'CAPITAL_ROTATION_FRICTION', 'CAPITAL_COMPETITION'}:
            return False
        source_result = _decode(source.get('result_json'))
        if not source_result or (instrument and source_result.get('subject') != instrument):
            return False
        source_refs = _decode(source.get('inputs_json')).get('evidence_ids')
        if not isinstance(source_refs, list) or not source_refs or not all(_eligible(evidences.get(eid), run_id, cutoff) for eid in source_refs):
            return False
    return True


def derive_capital_competition_inputs(run, instrument_ids):
    """Convert persisted research to typed inputs; never synthesize an approval.

    Explicit research scores take precedence. Otherwise growth, earnings yield,
    ROE and inverse leverage use within-cohort midrank percentiles. Business
    quality and industry growth require actual research observations: revenue
    growth cannot stand in for industry growth or a moat assessment.
    """
    snapshot = run.fetch_phase6_context()
    cutoff = _time(snapshot['run_metadata']['analysis_as_of'])
    evidence = {r['evidence_id']: r for r in snapshot['evidence']}
    subjects = tuple(dict.fromkeys(instrument_ids))
    facts, sources, fact_priorities, fact_conflicts = {}, {}, {}, {}
    accepted = {'EQUITY_FUNDAMENTAL', 'EQUITY_VALUATION', 'FUND', 'PORTFOLIO_LIGHTWEIGHT', 'VALIDATED_PRIOR_RESEARCH'}

    def number(value):
        if isinstance(value, (float, bool)):
            return None
        try:
            value = Decimal(str(value))
            return value if value.is_finite() else None
        except (ValueError, ArithmeticError):
            return None

    def observation_number(row):
        try:
            return number(json.loads(row.get("value_text") or "null"))
        except (ValueError, TypeError):
            return None

    def eligible(ref, iid):
        row = evidence.get(ref)
        # Live collection can retrieve an already-published observation after
        # pinning the cutoff. Observed/publication times remain cutoff-bound.
        return _eligible(row, run.run_id, cutoff, instrument=iid)

    for iid in subjects:
        metrics, source_ids, conflicting_metrics, priorities = {}, [], set(), {}
        names = set()
        for row in snapshot['calculations']:
            output = _decode(row.get('result_json'))
            if (row.get('run_id') != run.run_id or row.get('calculation_name') not in accepted
                    or output.get('subject') != iid):
                continue
            refs = _decode(row.get('inputs_json')).get('evidence_ids', [])
            if not refs or not all(eligible(ref, iid) for ref in refs):
                continue
            names.add(row['calculation_name'])
            source_ids.append(row['calculation_id'])
            priority = 3 if row['calculation_name'] in {'EQUITY_FUNDAMENTAL', 'EQUITY_VALUATION', 'FUND'} else 2 if row['calculation_name'] == 'PORTFOLIO_LIGHTWEIGHT' else 1
            for metric in output.get('metrics', ()):
                value = number(metric.get('value'))
                bindings = metric.get('evidence_ids', [])
                if (value is not None and metric.get('status') == 'COMPLETE' and bindings
                        and set(bindings) <= set(refs)):
                    name = metric['name']
                    if priority < priorities.get(name, 0):
                        continue
                    if priority > priorities.get(name, 0):
                        metrics.pop(name, None)
                        conflicting_metrics.discard(name)
                    priorities[name] = priority
                    if name in metrics and metrics[name][0] != value:
                        conflicting_metrics.add(name)
                        metrics.pop(name)
                    if name not in conflicting_metrics:
                        metrics[name] = (value, bindings[0])
        # Qualitative assessments/industry observations are selected research,
        # not request payload score overrides. Ambiguous observations are withheld.
        for name in ('business_quality_score', 'industry_growth_rate',
                     *(dimension + '_score' for dimension in DIMENSIONS)):
            rows = [r for r in snapshot['evidence'] if (r.get('metric') == name
                    or _decode(r.get('metadata_json')).get('canonical_metric') == name)
                    and eligible(r['evidence_id'], iid)]
            # Imported prior evidence keeps its origin and cannot override current facts.
            current = [r for r in rows if not _decode(r.get('metadata_json')).get('imported_from_run_id')]
            rows = current or rows
            observation_priority = 2 if current else 1
            if observation_priority < priorities.get(name, 0):
                continue
            values = [(observation_number(r), r) for r in rows]
            values = [(value, row) for value, row in values if value is not None]
            if len({value for value, _ in values}) > 1:
                metrics.pop(name, None)
                conflicting_metrics.add(name)
                priorities[name] = observation_priority
            if len({value for value, _ in values}) == 1:
                value, row = values[0]
                md = _decode(row.get('metadata_json'))
                if name.endswith('_score') and (not 0 <= value <= 1 or not md.get('assessment_rationale')):
                    continue
                if observation_priority > priorities.get(name, 0):
                    metrics.pop(name, None)
                    conflicting_metrics.discard(name)
                priorities[name] = observation_priority
                if name in conflicting_metrics or (name in metrics and metrics[name][0] != value):
                    metrics.pop(name, None)
                    conflicting_metrics.add(name)
                    continue
                metrics[name] = (value, row['evidence_id'])
        facts[iid], sources[iid], fact_priorities[iid] = metrics, source_ids, priorities
        fact_conflicts[iid] = {name: priorities.get(name, 0) for name in conflicting_metrics}

    raw, raw_priorities = {}, {}
    for iid, metrics in facts.items():
        dimensions, dimension_priorities = {}, {}
        for dimension, name in (('growth', 'revenue_growth'), ('financial_quality', 'roe'),
                                ('industry_growth', 'industry_growth_rate')):
            if name in metrics:
                dimensions[dimension] = metrics[name]
                dimension_priorities[dimension] = fact_priorities[iid].get(name, 0)
        if 'pe' in metrics and metrics['pe'][0] > 0:
            value, ref = metrics['pe']
            dimensions['valuation'] = (1 / value, ref)
            dimension_priorities['valuation'] = fact_priorities[iid].get('pe', 0)
        if 'debt_to_equity' in metrics and metrics['debt_to_equity'][0] >= 0:
            value, ref = metrics['debt_to_equity']
            dimensions['risk_downside'] = (-value, ref)
            dimension_priorities['risk_downside'] = fact_priorities[iid].get('debt_to_equity', 0)
        raw[iid], raw_priorities[iid] = dimensions, dimension_priorities
        for dimension in tuple(dimensions):
            if fact_conflicts[iid].get(dimension + '_score', 0) >= dimension_priorities[dimension]:
                dimensions.pop(dimension)
                dimension_priorities.pop(dimension)
    # Each dimension includes all holdings with valid observations for that
    # dimension. Missing dimensions remain unknown; the gate never defines peers.
    eligible_ids = list(subjects)
    assets = []
    for iid, metrics in facts.items():
        scores, bindings, direct_dimensions = {}, {}, set()
        for dimension in DIMENSIONS:
            direct = metrics.get(dimension + '_score')
            raw_name = {'growth':'revenue_growth','valuation':'pe','financial_quality':'roe',
                        'risk_downside':'debt_to_equity','industry_growth':'industry_growth_rate'}.get(dimension)
            conflict_priority = max(fact_conflicts[iid].get(dimension + '_score', 0), fact_conflicts[iid].get(raw_name, 0))
            source_priority = max(fact_priorities[iid].get(dimension + '_score', 0) if direct else 0,
                                  raw_priorities[iid].get(dimension, 0))
            if conflict_priority and conflict_priority >= source_priority:
                continue
            if direct is not None and 0 <= direct[0] <= 1 and fact_priorities[iid].get(dimension + '_score', 0) >= raw_priorities[iid].get(dimension, 0):
                scores[dimension], bindings[dimension] = direct
                direct_dimensions.add(dimension)
            elif dimension in raw[iid]:
                value, ref = raw[iid][dimension]
                peers = [raw[other][dimension][0] for other in eligible_ids if dimension in raw[other]]
                if len(peers) < 2:
                    continue
                scores[dimension] = (Decimal(sum(v < value for v in peers))
                    + Decimal(sum(v == value for v in peers)) / 2) / len(peers)
                bindings[dimension] = ref
        prices = [r for r in snapshot['evidence'] if r.get('metric') == 'current_price'
                  and eligible(r['evidence_id'], iid)]
        price_values = [(observation_number(r), r) for r in prices]
        price_values = [(v, r) for v, r in price_values if v is not None and v > 0]
        price, price_ref = (price_values[0][0], price_values[0][1]['evidence_id']) if len({v for v, _ in price_values}) == 1 else (None, None)
        provenance = {}
        for dimension, ref in bindings.items():
            row = evidence[ref]
            md = _decode(row.get('metadata_json'))
            metric_name = dimension + '_score' if dimension in direct_dimensions else {'growth':'revenue_growth','valuation':'pe',
                'financial_quality':'roe','risk_downside':'debt_to_equity','industry_growth':'industry_growth_rate'}.get(dimension)
            chosen_priority = fact_priorities[iid].get(metric_name, 2)
            chosen_sources = [c['calculation_id'] for c in snapshot['calculations']
                if c['calculation_id'] in sources[iid]
                and (3 if c['calculation_name'] in {'EQUITY_FUNDAMENTAL','EQUITY_VALUATION','FUND'} else 2 if c['calculation_name']=='PORTFOLIO_LIGHTWEIGHT' else 1) == chosen_priority
                and any(m.get('name') == metric_name and ref in m.get('evidence_ids',()) for m in _decode(c.get('result_json')).get('metrics',()))]
            provenance[dimension] = {'evidence_id': ref, 'run_id': run.run_id,
                'source_run_id': md.get('imported_from_run_id', run.run_id),
                'source_evidence_id': md.get('original_evidence_id', ref),
                'source_uri': row.get('source_uri'), 'observed_at': row.get('observed_at'),
                'published_at': row.get('published_at'), 'retrieved_at': row.get('retrieved_at'),
                'freshness_status': row.get('freshness_status'),
                'basis': 'DIRECT_RESEARCH_SCORE' if dimension in direct_dimensions else 'COHORT_MIDRANK',
                'assessment_rationale': md.get('assessment_rationale'),
                'source_calculation_ids': chosen_sources,
                'source_stage': '|'.join(dict.fromkeys(c['calculation_name'] for c in snapshot['calculations']
                    if c['calculation_id'] in chosen_sources)) or ('VALIDATED_PRIOR_RESEARCH' if md.get('imported_from_run_id') else 'LIGHTWEIGHT_SELECTED_EVIDENCE'),
                'input_priority': chosen_priority,
                'normalization_cohort': [other for other in eligible_ids if dimension in raw[other]] if dimension not in direct_dimensions else [],
                'normalization_universe': list(subjects)}
        listing = next((_decode(t.get('metadata_json')).get('listing_id') for t in snapshot.get('task_states', ())
                        if t.get('task_name') == 'instrument_resolution:' + iid and t.get('task_status') == 'COMPLETE'), None)
        ticker = listing.split(':', 1)[1] if isinstance(listing, str) and ':' in listing else None
        candidate = CapitalCandidate(iid, scores=scores, score_evidence=bindings, score_provenance=provenance, ticker=ticker,
                                     price=price, price_evidence_id=price_ref, verified_price=price is not None,
                                     relative_scores=any(d not in direct_dimensions for d in scores))
        cid = 'calc:capital-research-input:' + uuid4().hex
        refs = tuple(dict.fromkeys((*bindings.values(), *((price_ref,) if price_ref else ()),
            *(ref for other in eligible_ids for _, ref in raw[other].values()))))
        run.add_calculation(calculation_id=cid, calculation_name='CAPITAL_COMPETITION_INPUT',
            formula='same_run_research_scores_or_cohort_midrank_v1',
            inputs={'evidence_ids': list(refs), 'source_calculation_ids': list(dict.fromkeys((*sources[iid],
                        *(cid for other in eligible_ids for cid in sources[other])))),
                    'analysis_as_of': snapshot['run_metadata']['analysis_as_of'],
                    'normalization_cohort': eligible_ids, 'automatic_research_conversion': True},
            result=json_value(candidate))
        assets.append(AuthorizedCapitalInput(candidate, run.run_id,
                      snapshot['run_metadata']['analysis_as_of'], cid, '', ''))
    return CapitalCompetitionPolicyInputs(tuple(assets))


TITLES = ('핵심 결론', '자본 집중 우선순위', '정리 우선순위', '유지/관찰 자산', '신규자금 투입 우선순위', '자본 재배치 후보', 'Concentration Risk', 'Expected 5Y CAGR', '주요 Thesis Breaker', 'Latest Material Events')


def render_capital_competition(run, portfolio_request, portfolio_result, optionalpolicyinputs=None, *, candidate_ids=()):
    """Persist outputs and render all ten sections before the fixed Review stage.

    Missing qualitative data remains WATCH/unranked. User-approved score inputs
    must match a persisted same-run receipt; this function never discovers or
    invents probabilities, growth assumptions, narratives, or target weights.
    """
    snapshot = run.fetch_phase6_context()
    meta = snapshot['run_metadata']
    cutoff = _time(meta['analysis_as_of'])
    if meta.get('run_id') != run.run_id or portfolio_request.pinned_state.analysis_as_of != meta['analysis_as_of']:
        raise ValueError('capital competition requires the pinned run clock')
    pin = snapshot.get('pinned_personal_state') or {}
    if (pin.get('state_version') != portfolio_result.state_version
            or pin.get('portfolio_snapshot_id') != portfolio_result.snapshot_ref
            or portfolio_request.pinned_state.state_version != portfolio_result.state_version
            or portfolio_request.pinned_state.snapshot_ref != portfolio_result.snapshot_ref):
        raise ValueError('capital competition requires the pinned personal state')
    automatic = derive_capital_competition_inputs(run, (*[p.instrument_id for p in portfolio_request.positions], *candidate_ids))
    snapshot = run.fetch_phase6_context()
    supplied = optionalpolicyinputs or CapitalCompetitionPolicyInputs()
    if not isinstance(supplied, CapitalCompetitionPolicyInputs):
        raise ValueError('typed capital competition policy inputs required')
    policy = supplied.policy
    evidence_refs, source_refs, missing = [], [], []
    if policy != CompetitionPolicy() and not _authorized(snapshot,
            calculation_id=supplied.policy_calculation_id, approval_evidence_id=supplied.policy_approval_evidence_id,
            approval_ref=supplied.policy_approval_ref, name='CAPITAL_COMPETITION_POLICY',
            payload=policy, cutoff=cutoff):
        policy = CompetitionPolicy()
        missing.append('capital_competition_policy_override_unverified')
    elif supplied.policy_calculation_id:
        source_refs.append(supplied.policy_calculation_id)
        evidence_refs.append(supplied.policy_approval_evidence_id)
    # Reuse the calculator's eligible FX path; unknown gross assets forbids a
    # misleading partial-subset weight being presented as total portfolio weight.
    portfolio_sources = []
    expected_total = str(portfolio_result.gross_assets) if portfolio_result.gross_assets is not None else None
    for row in snapshot['calculations']:
        inputs, values = _decode(row.get('inputs_json')), _decode(row.get('result_json'))
        if (row.get('run_id') == run.run_id and row.get('calculation_name') == 'portfolio_analysis'
                and inputs.get('state_version') == portfolio_result.state_version
                and inputs.get('snapshot_ref') == portfolio_result.snapshot_ref
                and values.get('gross_assets') == expected_total):
            portfolio_sources.append(row['calculation_id'])
    denominator = portfolio_result.gross_assets if portfolio_sources else None
    source_refs.extend(portfolio_sources)
    if not portfolio_sources:
        missing.append('same_run_portfolio_calculation_unverified')
    defaults = {}
    for position in portfolio_request.positions:
        value = _convert(position.market_value, position.currency, portfolio_request.evaluation_currency, cutoff, portfolio_request.fx_evidence)
        weight = value / denominator if value is not None and denominator is not None and denominator > 0 else None
        defaults[position.instrument_id] = CapitalCandidate(position.instrument_id, weight=weight)
    candidates = dict(defaults)
    for iid in candidate_ids:
        if not isinstance(iid,str) or not iid.strip():
            raise ValueError('explicit candidate identity required')
        candidates.setdefault(iid,CapitalCandidate(iid,held=False))
    if len({a.candidate.instrument_id for a in supplied.assets}) != len(supplied.assets):
        raise ValueError('duplicate supplied capital policy asset')
    # Explicit overrides retain their original approval checks. Internal derived
    # values are created here from validated same-run calculations only.
    automatic_assets = tuple(a for a in automatic.assets if a.candidate.instrument_id not in {b.candidate.instrument_id for b in supplied.assets})
    for item in (*automatic_assets, *supplied.assets):
        c = item.candidate
        refs = set(c.score_evidence.values()) | {v for s in c.scenarios for v in s.evidence_bindings.values()}
        if c.price_evidence_id:
            refs.add(c.price_evidence_id)
        valid = any(item is a for a in automatic_assets) or (item.run_id == run.run_id and _time(item.as_of) == cutoff and _authorized(snapshot,
            calculation_id=item.calculation_id, approval_evidence_id=item.approval_evidence_id,
            approval_ref=item.approval_ref, name='CAPITAL_COMPETITION_INPUT', payload=c,
            cutoff=cutoff, instrument=c.instrument_id))
        by_id = {r['evidence_id']: r for r in snapshot['evidence']}
        valid = valid and all(_eligible(by_id.get(ref), run.run_id, cutoff, instrument=c.instrument_id) for ref in refs)
        price_row = by_id.get(c.price_evidence_id)
        if valid and c.verified_price:
            try:
                price = Decimal(str(json.loads(price_row['value_text'])))
                valid = price_row.get('metric') == 'current_price' and price == c.price and price > 0
            except (TypeError, ValueError, ArithmeticError, KeyError):
                valid = False
        if not valid:
            missing.append(c.instrument_id + ':capital_input_not_verified')
            continue
        held = c.instrument_id in defaults
        candidates[c.instrument_id] = replace(c, held=held, weight=defaults[c.instrument_id].weight if held else None)
        evidence_refs.extend((*refs, *((item.approval_evidence_id,) if item.approval_evidence_id else ())))
        source_refs.append(item.calculation_id)
    friction = {}
    for item in supplied.frictions:
        valid = item.run_id == run.run_id and _time(item.as_of) == cutoff and _authorized(snapshot,
            calculation_id=item.calculation_id, approval_evidence_id=item.approval_evidence_id,
            approval_ref=item.approval_ref, name='CAPITAL_ROTATION_FRICTION', payload={
                'from_instrument': item.from_instrument, 'to_instrument': item.to_instrument,
                'total_fraction': item.total_fraction, 'components_confirmed': ['tax', 'fees', 'fx', 'slippage']}, cutoff=cutoff)
        if valid:
            friction[item.from_instrument, item.to_instrument] = item.total_fraction
            evidence_refs.append(item.approval_evidence_id)
            source_refs.append(item.calculation_id)
        else:
            missing.append('rotation_friction_not_verified:' + item.from_instrument + ':' + item.to_instrument)
    result = analyze_capital_competition(tuple(candidates.values()), policy=policy, rotation_friction=friction)
    all_rows = (*result.ranked, *result.unranked)
    missing.extend(r.instrument_id + ':' + v for r in all_rows for v in r.missing_inputs)
    if denominator is None:
        missing.append('concentration_total_portfolio_denominator_unavailable')
    refs = tuple(dict.fromkeys(evidence_refs))
    source_refs = tuple(dict.fromkeys(source_refs))
    latest_events=[]
    for row in snapshot['calculations']:
        if row.get('calculation_name')!='news_thesis_impact' or row.get('run_id')!=run.run_id:
            continue
        event_output=_decode(row.get('result_json'))
        if event_output.get('subject') not in candidates:
            continue
        event_refs=tuple(_decode(row.get('inputs_json')).get('evidence_ids',()))
        if not event_refs or not all(_eligible(next((e for e in snapshot['evidence'] if e['evidence_id']==eid),None),run.run_id,cutoff) for eid in event_refs):
            continue
        latest_events.extend({'instrument_id':event_output['subject'],**event} for event in event_output.get('events',()) if isinstance(event,dict))
        refs=tuple(dict.fromkeys((*refs,*event_refs)))
        source_refs=tuple(dict.fromkeys((*source_refs,row['calculation_id'])))
    calc_id = 'calc:capital-competition:' + uuid4().hex
    run.add_calculation(calculation_id=calc_id, calculation_name='CAPITAL_COMPETITION',
        formula='six_evidenced_normalized_scores_weighted_priority_v1; explicit_5Y_scenarios',
        inputs={'evidence_ids': list(refs), 'source_calculation_ids': list(source_refs),
                'state_version': portfolio_result.state_version, 'snapshot_ref': portfolio_result.snapshot_ref,
                'analysis_as_of': meta['analysis_as_of'], 'policy': json_value(policy),
                'candidates': json_value(tuple(candidates.values())),
                'rotation_frictions': [{'from_instrument': a, 'to_instrument': b, 'total_fraction': str(v)} for (a, b), v in friction.items()],
                'ranking_basis': 'research_priority_score_not_expected_return',
                'automatic_input_calculation_ids': [a.calculation_id for a in automatic_assets]},
        result=json_value(result))
    lines = [[] for _ in TITLES]
    lines[0] = ['집중도는 위험 정보이며 자동 매도 신호가 아닙니다. 근거가 충분한 4~6개 자산 집중을 검토할 수 있습니다.',
                '가중 우선순위 점수는 위험조정 기대수익률 수치가 아닙니다. 시나리오 CAGR에 임의 확률을 적용하지 않습니다.',
                '분류·우선순위는 검토 전 잠정 후보입니다. 신규 집중·증액·재배치는 Level 3 검토 완료 근거 전까지 대기합니다.']
    if not result.ranked:
        lines[0].append('근거가 부족하여 자본 경쟁 순위와 신규자금 배분을 확정하지 않았습니다.')
    for i, row in enumerate((*result.ranked, *sorted(result.unranked, key=lambda r: r.instrument_id)), 1):
        line = f'{i}. {row.instrument_id} — {CATEGORY_LABELS[row.category]} 잠정 후보; 우선순위 점수={row.score}'
        if candidates[row.instrument_id].relative_scores:
            line += '; 적격 비교군 내 상대 점수; 절대 사업가치·매도 판단 아님'
        lines[1].append(line)
        if row.score is None:
            lines[1].append('근거 부족: 점수 null, 신뢰도 LOW; 표시 번호는 경제적 우열 순위가 아님. 부족=' + ', '.join(row.missing_inputs))
        if row.category.value in {'REDUCE', 'EXIT_CANDIDATE'}:
            lines[2].append(line + '; 검토 후보이며 주문 지시 아님')
        else:
            lines[3].append(line)
        if row.category.value in {'CORE_CONCENTRATION', 'SECONDARY_GROWTH'}:
            lines[4].append(line + '; Level 3 검토 완료 근거까지 증액 대기; 기존 비중·유동성·대안 검토 후 판단, 고정 목표비중 없음')
    lines[4].insert(0, '신규 집중·증액은 Level 3 검토 완료 근거 전까지 대기합니다. 입력 부족 자산에는 신규자금 배분 순위를 만들지 않습니다.')
    from investment_stack.calculations.position_policy import GUIDANCE
    lines[6].append(GUIDANCE)
    lines[4].append('ETF·현금도 경쟁 자산입니다. 매력적인 개별 후보 부재·변동성 완화·사용자의 시장 노출 의도·대기자금·상대 수익 우위 근거가 있을 때 검토합니다.')
    for row in result.unranked:
        lines[3].append(row.instrument_id + ' — 관찰; 순위 미확정; 부족=' + ', '.join(row.missing_inputs))
    for rotation in result.rotations:
        lines[5].append(f'{rotation.from_instrument} → {rotation.to_instrument}: {rotation.status}; {rotation.reason}; 마찰비용 반영 시나리오 CAGR={rotation.net_destination_cagr}')
    for row in all_rows:
        lines[6].append(f'{row.instrument_id}: 전체자산 비중={row.weight if row.weight is not None else "확인 불가"}; ' + ', '.join(row.flags))
        lines[7].append(row.instrument_id + ': ' + ('; '.join(f'{k} CAGR={v}' for k, v in row.scenario_cagrs.items()) if row.scenario_cagrs else '5Y CAGR 확인 불가'))
        c = candidates[row.instrument_id]
        lines[8].extend(row.instrument_id + ': ' + text for text in c.thesis_breakers)
        lines[9].extend(row.instrument_id + ': ' + text for text in c.material_events)
    lines[9].extend(event['instrument_id']+': '+str(event.get('headline'))
        +'; published='+str(event.get('published_at'))+'; confirmation='+str(event.get('confirmation'))
        +'; thesis impact='+str(event.get('thesis_impact'))+'; 미확인 영향은 가치평가에 반영하지 않음'
        for event in latest_events)
    if result.review_triggers:
        lines[6].append('Level 3 Review 필요: ' + ', '.join(result.review_triggers))
    sections = tuple(ReportSectionInput('capital_competition_' + str(i + 1), title,
                    tuple(body or ['확인된 근거 없음; 후보·결론 생성 보류']),
                    status=Availability.PARTIAL if missing else Availability.AVAILABLE,
                    evidence_ids=refs, calculation_ids=(calc_id,),
                    metadata={'capital_competition': True, 'review_triggers': result.review_triggers,
                              'non_posting': True, 'score_is_expected_return': False})
                    for i, (title, body) in enumerate(zip(TITLES, lines)))
    return CapitalCompetitionReport(sections, result, (calc_id,), refs, result.review_triggers, tuple(dict.fromkeys(missing)))
