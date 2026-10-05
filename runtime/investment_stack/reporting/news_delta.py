"""Render only same-run dated news impact assessments."""
import json
from .models import ReportSectionInput, Availability


def news_delta_section(run, instrument_id):
    context = run.fetch_phase6_context()
    rows = [r for r in context['calculations'] if r['calculation_name'] == 'news_thesis_impact'
            and json.loads(r['result_json'] or '{}').get('subject') == instrument_id]
    lines, refs, calcs = [], [], []
    for row in rows:
        output = json.loads(row['result_json'])
        calcs.append(row['calculation_id'])
        refs.extend(json.loads(row['inputs_json']).get('evidence_ids', ()))
        for event in output['events']:
            lines.append(event['headline'] + '; published=' + str(event['published_at']) +
                         '; confirmation=' + str(event['confirmation']) + '; thesis impact=' + event['thesis_impact'])
    if not lines:
        lines = ['No verified material news delta supplied; thesis impact unavailable.']
    return ReportSectionInput(instrument_id + '_news_delta', instrument_id + ' News and thesis impact',
                              tuple(lines), status=Availability.PARTIAL,
                              evidence_ids=tuple(dict.fromkeys(refs)), calculation_ids=tuple(calcs))
