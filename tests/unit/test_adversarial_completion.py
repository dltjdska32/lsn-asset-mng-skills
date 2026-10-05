import json
import unittest
from dataclasses import replace

from investment_stack.review.adversarial import review_valuation_outputs, TOPICS
from investment_stack.review.models import ReviewResult
from investment_stack.reporting.models import Confidence, Availability
from investment_stack.reporting.adversarial import adversarial_sections


PIN = '2026-10-05T00:00:00+00:00'


class SyntheticReviewRun:
    def __init__(self):
        self.run_id = 'review-synthetic'
        self.context = {'run_metadata': {'run_id': self.run_id, 'analysis_as_of': PIN},
                        'evidence': [], 'calculations': []}
        self.findings, self.tasks = [], []

    def fetch_phase6_context(self):
        return self.context

    def evidence(self, iid='A', *, metadata=None, evidence_id='ev', **kwargs):
        row = {'run_id': self.run_id, 'evidence_id': evidence_id, 'instrument_id': iid,
               'source_tier': 1, 'selection_state': 'SELECTED', 'freshness_status': 'FRESH',
               'observed_at': PIN, 'published_at': PIN, 'retrieved_at': '2026-10-05T00:05:00+00:00',
               'metadata_json': json.dumps(metadata or {'calculation_input_approved': True}), **kwargs}
        self.context['evidence'].append(row)
        return row

    def calculation(self, name='EQUITY_VALUATION', iid='A', metrics=None, metadata=None, unknowns=None, refs=('ev',)):
        cid = name + ':' + iid + ':' + str(len(self.context['calculations']))
        self.add_calculation(calculation_id=cid, calculation_name=name, formula='synthetic_fixture',
                             inputs={'evidence_ids': list(refs)},
                             result={'subject': iid, 'analysis_type': name, 'status': 'PARTIAL', 'metadata': metadata,
                                     'metrics': metrics or [], 'unknowns': unknowns or []})
        return cid

    def add_calculation(self, **kwargs):
        self.context['calculations'].append({**kwargs, 'run_id': self.run_id,
            'inputs_json': json.dumps(kwargs['inputs']), 'result_json': json.dumps(kwargs['result'])})

    def add_review_finding(self, **kwargs):
        self.findings.append(kwargs)

    def record_task_state(self, **kwargs):
        self.tasks.append(kwargs)

    def reviews(self):
        return [json.loads(r['result_json']) for r in self.context['calculations'] if r['calculation_name'] == 'adversarial_review']


def metric(name, value='20', refs=('ev',)):
    return {'name': name, 'value': value, 'status': 'COMPLETE', 'evidence_ids': list(refs)}


def initial():
    return ReviewResult(False, (), (), Confidence.MEDIUM)


def disclosure_records():
    return {topic: {'statement': 'Documented exposure for ' + topic,
                    'adverse_condition': 'Source-disclosed event occurs',
                    'thesis_breaker': 'Reassess when source-disclosed condition occurs'} for topic in TOPICS}


