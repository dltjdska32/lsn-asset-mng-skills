"""Run-local adversarial conditions from persisted outputs and approved disclosures."""
from dataclasses import replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
from uuid import uuid4
from .models import ReviewFinding, FindingSeverity

TOPICS = ('strongest_bear_case', 'hidden_assumptions', 'priced_in_expectations',
          'customer_concentration', 'supplier_concentration', 'dilution', 'debt',
          'regulatory_geopolitical_risk', 'cyclicality', 'technology_substitution',
          'margin_normalization', 'multiple_compression', 'scenario_failure',
          'thesis_breaker', 'missing_data', 'liquidity', 'alternative_opportunity',
          'core_holding_correlation', 'growth_slowdown', 'concentration_justification', 'thesis_confidence')
TOPIC_ACTIONS = {
    'liquidity': 'Validate dated trading depth, spread, liquidation horizon and venue/redemption restrictions before sizing.',
    'alternative_opportunity': 'Compare the strongest evidenced current/candidate holding after tax, fees, FX and slippage; priority score is not expected return.',
    'core_holding_correlation': 'Retrieve aligned dated return series and overlapping customer/sector exposures; do not infer independence from different tickers.',
    'growth_slowdown': 'Examine growth slowing by 30-50% only with explicit approved stress assumptions; do not calculate an arbitrary stress return.',
    'concentration_justification': 'Ask what would make concentration wrong; validate valuation, downside, liquidity and the strongest alternative before approving size.',
    'thesis_confidence': 'Distinguish source-supported conviction from narrative; identify disconfirming facts and measurable thesis-breaker conditions.',
}
ASSET_CALCULATIONS = {'EQUITY_VALUATION', 'EQUITY_FUNDAMENTAL', 'FUND', 'FUND_ANALYSIS',
                      'ALTERNATIVE_BITCOIN', 'ALTERNATIVE_ETHEREUM', 'ALTERNATIVE_GOLD', 'ALTERNATIVE_SILVER'}
PORTFOLIO_CALCULATIONS = {'portfolio_analysis', 'CAPITAL_COMPETITION', 'portfolio_risk', 'cross_asset_allocation'}


def _object(value):
    try:
        item = json.loads(value or '{}')
    except (ValueError, TypeError):
        return {}
    return item if isinstance(item, dict) else {}


def _number(value):
    if isinstance(value, (bool, float)) or value is None:
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _time(value):
    if not isinstance(value, str):
        raise ValueError('timestamp required')
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('aware timestamp required')
    return stamp


def _eligible(row, run_id, cutoff, subject=None):
    if not row or row.get('run_id') != run_id or row.get('selection_state') != 'SELECTED':
        return False
    if subject is not None and row.get('instrument_id') != subject:
        return False
    if row.get('freshness_status') not in {'FRESH', 'LAST_VALID_CLOSE'}:
        return False
    if row.get('official_confirmation_status') in {'RUMOR', 'UNVERIFIED', 'UNCONFIRMED', 'FIXTURE_ONLY_WEB_UNVERIFIED', 'CANDIDATE_UNVERIFIED_LIVE'}:
        return False
    metadata = _object(row.get('metadata_json'))
    if metadata.get('calculation_input_approved') is False:
        return False
    try:
        observed, published, retrieved = (_time(row.get(k)) for k in ('observed_at', 'published_at', 'retrieved_at'))
        return observed <= cutoff and published <= cutoff and retrieved >= max(observed, published)
    except (ValueError, TypeError):
        return False


def _primary_disclosure(row):
    metadata = _object(row.get('metadata_json'))
    return (row.get('source_tier') == 1
            and metadata.get('calculation_input_approved') is True
            and metadata.get('disclosure_content_verified') is True
            and isinstance(metadata.get('adversarial_disclosures'), dict))


def _strings(value):
    return tuple(v for v in value if isinstance(v, str) and v.strip()) if isinstance(value, (tuple, list)) else ()


