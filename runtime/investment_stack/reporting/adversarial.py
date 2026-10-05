"""Render only same-run adversarial assessments with eligible persisted lineage."""
import json
from .models import Availability, ReportSectionInput, Confidence
from investment_stack.review.models import ReviewResult
from investment_stack.review.adversarial import TOPICS, _object, _time, _eligible, _strings, review_valuation_outputs


class _ReadOnlyReplay:
    """Recompute against the frozen context without any run.db writer calls."""
    def __init__(self, run_id, context):
        self.run_id,self.context,self.outputs=run_id,context,{}
    def fetch_phase6_context(self):
        return self.context
    def add_calculation(self, **record):
        self.outputs[record['result']['subject']]=record
    def add_review_finding(self, **_record):
        pass
    def record_task_state(self, **_record):
        pass


def _canonical(value):
    return json.dumps(value,sort_keys=True,default=str)


def adversarial_sections(run):
    context = run.fetch_phase6_context()
    meta = context.get('run_metadata') or {}
    cutoff = _time(meta.get('analysis_as_of'))
    evidence = {r['evidence_id']: r for r in context.get('evidence', ()) if r.get('run_id') == run.run_id}
    calculations = {r['calculation_id']: r for r in context.get('calculations', ()) if r.get('run_id') == run.run_id}
    sections = []
    replay_cache={}
    for row in calculations.values():
        if row.get('calculation_name') != 'adversarial_review':
            continue
        output, inputs = _object(row.get('result_json')), _object(row.get('inputs_json'))
        subject = output.get('subject')
        if not isinstance(subject, str) or not subject or output.get('review_level') != 3:
            continue
        refs = _strings(inputs.get('evidence_ids', ()))
        sources = _strings(inputs.get('source_calculation_ids', ()))
        triggers=_strings(output.get('review_triggers',()))
        if triggers not in replay_cache:
            replay=_ReadOnlyReplay(run.run_id,context)
            subjects=tuple(_object(r.get('result_json')).get('subject') for r in calculations.values()
                           if r.get('calculation_name')=='adversarial_review')
            review_valuation_outputs(replay,ReviewResult(False,(),(),Confidence.MEDIUM),
                                     required_subjects=subjects,review_triggers=triggers)
            replay_cache[triggers]=replay.outputs
        expected=replay_cache[triggers].get(subject)
        valid = (inputs.get('analysis_as_of') == meta.get('analysis_as_of')
                 and all(_eligible(evidence.get(ref), run.run_id, cutoff) for ref in refs)
                 and all(ref in calculations for ref in sources)
                 and expected is not None
                 and _canonical(output)==_canonical(expected['result'])
                 and _canonical(inputs)==_canonical(expected['inputs']))
        if valid:
            for ref in sources:
                source_refs = _strings(_object(calculations[ref].get('inputs_json')).get('evidence_ids', ()))
                if not all(_eligible(evidence.get(eid), run.run_id, cutoff) for eid in source_refs):
                    valid = False
                    break
        assessments = output.get('assessments')
        if not isinstance(assessments, dict) or not valid:
            sections.append(ReportSectionInput(subject + '_adversarial_review', subject + ' Level 3 Review',
                ('저장된 검토 결과의 동일 run·기준시각·근거 결속을 확인할 수 없어 내용을 숨겼습니다.',),
                status=Availability.UNAVAILABLE, calculation_ids=(row['calculation_id'],)))
            continue
        complete_topics = sum(isinstance(assessments.get(topic), dict)
                              and assessments[topic].get('status') == 'REVIEWED'
                              and all(isinstance(assessments[topic].get(k), str) for k in ('assessment', 'action'))
                              and set(_strings(assessments[topic].get('evidence_ids', ()))) <= set(refs)
                              and (topic == 'missing_data' or bool(_strings(assessments[topic].get('evidence_ids', ()))))
                              for topic in TOPICS)
        complete = (output.get('status') == 'AVAILABLE' and complete_topics == len(TOPICS)
                    and not _strings(output.get('missing_inputs', ()))
                    and type(output.get('source_output_count')) is int and output['source_output_count'] > 0)
        lines = ['검토 상태=' + ('AVAILABLE' if complete else 'PARTIAL')
                 + '; 완료한 논점=' + str(complete_topics) + '/' + str(len(TOPICS)) + '. 미완료 논점이 있으면 투자·집중·재배치 판단을 확정하지 않습니다.']
        for topic in TOPICS:
            item = assessments.get(topic)
            if not isinstance(item, dict) or not all(isinstance(item.get(k), str) for k in ('status', 'assessment', 'action')):
                lines.append(topic + ': UNAVAILABLE; 검토 출력 구조 확인 불가')
                continue
            topic_refs = _strings(item.get('evidence_ids', ()))
            if not all(ref in refs for ref in topic_refs):
                lines.append(topic + ': UNAVAILABLE; 검토 근거 확인 불가')
                complete = False
                continue
            lines.append(topic + ': ' + item['status'] + '; ' + item['assessment'] + ' Action: ' + item['action']
                         + '; evidence=' + ','.join(topic_refs))
        lines.append('Source calculations: ' + (', '.join(sources) or '없음; 실제 자산 출력 미확보'))
        sections.append(ReportSectionInput(subject + '_adversarial_review', subject + ' Level 3 Review', tuple(lines),
                         status=Availability.AVAILABLE if complete else Availability.PARTIAL,
                         evidence_ids=refs, calculation_ids=(row['calculation_id'], *sources),
                         metadata={'review_level': 3, 'review_complete': complete,
                                   'numeric_output_verified': True, 'source_calculation_ids': sources}))
    return tuple(sections)
