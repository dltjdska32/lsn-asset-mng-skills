"""Append-only execution receipts in the existing run-local task ledger."""
from contextlib import contextmanager
from datetime import datetime, timezone


def now():
    return datetime.now(timezone.utc).isoformat()


def record_stage(run, name, status, *, started_at=None, input_count=0,
                 output_count=0, evidence_count=0, reason=None, dependency=None):
    mode = run.fetch_phase6_context().get('run_metadata', {}).get('request_mode')
    run.record_task_state(task_name='stage:' + name, task_status=status, metadata={
        'run_id': run.run_id, 'request_mode': mode, 'stage_name': name,
        'started_at': started_at, 'completed_at': None if status in {'PLANNED', 'RUNNING'} else now(),
        'input_count': input_count, 'output_count': output_count,
        'evidence_count': evidence_count, 'dependency_stage': dependency,
        'failure_reason': reason if status in {'FAILED', 'BLOCKED'} else None,
        'partial_reason': reason if status == 'PARTIAL' else None,
    })


@contextmanager
def analysis_stage(run, name, *, input_count=0, evidence_count=0, dependency=None):
    started = now()
    record_stage(run, name, 'RUNNING', started_at=started, input_count=input_count,
                 evidence_count=evidence_count, dependency=dependency)
    receipt = {'status': 'SUCCESS', 'output_count': 0, 'reason': None}
    try:
        yield receipt
    except Exception as exc:
        record_stage(run, name, 'FAILED', started_at=started, input_count=input_count,
                     evidence_count=evidence_count, reason=type(exc).__name__, dependency=dependency)
        raise
    else:
        record_stage(run, name, receipt['status'], started_at=started,
                     input_count=input_count, output_count=receipt['output_count'],
                     evidence_count=evidence_count, reason=receipt['reason'], dependency=dependency)


def verified_equity_outputs(run, outcomes):
    """Reject synthetic/task-only research and outputs from another run."""
    stored = {r['calculation_id']: r for r in run.fetch_phase6_context()['calculations']}
    problems = []
    for outcome in outcomes:
        for label, result in [('FUNDAMENTAL', outcome.analysis.fundamental),
                              ('VALUATION', outcome.analysis.valuation)]:
            ref = result.metadata.get('calculation_id')
            row = stored.get(ref)
            if row is None or row.get('run_id') != run.run_id:
                problems.append(outcome.instrument_id + ':' + label + '_STAGE_NOT_EXECUTED')
    return tuple(problems)
