import json
import unittest
from dataclasses import replace
from decimal import Decimal as D
from types import SimpleNamespace

from investment_stack.calculations.capital_competition import (
    CapitalCandidate, CapitalScenario, CapitalCategory, CompetitionPolicy,
    DIMENSIONS, analyze_capital_competition,
)
from investment_stack.execution.capital_competition import (
    AuthorizedCapitalInput, CapitalCompetitionPolicyInputs, render_capital_competition,
    json_value, TITLES,
)
from investment_stack.reporting.portfolio_modes import PortfolioPosition


AS_OF = '2026-10-05T00:00:00+00:00'


def candidate(iid, *, score='.9', growth='.15', weight='.3', held=True):
    bindings = {k: 'facts:' + iid for k in ('earnings_per_share', 'earnings_growth', 'annual_dilution', 'terminal_multiple', 'dividends_per_share')}
    scenarios = tuple(CapitalScenario(name, D('1'), rate, D('0'), D('20'), D('0'), bindings)
                      for name, rate in (('bear', D('-.1')), ('base', D(growth)), ('bull', D('.35'))))
    return CapitalCandidate(iid, held, D(weight) if held else None,
                            {k: D(score) for k in DIMENSIONS}, {k: 'facts:' + iid for k in DIMENSIONS},
                            scenarios, D('20'), 'price:' + iid, True)


class SyntheticRun:
    def __init__(self):
        self.run_id = 'synthetic-capital'
        self.snapshot = {'run_metadata': {'run_id': self.run_id, 'analysis_as_of': AS_OF},
                         'pinned_personal_state': {'state_version': 1, 'portfolio_snapshot_id': 'snap'},
                         'evidence': [], 'calculations': []}
        self.add_calculation(calculation_id='portfolio', calculation_name='portfolio_analysis',
            inputs={'state_version': 1, 'snapshot_ref': 'snap'}, result={'gross_assets': '100'})

    def fetch_phase6_context(self):
        return self.snapshot

    def add_calculation(self, **kwargs):
        self.snapshot['calculations'].append({**kwargs, 'run_id': self.run_id,
            'inputs_json': json.dumps(kwargs['inputs']), 'result_json': json.dumps(kwargs['result'])})

    def approved(self, c):
        for eid in ('facts:' + c.instrument_id, 'price:' + c.instrument_id, 'approval:' + c.instrument_id):
            self.snapshot['evidence'].append({'evidence_id': eid, 'run_id': self.run_id,
                'instrument_id': c.instrument_id, 'selection_state': 'SELECTED', 'freshness_status': 'FRESH',
                'observed_at': AS_OF, 'published_at': AS_OF, 'retrieved_at': AS_OF,
                'metric': 'current_price' if eid.startswith('price:') else 'policy', 'value_text': '"20"',
                'metadata_json': json.dumps({'policy_approved': True, 'approval_ref': 'approval-reference'})})
        self.add_calculation(calculation_id='source:' + c.instrument_id, calculation_name='EQUITY_FUNDAMENTAL',
            inputs={'evidence_ids': ['facts:' + c.instrument_id]}, result={'subject': c.instrument_id})
        self.add_calculation(calculation_id='policy:' + c.instrument_id, calculation_name='CAPITAL_COMPETITION_INPUT',
            inputs={'evidence_ids': ['facts:' + c.instrument_id, 'price:' + c.instrument_id, 'approval:' + c.instrument_id],
                    'source_calculation_ids': ['source:' + c.instrument_id]}, result=json_value(c))
        return AuthorizedCapitalInput(c, self.run_id, AS_OF, 'policy:' + c.instrument_id,
                                      'approval:' + c.instrument_id, 'approval-reference')


def portfolio():
    request = SimpleNamespace(pinned_state=SimpleNamespace(analysis_as_of=AS_OF, state_version=1, snapshot_ref='snap'),
        evaluation_currency='USD', positions=(PortfolioPosition('A', D('30'), 'USD'), PortfolioPosition('B', D('20'), 'USD')), fx_evidence=())
    result = SimpleNamespace(gross_assets=D('100'), state_version=1, snapshot_ref='snap')
    return request, result