class AdversarialCompletionTests(unittest.TestCase):
    def test_ratio_only_executes_fifteen_topics_but_is_partial(self):
        run = SyntheticReviewRun()
        run.evidence()
        run.calculation(metrics=[metric('ev_to_ebitda')])
        result = review_valuation_outputs(run, initial())
        output = run.reviews()[0]
        self.assertTrue(result.required)
        self.assertEqual(len(output['assessments']), len(TOPICS))
        self.assertEqual(output['status'], 'PARTIAL')
        self.assertEqual(output['assessments']['priced_in_expectations']['metrics']['ev_to_ebitda'], '20')
        self.assertIn('customer_concentration', output['missing_topics'])

    def test_required_fund_high_concentration_executes_actual_review(self):
        run = SyntheticReviewRun()
        run.evidence(iid='ETF')
        source = run.calculation(name='FUND', iid='ETF', metrics=[metric('top10_concentration', '.5')])
        review_valuation_outputs(run, initial(), required_subjects=('ETF',), review_triggers=('SINGLE_ASSET_OVER_30_PERCENT',))
        output = run.reviews()[0]
        self.assertEqual(output['subject'], 'ETF')
        self.assertEqual(output['review_level'], 3)
        self.assertIn('SINGLE_ASSET_OVER_30_PERCENT', output['review_triggers'])
        self.assertIn('Fund structure', output['assessments']['strongest_bear_case']['assessment'])
        self.assertIn(source, json.loads(run.context['calculations'][-1]['inputs_json'])['source_calculation_ids'])

    def test_required_subject_without_outputs_reports_gap(self):
        run = SyntheticReviewRun()
        review_valuation_outputs(run, initial(), required_subjects=('MISSING',))
        output = run.reviews()[0]
        self.assertEqual(output['status'], 'PARTIAL')
        self.assertEqual(output['source_output_count'], 0)
        self.assertIn('usable_asset_output_unavailable', output['missing_inputs'])

    def test_null_metadata_and_malformed_json_do_not_crash(self):
        run = SyntheticReviewRun()
        run.evidence()
        run.calculation(metrics=[metric('pe')], metadata=None)
        run.context['calculations'].append({'run_id': run.run_id, 'calculation_id': 'malformed',
            'calculation_name': 'EQUITY_FUNDAMENTAL', 'result_json': '[null]', 'inputs_json': 'invalid'})
        review_valuation_outputs(run, initial())
        self.assertEqual(run.reviews()[0]['status'], 'PARTIAL')

    def test_future_rejected_crossrun_evidence_not_consumed(self):
        for changes in ({'published_at': '2026-10-06T00:00:00+00:00'}, {'selection_state': 'REJECTED'}, {'run_id': 'other'}, {'freshness_status': 'STALE'}):
            run = SyntheticReviewRun()
            run.evidence(**changes)
            run.calculation(metrics=[metric('pe', '999')])
            review_valuation_outputs(run, initial())
            output = run.reviews()[0]
            self.assertNotIn('999', json.dumps(output))
            self.assertEqual(json.loads(run.context['calculations'][-1]['inputs_json'])['evidence_ids'], [])

    def test_approved_disclosure_condition_is_evaluated_with_source(self):
        run = SyntheticReviewRun()
        records = disclosure_records()
        records['debt'].update(observed_value='3', operator='>', threshold='2', unit='ratio')
        run.evidence(metadata={'calculation_input_approved': True, 'disclosure_content_verified': True,
                               'adversarial_disclosures': records})
        run.calculation(metrics=[metric('pe')])
        review_valuation_outputs(run, initial())
        output = run.reviews()[0]
        self.assertEqual(output['status'], 'AVAILABLE')
        self.assertIn('condition=MET', output['assessments']['debt']['assessment'])
        self.assertEqual(output['assessments']['debt']['evidence_ids'], ['ev'])

    def test_unapproved_or_unverified_disclosure_never_fills_topic(self):
        for metadata in ({'calculation_input_approved': True, 'disclosure_content_verified': False},
                         {'calculation_input_approved': False, 'disclosure_content_verified': True}):
            run = SyntheticReviewRun()
            run.evidence(metadata={**metadata, 'adversarial_disclosures': disclosure_records()})
            run.calculation(metrics=[metric('pe')])
            review_valuation_outputs(run, initial())
            self.assertIn('technology_substitution', run.reviews()[0]['missing_topics'])

    def test_different_primary_statements_remain_conflicting(self):
        run = SyntheticReviewRun()
        for eid, statement in (('ev', 'Exposure one'), ('ev2', 'Exposure two')):
            records = disclosure_records()
            records['cyclicality']['statement'] = statement
            run.evidence(evidence_id=eid, metadata={'calculation_input_approved': True,
                'disclosure_content_verified': True, 'adversarial_disclosures': {'cyclicality': records['cyclicality']}})
        run.calculation(metrics=[metric('pe')])
        review_valuation_outputs(run, initial())
        self.assertIn('Conflicting', run.reviews()[0]['assessments']['cyclicality']['assessment'])
        self.assertIn('cyclicality', run.reviews()[0]['missing_topics'])

    def test_reporting_validates_same_run_refs_and_hides_tampered_evidence(self):
        run = SyntheticReviewRun()
        ev = run.evidence()
        run.calculation(metrics=[metric('pe')])
        review_valuation_outputs(run, initial())
        section = adversarial_sections(run)[0]
        self.assertEqual(section.status, Availability.PARTIAL)
        self.assertIn('ev', section.evidence_ids)
        self.assertEqual(len(section.lines), len(TOPICS) + 2)
        ev['selection_state'] = 'REJECTED'
        hidden = adversarial_sections(run)[0]
        self.assertEqual(hidden.status, Availability.UNAVAILABLE)
        self.assertNotIn('pe=20', ' '.join(hidden.lines))

    def test_crossrun_calculation_does_not_create_review_for_its_subject(self):
        run = SyntheticReviewRun()
        run.evidence(iid='OTHER')
        run.calculation(iid='OTHER', metrics=[metric('pe')])
        run.context['calculations'][0]['run_id'] = 'other'
        result = review_valuation_outputs(run, initial())
        self.assertFalse(run.reviews())
        self.assertFalse(result.required)

    def test_explicit_missing_inputs_prevent_review_completion(self):
        run = SyntheticReviewRun()
        run.evidence(metadata={'calculation_input_approved': True, 'disclosure_content_verified': True,
                               'adversarial_disclosures': disclosure_records()})
        run.calculation(metrics=[metric('pe')], unknowns=['debt_maturity'])
        review_valuation_outputs(run, initial())
        self.assertEqual(run.reviews()[0]['status'], 'PARTIAL')
        self.assertIn('debt_maturity', run.reviews()[0]['missing_inputs'])

    def test_empty_placeholder_output_cannot_complete_review(self):
        run = SyntheticReviewRun()
        run.evidence(metadata={'calculation_input_approved': True, 'disclosure_content_verified': True,
                               'adversarial_disclosures': disclosure_records()})
        run.calculation(metrics=[])
        review_valuation_outputs(run, initial())
        self.assertEqual(run.reviews()[0]['status'], 'PARTIAL')

    def test_metric_refs_must_belong_to_its_source_calculation(self):
        run = SyntheticReviewRun()
        run.evidence()
        run.calculation(metrics=[metric('pe', '999')], refs=())
        review_valuation_outputs(run, initial())
        output = run.reviews()[0]
        self.assertNotIn('999', json.dumps(output))
        self.assertIn('metric_lineage_unavailable:pe', output['missing_inputs'])

    def test_null_metrics_source_is_unavailable_without_exception(self):
        run = SyntheticReviewRun()
        run.evidence()
        run.calculation()
        row = run.context['calculations'][0]
        payload = json.loads(row['result_json'])
        payload['metrics'] = None
        row['result_json'] = json.dumps(payload)
        review_valuation_outputs(run, initial())
        self.assertEqual(run.reviews()[0]['status'], 'PARTIAL')

    def test_correlation_and_growth_stress_need_explicit_evidence(self):
        run = SyntheticReviewRun()
        run.evidence()
        run.calculation(metrics=[metric('pe')])
        review_valuation_outputs(run, initial(), required_subjects=('A',), review_triggers=('TOP_TWO_OVER_50_PERCENT',))
        output = run.reviews()[0]
        self.assertEqual(output['assessments']['core_holding_correlation']['status'], 'UNAVAILABLE')
        self.assertEqual(output['assessments']['growth_slowdown']['status'], 'UNAVAILABLE')
        self.assertIn('30-50%', output['assessments']['growth_slowdown']['action'])
        self.assertNotIn('metrics', output['assessments']['growth_slowdown'])
        self.assertIn('not a sell instruction', output['assessments']['concentration_justification']['assessment'])

    def test_authorized_capital_scores_compare_strongest_alternative_conditionally(self):
        from tests.unit.test_capital_competition import SyntheticRun, candidate, portfolio
        from investment_stack.execution.capital_competition import render_capital_competition, CapitalCompetitionPolicyInputs
        run = SyntheticRun()
        assets = (run.approved(candidate('A', score='.5')), run.approved(candidate('B', score='.9', weight='.2')))
        render_capital_competition(run, *portfolio(), CapitalCompetitionPolicyInputs(assets))
        run.add_review_finding = lambda **kwargs: None
        run.record_task_state = lambda **kwargs: None
        review_valuation_outputs(run, initial(), required_subjects=('A',))
        output = json.loads(run.snapshot['calculations'][-1]['result_json'])
        alternative = output['assessments']['alternative_opportunity']
        self.assertEqual(alternative['status'], 'CONDITIONAL')
        self.assertIn('alternative by evidenced priority score: B', alternative['assessment'])
        self.assertIn('not expected risk-adjusted CAGR', alternative['assessment'])
        self.assertIn('alternative_opportunity', output['missing_topics'])
        self.assertIn('CAPITAL_COMPETITION', [r['calculation_name'] for r in run.snapshot['calculations']])

    def complete_review_fixture(self):
        run=SyntheticReviewRun()
        ev=run.evidence(metadata={'calculation_input_approved':True,
            'disclosure_content_verified':True,'adversarial_disclosures':disclosure_records()})
        run.calculation(metrics=[metric('pe')])
        review_valuation_outputs(run,initial())
        self.assertEqual(adversarial_sections(run)[0].status,Availability.AVAILABLE)
        return run,ev

    def test_report_rejects_boolean_count_and_absent_actual_source_outputs(self):
        for count in (True,1):
            run,_=self.complete_review_fixture()
            row=run.context['calculations'][-1]
            output=json.loads(row['result_json']);output['source_output_count']=count
            inputs=json.loads(row['inputs_json']);inputs['source_calculation_ids']=[]
            row['result_json']=json.dumps(output);row['inputs_json']=json.dumps(inputs)
            self.assertEqual(adversarial_sections(run)[0].status,Availability.UNAVAILABLE)

    def test_report_replays_primary_disclosure_approval_and_topic_content(self):
        for mutation in ('verification','statement','threshold'):
            run,ev=self.complete_review_fixture()
            metadata=json.loads(ev['metadata_json'])
            if mutation=='verification':metadata['disclosure_content_verified']=False
            elif mutation=='statement':metadata['adversarial_disclosures']['cyclicality']['statement']='Changed source statement'
            else:metadata['adversarial_disclosures']['debt'].update(observed_value='10',operator='>',threshold='20',unit='ratio')
            ev['metadata_json']=json.dumps(metadata)
            self.assertEqual(adversarial_sections(run)[0].status,Availability.UNAVAILABLE)

    def test_report_recomputation_does_not_write_tasks_findings_or_calculations(self):
        run,_=self.complete_review_fixture()
        before=(len(run.context['calculations']),len(run.findings),len(run.tasks))
        self.assertEqual(adversarial_sections(run)[0].status,Availability.AVAILABLE)
        self.assertEqual(before,(len(run.context['calculations']),len(run.findings),len(run.tasks)))

    def test_unauthorized_capital_scores_do_not_generate_alternative_claim(self):
        run = SyntheticReviewRun()
        run.evidence()
        run.calculation(metrics=[metric('pe')])
        run.add_calculation(calculation_id='bad-capital', calculation_name='CAPITAL_COMPETITION', formula='tampered',
            inputs={'evidence_ids': ['ev'], 'candidates': [{'instrument_id': 'A'}, {'instrument_id': 'B'}], 'source_calculation_ids': []},
            result={'ranked': [{'instrument_id': 'A', 'score': '.5'}, {'instrument_id': 'B', 'score': '.99'}]})
        review_valuation_outputs(run, initial())
        self.assertEqual(run.reviews()[0]['assessments']['alternative_opportunity']['status'], 'UNAVAILABLE')


if __name__ == '__main__':
    unittest.main()