def review_valuation_outputs(run, result, *, required_subjects=(), review_triggers=()):
    """Execute topic assessments, including required funds/concentrations.

    A conditional ratio observation is not completion of a qualitative review.
    Approved primary disclosures may supply explicit adverse conditions and
    thesis-breaker criteria. No absent fact, probability or stress percentage is
    inferred. Retrieval after the pinned clock is permitted for prior disclosure.
    """
    context = run.fetch_phase6_context()
    metadata = context.get('run_metadata') or {}
    cutoff = _time(metadata.get('analysis_as_of'))
    if metadata.get('run_id') != run.run_id:
        raise ValueError('adversarial review must bind the current run')
    evidence = {r['evidence_id']: r for r in context.get('evidence', ()) if r.get('run_id') == run.run_id}
    rows = [r for r in context.get('calculations', ()) if r.get('run_id') == run.run_id]
    subjects = list(dict.fromkeys(_strings(required_subjects)))
    for row in rows:
        output = _object(row.get('result_json'))
        if row.get('calculation_name') == 'EQUITY_VALUATION' and isinstance(output.get('subject'), str):
            if output['subject'] not in subjects:
                subjects.append(output['subject'])
    findings = []
    for subject in subjects:
        sources, outputs, source_refs, refs, source_gaps, capital_outputs = [], [], [], set(), [], []
        for row in rows:
            name = row.get('calculation_name')
            output, inputs = _object(row.get('result_json')), _object(row.get('inputs_json'))
            if name in ASSET_CALCULATIONS and output.get('subject') == subject:
                ids = _strings(inputs.get('evidence_ids', ()))
                good = tuple(eid for eid in ids if _eligible(evidence.get(eid), run.run_id, cutoff))
                # Keep an actual unavailable attempt, but never consume a numeric
                # source with absent, rejected or future input evidence.
                if ids and len(good) != len(ids):
                    source_gaps.append('ineligible_source:' + row['calculation_id'])
                    continue
                sources.append(row)
                outputs.append(output)
                source_refs.append(row['calculation_id'])
                refs.update(good)
            elif name in PORTFOLIO_CALCULATIONS:
                ids = _strings(inputs.get('evidence_ids', ()))
                if all(_eligible(evidence.get(eid), run.run_id, cutoff) for eid in ids):
                    source_refs.append(row['calculation_id'])
                    refs.update(ids)
                    if name == 'CAPITAL_COMPETITION':
                        capital_outputs.append((row, inputs, output, ids))
        metrics = {}
        for source, output in zip(sources, outputs):
            source_evidence_ids = set(_strings(_object(source.get('inputs_json')).get('evidence_ids', ())))
            for item in output.get('metrics', ()) if isinstance(output.get('metrics'), list) else ():
                if not isinstance(item, dict) or item.get('status') not in {'COMPLETE', 'AVAILABLE'} or _number(item.get('value')) is None:
                    continue
                ids = _strings(item.get('evidence_ids', ()))
                if not ids or not set(ids) <= source_evidence_ids or not all(_eligible(evidence.get(eid), run.run_id, cutoff, subject) for eid in ids):
                    source_gaps.append('metric_lineage_unavailable:' + str(item.get('name')))
                    continue
                name = item.get('name')
                if isinstance(name, str):
                    previous = metrics.get(name)
                    if previous and previous.get('value') != item.get('value'):
                        metrics.pop(name, None)
                        source_gaps.append('conflicting_metric:' + name)
                    elif 'conflicting_metric:' + name not in source_gaps:
                        metrics[name] = item
        usable_output = any(output.get('status') in {'COMPLETE', 'PARTIAL', 'AVAILABLE'}
                            and (any(isinstance(m, dict) and _number(m.get('value')) is not None
                                     for m in (output.get('metrics') if isinstance(output.get('metrics'), list) else ()))
                                 or bool(_strings(output.get('findings', ())))) for output in outputs)
        if not usable_output:
            source_gaps.append('usable_asset_output_unavailable')
        unknowns = tuple(dict.fromkeys((*source_gaps, *(u for output in outputs for u in _strings(output.get('unknowns', ()))))))
        assessments = {topic: {'status': 'UNAVAILABLE', 'assessment': 'No supporting same-run approved disclosure supplied.',
                               'action': TOPIC_ACTIONS.get(topic, 'Retrieve dated primary disclosure for ' + topic + '; do not infer absence of risk.'),
                               'evidence_ids': [], 'source_calculation_ids': []} for topic in TOPICS}

        def assess(topic, text, action, *, names=(), status='CONDITIONAL', evidence_ids=()):
            used = tuple(name for name in names if name in metrics)
            ids = tuple(dict.fromkeys((*evidence_ids, *(eid for name in used for eid in metrics[name]['evidence_ids']))))
            refs.update(ids)
            assessments[topic] = {'status': status, 'assessment': text, 'action': action,
                'metrics': {name: metrics[name]['value'] for name in used}, 'evidence_ids': list(ids),
                'source_calculation_ids': [r['calculation_id'] for r in sources]}

        ratios = tuple(name for name in ('pe', 'pb', 'price_to_sales', 'ev_to_ebitda') if name in metrics)
        if ratios:
            assess('priced_in_expectations', 'Observed multiples: ' + ', '.join(name + '=' + str(metrics[name]['value']) for name in ratios)
                   + '. Multiples alone do not determine the growth currently priced in.',
                   'Supply source-bound normalized earnings and terminal/growth assumptions for reverse valuation.', names=ratios)
            assess('multiple_compression', 'At unchanged earnings/cash flow, a lower multiple implies a proportionately lower value. No stress percentage or probability inferred.',
                   'Use a documented terminal multiple and bear scenario; verify current and terminal period compatibility.', names=ratios)
        scenarios = tuple(name for name in metrics if name.startswith(('dcf_scenario_', 'scenario_', 'dcf_sensitivity_')))
        if scenarios:
            values = [(name, _number(metrics[name]['value'])) for name in scenarios]
            low = min(values, key=lambda item: item[1])
            assess('strongest_bear_case', 'Lowest supplied scenario/sensitivity: ' + low[0] + '=' + str(low[1])
                   + '. Conditional supplied assumptions; this is not an exhaustive bear case or probability estimate.',
                   'Compare operational, financing and concentration disclosures with the supplied downside.', names=scenarios)
            assess('scenario_failure', 'Supplied scenario range=' + str(min(v for _, v in values)) + ' to ' + str(max(v for _, v in values))
                   + '; permanent loss may extend outside this model range.',
                   'Re-run when evidenced growth, dilution, financing or terminal assumptions fail.', names=scenarios)
        binding_rows = []
        for source, output in zip(sources, outputs):
            inputs = _object(source.get('inputs_json'))
            output_metadata = output.get('metadata') if isinstance(output.get('metadata'), dict) else {}
            bindings = inputs.get('dcf_assumption_value_bindings') or output_metadata.get('dcf_assumption_value_bindings')
            if isinstance(bindings, list) and bindings:
                binding_rows.extend(bindings)
        assess('hidden_assumptions', 'Evidence-bound assumption records require period, share-count, unit and sensitivity verification.'
               if binding_rows else 'No source-bound DCF/scenario assumptions supplied; ratios alone do not establish fair value.',
               'Verify each assumption receipt; disclose terminal-multiple, growth and share-count basis.', status='CONDITIONAL')
        for topic, names in (('debt', ('net_debt', 'debt_to_equity', 'interest_coverage')),
                             ('margin_normalization', ('operating_margin', 'net_margin', 'gross_margin')),
                             ('dilution', ('dilution', 'share_count_growth')),
                             ('customer_concentration', ('top_customer_revenue_share',)),
                             ('supplier_concentration', ('top_supplier_purchase_share',))):
            present = tuple(name for name in names if name in metrics)
            if present:
                assess(topic, 'Observed metrics: ' + ', '.join(name + '=' + str(metrics[name]['value']) for name in present)
                       + '; one observation does not establish future sustainability or absence of risk.',
                       'Check dated maturities, covenants, share commitments and operating concentration as applicable.', names=present)
        fund = any(source.get('calculation_name') in {'FUND', 'FUND_ANALYSIS'} for source in sources)
        if fund:
            present = tuple(k for k in ('top10_concentration', 'holding_hhi', 'nav_premium_discount', 'expense_ratio', 'tracking_difference') if k in metrics)
            if present:
                assess('strongest_bear_case', 'Fund structure observations: ' + ', '.join(k + '=' + str(metrics[k]['value']) for k in present)
                       + '; overlapping holdings, benchmark downside, tracking/liquidity and NAV dislocation remain relevant risks.',
                       'Validate issuer holdings coverage, benchmark concentration and dated redemption/liquidity disclosures.', names=present)
        liquidity_names = tuple(k for k in ('average_daily_value', 'bid_ask_spread', 'liquidity_score') if k in metrics)
        if liquidity_names:
            assess('liquidity', 'Observed liquidity metrics: ' + ', '.join(k + '=' + str(metrics[k]['value']) for k in liquidity_names)
                   + '; historical turnover alone does not establish liquidation capacity under stress.',
                   TOPIC_ACTIONS['liquidity'], names=liquidity_names)
        if review_triggers:
            assess('concentration_justification', 'Concentration review was requested by explicit triggers: '
                   + ', '.join(str(t) for t in review_triggers) + '. A concentration trigger is not a sell instruction or approval of size.',
                   TOPIC_ACTIONS['concentration_justification'])
        # Capital priorities are conditional scenario comparisons, not a
        # probability-weighted expected return. Require original authorized
        # policy receipts before consuming qualitative scores or scenario values.
        for capital_row, capital_inputs, capital_output, capital_ids in capital_outputs:
            ranked = capital_output.get('ranked')
            candidates = capital_inputs.get('candidates')
            if not isinstance(ranked, list) or not isinstance(candidates, list) or not capital_ids:
                continue
            source_ids = _strings(capital_inputs.get('source_calculation_ids', ()))
            policies = [_object(r.get('result_json')) for r in rows
                        if r.get('calculation_id') in source_ids and r.get('calculation_name') == 'CAPITAL_COMPETITION_INPUT'
                        and _strings(_object(r.get('inputs_json')).get('evidence_ids', ()))
                        and all(_eligible(evidence.get(eid), run.run_id, cutoff)
                                for eid in _strings(_object(r.get('inputs_json')).get('evidence_ids', ())))]
            authorized = {}
            for c in candidates:
                if not isinstance(c, dict):
                    continue
                policy = next((p for p in policies if p.get('instrument_id') == c.get('instrument_id')
                               and all(p.get(k) == c.get(k) for k in ('scores', 'score_evidence', 'scenarios', 'price', 'price_evidence_id', 'verified_price'))), None)
                if not policy or c.get('verified_price') is not True:
                    continue
                approval_ids = [eid for eid in capital_ids if _object(evidence[eid].get('metadata_json')).get('policy_approved') is True
                                and evidence[eid].get('instrument_id') == c.get('instrument_id')]
                if not approval_ids:
                    continue
                authorized[c['instrument_id']] = c
            policy = capital_inputs.get('policy')
            weights = policy.get('weights') if isinstance(policy, dict) else None
            if not isinstance(weights, dict) or not weights or any(_number(v) is None or _number(v) < 0 for v in weights.values()) or sum((_number(v) for v in weights.values()), Decimal(0)) != 1:
                continue
            consistent_ranked = []
            for r in ranked:
                c = authorized.get(r.get('instrument_id')) if isinstance(r, dict) else None
                scores = c.get('scores') if c else None
                if not isinstance(scores, dict) or not all(_number(scores.get(k)) is not None and 0 <= _number(scores[k]) <= 1 for k in weights):
                    continue
                expected_score = sum((_number(v) * _number(scores[k]) for k, v in weights.items()), Decimal(0))
                if _number(r.get('score')) == expected_score:
                    consistent_ranked.append(r)
            ranked = consistent_ranked
            own = next((r for r in ranked if isinstance(r, dict) and r.get('instrument_id') == subject and subject in authorized), None)
            alternatives = [r for r in ranked if isinstance(r, dict) and r.get('instrument_id') != subject
                            and r.get('instrument_id') in authorized and _number(r.get('score')) is not None]
            if own and alternatives and _number(own.get('score')) is not None:
                best = max(alternatives, key=lambda r: _number(r['score']))
                text = 'Strongest supplied alternative by evidenced priority score: ' + best['instrument_id']
                text += '; alternative score=' + str(best['score']) + '; subject score=' + str(own['score'])
                text += '. This score is not expected risk-adjusted CAGR; scenarios are conditional and rotation requires net frictions.'
                assess('alternative_opportunity', text, TOPIC_ACTIONS['alternative_opportunity'], evidence_ids=capital_ids)
            if own:
                flags = _strings(own.get('flags', ()))
                assess('concentration_justification', 'Authorized capital analysis flags: ' + (', '.join(flags) or 'No concentration flag reported')
                       + '. Scores/scenarios support comparison but cannot independently approve a concentration or a sale.',
                       TOPIC_ACTIONS['concentration_justification'], evidence_ids=capital_ids)
        # Each qualitative statement requires an approved content-verified primary
        # disclosure. A numeric threshold is evaluated only when supplied there.
        topic_records = {topic: [] for topic in TOPICS}
        for eid, row in evidence.items():
            if not _eligible(row, run.run_id, cutoff, subject) or not _primary_disclosure(row):
                continue
            for topic, record in _object(row.get('metadata_json'))['adversarial_disclosures'].items():
                if topic in topic_records and isinstance(record, dict):
                    topic_records[topic].append((eid, record))
        for topic, records in topic_records.items():
            if not records:
                continue
            signatures = {json.dumps(record, sort_keys=True) for _, record in records}
            if len(signatures) > 1:
                assess(topic, 'Conflicting approved disclosure assessments; no consolidated conclusion inferred.',
                       'Reconcile source statements and their dates.', evidence_ids=tuple(eid for eid, _ in records))
                continue
            eid, record = records[0]
            fields = ('statement', 'adverse_condition', 'thesis_breaker')
            if not all(isinstance(record.get(k), str) and record[k].strip() for k in fields):
                continue
            condition = 'Qualitative condition; no probability inferred.'
            numeric_keys = ('observed_value', 'operator', 'threshold', 'unit')
            if any(k in record for k in numeric_keys):
                left, right = _number(record.get('observed_value')), _number(record.get('threshold'))
                operator = record.get('operator')
                unit = record.get('unit')
                if left is None or right is None or operator not in {'>', '>=', '<', '<=', '=='} or not isinstance(unit, str) or not unit.strip():
                    continue
                met = {'>': left > right, '>=': left >= right, '<': left < right, '<=': left <= right, '==': left == right}[operator]
                condition = 'Supplied adverse condition=' + ('MET' if met else 'NOT_MET') + '; observed=' + str(left) + ' ' + operator + ' threshold=' + str(right) + ' ' + unit + '. No future probability inferred.'
            assess(topic, record['statement'] + ' Adverse condition: ' + record['adverse_condition'] + ' ' + condition,
                   'Thesis-breaker response: ' + record['thesis_breaker'], status='REVIEWED', evidence_ids=(eid,))
        assess('missing_data', 'Missing inputs/source validation: ' + (', '.join(unknowns) or 'No numeric gap reported; qualitative coverage evaluated separately.')
               + ('' if sources else ' No supported asset-level calculation output exists for this subject.'),
               'Recover missing disclosures before affirming concentration, capital rotation or an investment conclusion.', status='REVIEWED')
        missing_topics = tuple(topic for topic, assessment in assessments.items() if assessment['status'] != 'REVIEWED')
        status = 'PARTIAL' if missing_topics or unknowns or not sources else 'AVAILABLE'
        calc_id = 'calc:adversarial:' + uuid4().hex
        payload = {'subject': subject, 'review_level': 3, 'status': status, 'assessments': assessments,
                   'missing_topics': missing_topics, 'missing_inputs': unknowns, 'review_triggers': tuple(review_triggers),
                   'observed_risks': tuple(dict.fromkeys(risk for output in outputs for risk in _strings(output.get('risks', ())))),
                   'source_output_count': len(sources), 'concentration_is_automatic_sell': False}
        run.add_calculation(calculation_id=calc_id, calculation_name='adversarial_review',
                            formula='eligible same-run asset outputs + approved primary disclosure -> adversarial condition assessments',
                            inputs={'evidence_ids': sorted(refs), 'source_calculation_ids': list(dict.fromkeys(source_refs)),
                                    'analysis_as_of': metadata['analysis_as_of'], 'required_subject': subject,
                                    'review_triggers': list(review_triggers)}, result=payload)
        finding = ReviewFinding(FindingSeverity.MEDIUM, 'LEVEL3_ADVERSARIAL_DATA_GAPS' if status == 'PARTIAL' else 'LEVEL3_ADVERSARIAL_REVIEW',
                                subject + ': reviewed ' + str(len(TOPICS) - len(missing_topics)) + ' of ' + str(len(TOPICS)) + ' topics; incomplete: ' + ', '.join(missing_topics),
                                metadata={**payload, 'calculation_id': calc_id,
                                          'topic_status': {k: v['status'] for k, v in assessments.items()}})
        findings.append(finding)
        run.add_review_finding(finding_id='review:adversarial:' + uuid4().hex, severity=finding.severity.value,
                               status='OPEN', finding_text='[' + finding.code + '] ' + finding.text)
        run.record_task_state(task_name='adversarial_review:' + subject, task_status=status,
                              metadata={**payload, 'calculation_id': calc_id})
    return replace(result, required=result.required or bool(findings), findings=(*result.findings, *findings))