class CapitalCompetitionTests(unittest.TestCase):
    def test_thirty_percent_strong_quality_is_core_not_automatic_reduce(self):
        result = analyze_capital_competition((candidate('A'),))
        row = result.ranked[0]
        self.assertEqual(row.category, CapitalCategory.CORE_CONCENTRATION)
        self.assertIn('CONCENTRATION_RISK', row.flags)
        self.assertFalse(row.automatic_reduce)

    def test_ten_percent_poor_quality_is_reduce(self):
        row = analyze_capital_competition((candidate('A', score='.1', weight='.1'),)).ranked[0]
        self.assertEqual(row.category, CapitalCategory.REDUCE)
        self.assertFalse(row.automatic_reduce)

    def test_small_position_relevance_and_moonshot_exception(self):
        c = replace(candidate('A', weight='.005'), expansion_planned=False)
        row = analyze_capital_competition((c,)).ranked[0]
        self.assertIn('POSITION_TOO_SMALL_TO_MATTER', row.flags)
        moonshot = analyze_capital_competition((replace(c, optionality_intent='moonshot'),)).ranked[0]
        self.assertNotIn('POSITION_TOO_SMALL_TO_MATTER', moonshot.flags)
        self.assertFalse(row.automatic_reduce)

    def test_etf_has_no_default_priority(self):
        result = analyze_capital_competition((candidate('EQUITY', score='.9'), candidate('ETF', score='.6')))
        self.assertEqual(result.ranked[0].instrument_id, 'EQUITY')

    def test_stronger_candidate_rotation_requires_net_frictions(self):
        candidates = (candidate('WEAK', score='.5', growth='.05'), candidate('NEW', score='.9', held=False))
        unknown = analyze_capital_competition(candidates).rotations[0]
        self.assertEqual(unknown.status, 'FRICTIONS_UNAVAILABLE')
        known = analyze_capital_competition(candidates, rotation_friction={('WEAK', 'NEW'): D('.02')}).rotations[0]
        self.assertEqual(known.status, 'REVIEW_CANDIDATE')
        self.assertGreater(known.net_destination_cagr, D('.05'))
        expensive = analyze_capital_competition(candidates, rotation_friction={('WEAK', 'NEW'): D('.8')}).rotations[0]
        self.assertEqual(expensive.status, 'NOT_JUSTIFIED')

    def test_over_thirty_percent_forces_level_three_trigger(self):
        result = analyze_capital_competition((candidate('A', weight='.31'), candidate('B', weight='.25')))
        self.assertIn('SINGLE_ASSET_OVER_30_PERCENT', result.review_triggers)
        self.assertIn('TOP_TWO_OVER_50_PERCENT', result.review_triggers)
        self.assertFalse(result.ranked[0].automatic_reduce)

    def test_missing_qualitative_inputs_watch_unranked(self):
        result = analyze_capital_competition((CapitalCandidate('A', weight=D('.3')),))
        self.assertFalse(result.ranked)
        self.assertEqual(result.unranked[0].category, CapitalCategory.WATCH)
        self.assertFalse(result.unranked[0].scenario_cagrs)

    def test_score_is_separate_from_cagr_and_dilution_is_consumed(self):
        c = candidate('A', score='.9')
        base = analyze_capital_competition((c,)).ranked[0]
        self.assertEqual(base.score, D('.9'))
        self.assertAlmostEqual(base.scenario_cagrs['base'], D('.15'))
        diluted = replace(c, scenarios=tuple(replace(s, annual_dilution=D('.05')) for s in c.scenarios))
        self.assertLess(analyze_capital_competition((diluted,)).ranked[0].scenario_cagrs['base'], base.scenario_cagrs['base'])

    def test_policy_weights_override_changes_priorities(self):
        c = candidate('A')
        c = replace(c, scores={**c.scores, 'valuation': D('.5')})
        weights = dict(zip(DIMENSIONS, (D('.1'), D('.6'), D('.1'), D('.05'), D('.05'), D('.1'))))
        a = analyze_capital_competition((c,)).ranked[0].score
        b = analyze_capital_competition((c,), policy=CompetitionPolicy(weights)).ranked[0].score
        self.assertLess(b, a)

    def test_bridge_approved_same_run_inputs_and_ten_section_order(self):
        run = SyntheticRun()
        approved = run.approved(candidate('A'))
        request, result = portfolio()
        report = render_capital_competition(run, request, result, CapitalCompetitionPolicyInputs((approved,)))
        self.assertEqual(tuple(s.title for s in report.sections), TITLES)
        self.assertEqual(report.result.ranked[0].instrument_id, 'A')
        self.assertEqual(report.result.unranked[0].instrument_id, 'B')
        self.assertIn('SINGLE_ASSET_OVER_25_PERCENT', report.review_triggers)
        stored = run.snapshot['calculations'][-1]
        self.assertEqual(stored['calculation_name'], 'CAPITAL_COMPETITION')
        self.assertEqual(json.loads(stored['inputs_json'])['state_version'], 1)

    def test_bridge_cross_run_and_unapproved_inputs_are_not_ranked(self):
        for failure in ('run_id', 'approval'):
            run = SyntheticRun()
            approved = run.approved(candidate('A'))
            if failure == 'run_id':
                approved = replace(approved, run_id='other')
            else:
                run.snapshot['evidence'][-1]['metadata_json'] = '{}'
            report = render_capital_competition(run, *portfolio(), CapitalCompetitionPolicyInputs((approved,)))
            self.assertFalse(report.result.ranked)
            self.assertIn('A:capital_input_not_verified', report.missing_inputs)

    def test_bridge_future_evidence_and_price_tampering_are_rejected(self):
        for failure in ('future', 'price'):
            run = SyntheticRun()
            approved = run.approved(candidate('A'))
            if failure == 'future':
                run.snapshot['evidence'][0]['published_at'] = '2026-10-06T00:00:00+00:00'
            else:
                run.snapshot['evidence'][1]['value_text'] = '"200"'
            report = render_capital_competition(run, *portfolio(), CapitalCompetitionPolicyInputs((approved,)))
            self.assertFalse(report.result.ranked)

    def test_bridge_no_inputs_is_explicitly_unranked_and_non_posting(self):
        run = SyntheticRun()
        report = render_capital_competition(run, *portfolio())
        self.assertFalse(report.result.ranked)
        self.assertEqual(len(report.result.unranked), 2)
        self.assertEqual(len(report.calculation_refs), 1)
        self.assertTrue(all(s.metadata['non_posting'] for s in report.sections))

    def test_bridge_unknown_total_does_not_use_partial_subset_weight(self):
        run = SyntheticRun()
        request, result = portfolio()
        result.gross_assets = None
        run.snapshot['calculations'][0]['result_json'] = '{"gross_assets": null}'
        report = render_capital_competition(run, request, result)
        self.assertTrue(all(r.weight is None for r in report.result.unranked))
        self.assertIn('concentration_total_portfolio_denominator_unavailable', report.missing_inputs)

    def test_live_retrieval_after_pin_is_allowed_for_prior_publication(self):
        run = SyntheticRun()
        approved = run.approved(candidate('A'))
        for e in run.snapshot['evidence']:
            e['retrieved_at'] = '2026-10-05T00:05:00+00:00'
        report = render_capital_competition(run, *portfolio(), CapitalCompetitionPolicyInputs((approved,)))
        self.assertEqual(report.result.ranked[0].instrument_id, 'A')
        self.assertIn('Level 3', report.sections[4].lines[0])

    def test_unpersisted_portfolio_total_cannot_authorize_concentration(self):
        run = SyntheticRun()
        run.snapshot['calculations'].clear()
        report = render_capital_competition(run, *portfolio())
        self.assertTrue(all(r.weight is None for r in report.result.unranked))
        self.assertIn('same_run_portfolio_calculation_unverified', report.missing_inputs)


if __name__ == '__main__':
    unittest.main()
