"""Whole-universe lightweight receipts and explicit read-only prior import."""
from contextlib import closing
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from investment_stack.calculations.capital_competition import DIMENSIONS
from investment_stack.execution.capital_competition import _decode, _eligible, _time

METRICS = {d + '_score' for d in DIMENSIONS} | {'revenue_growth', 'roe', 'pe', 'debt_to_equity', 'industry_growth_rate'}

def persist_lightweight_baseline(run, instrument_ids):
    context = run.fetch_phase6_context()
    cutoff = _time(context['run_metadata']['analysis_as_of'])
    ids = tuple(dict.fromkeys(instrument_ids))
    receipts = []
    for iid in ids:
        selected = [e for e in context['evidence'] if e.get('metric') in METRICS
            and not _decode(e.get('metadata_json')).get('imported_from_run_id')
            and _eligible(e, run.run_id, cutoff, instrument=iid)]
        metrics = []
        for e in selected:
            try:
                value = Decimal(str(json.loads(e['value_text'])))
            except (ValueError, TypeError, ArithmeticError):
                continue
            md = _decode(e.get('metadata_json'))
            if not value.is_finite() or (e['metric'].endswith('_score') and (not 0 <= value <= 1 or not md.get('assessment_rationale'))):
                continue
            metrics.append({'name': e['metric'], 'value': str(value), 'status': 'COMPLETE', 'evidence_ids': [e['evidence_id']]})
        cid = 'calc:portfolio-lightweight:' + uuid4().hex
        run.add_calculation(calculation_id=cid, calculation_name='PORTFOLIO_LIGHTWEIGHT',
            formula='validated_selected_lightweight_metrics_no_imputation_v1',
            inputs={'evidence_ids': [e['evidence_id'] for e in selected], 'universe': list(ids)},
            result={'subject': iid, 'metrics': metrics, 'status': 'COMPLETE' if metrics else 'PARTIAL',
                    'missing_reason': None if metrics else 'NO_VALIDATED_LIGHTWEIGHT_SCORE_FACTS'})
        receipts.append(cid)
    return tuple(receipts)

def import_prior_research(run, previous_run_db, instrument_ids):
    """Import only explicitly validity-bounded research, never trust old FRESH.

    Prior sources without a declared source-validity window are withheld. A
    fresh-looking retrieval date cannot extend original observation validity.
    Original evidence identity and all three timestamps are preserved.
    """
    current = run.fetch_phase6_context()
    cutoff = _time(current['run_metadata']['analysis_as_of'])
    with closing(sqlite3.connect(Path(previous_run_db).resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        meta = dict(conn.execute('SELECT * FROM run_metadata').fetchone())
        pin = dict(conn.execute('SELECT * FROM pinned_personal_state').fetchone())
        if (meta['request_mode'] != current['run_metadata']['request_mode']
                or _time(meta['analysis_as_of']) >= cutoff
                or pin['personal_db_instance_id'] != current['pinned_personal_state']['personal_db_instance_id']):
            raise ValueError('prior research must have an earlier clock, same mode and personal database identity')
        evidence = {r['evidence_id']: dict(r) for r in conn.execute('SELECT * FROM evidence')}
        calculations = [dict(r) for r in conn.execute('SELECT * FROM calculations')]
    imported = []
    allowed = {'EQUITY_FUNDAMENTAL', 'EQUITY_VALUATION', 'FUND', 'PORTFOLIO_LIGHTWEIGHT'}
    for calc in calculations:
        output = _decode(calc.get('result_json'))
        iid = output.get('subject')
        refs = _decode(calc.get('inputs_json')).get('evidence_ids', [])
        if calc.get('run_id') != meta['run_id'] or calc['calculation_name'] not in allowed or iid not in instrument_ids or not refs:
            continue
        rows = [evidence.get(ref) for ref in refs]
        valid = True
        for e in rows:
            if not e or not _eligible(e, meta['run_id'], cutoff, instrument=iid) or e.get('official_confirmation_status') not in {'CONFIRMED', 'OFFICIAL'}:
                valid = False
                break
            md = _decode(e.get('metadata_json'))
            # This is an explicit source contract, not an arbitrary freshness TTL.
            until = md.get('research_valid_until')
            try:
                valid = (_time(e['observed_at']) <= cutoff <= _time(until)
                         and _time(until) >= _time(e['observed_at']) and _time(e['retrieved_at']) <= cutoff)
            except (ValueError, TypeError):
                valid = False
            if not valid:
                break
        if not valid:
            continue
        mappings = {}
        for e in rows:
            eid = 'prior:' + uuid4().hex
            md = {**_decode(e.get('metadata_json')), 'imported_from_run_id': meta['run_id'],
                'original_evidence_id': e['evidence_id'], 'original_calculation_id': calc['calculation_id']}
            run.add_phase4_evidence(evidence_id=eid, evidence_type=e['evidence_type'],
                source_uri=e['source_uri'], retrieved_at=e['retrieved_at'], instrument_id=iid,
                metric=e.get('metric'), value=json.loads(e['value_text'] or 'null'), currency=e.get('currency'),
                unit=e.get('unit'), source_name=e.get('source_name'), source_tier=e.get('source_tier'),
                provider_id=e.get('provider_id'), headline=e.get('headline'),
                observed_at=e['observed_at'], published_at=e['published_at'], freshness_status='FRESH',
                official_confirmation_status='CONFIRMED', metadata=md)
            run.mark_evidence_selected(evidence_id=eid, reason='explicit validated prior import; source timestamps preserved')
            mappings[e['evidence_id']] = eid
        metrics = []
        for metric in output.get('metrics', ()):
            bindings = metric.get('evidence_ids', [])
            if bindings and set(bindings) <= mappings.keys():
                metrics.append({**metric, 'evidence_ids': [mappings[e] for e in bindings]})
        cid = 'calc:validated-prior:' + uuid4().hex
        run.add_calculation(calculation_id=cid, calculation_name='VALIDATED_PRIOR_RESEARCH',
            formula='explicit_validity_bounded_prior_import_v1',
            inputs={'evidence_ids': list(mappings.values()), 'source_run_id': meta['run_id'],
                'source_calculation_id': calc['calculation_id']}, result={'subject': iid, 'metrics': metrics})
        imported.append(cid)
    run.record_task_state(task_name='validated_prior_import', task_status='COMPLETE' if imported else 'PARTIAL',
        metadata={'imported_calculation_count': len(imported), 'reason': None if imported else 'NO_ELIGIBLE_VALIDITY_BOUNDED_PRIOR_RESEARCH'})
    return tuple(imported)
