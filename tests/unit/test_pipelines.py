from __future__ import annotations

import unittest

from investment_stack.pipelines import PIPELINES, FixedPipelinePlanner, PipelineStep
from investment_stack.routing import RequestMode


class FixedPipelinePlannerTest(unittest.TestCase):
    def test_exactly_one_pipeline_exists_for_each_of_seven_modes(self) -> None:
        self.assertEqual(7, len(RequestMode))
        self.assertEqual(set(RequestMode), set(PIPELINES))

    def test_pipeline_registry_is_immutable(self) -> None:
        with self.assertRaises(TypeError):
            PIPELINES[RequestMode.SINGLE_ASSET_ANALYSIS] = ()  # type: ignore[index]

    def test_personal_portfolio_materiality_precedes_deep_research(self) -> None:
        steps = FixedPipelinePlanner().plan(RequestMode.PERSONAL_PORTFOLIO_ANALYSIS).steps
        self.assertLess(
            steps.index(PipelineStep.APPLY_MATERIALITY_GATE),
            steps.index(PipelineStep.DEEP_RESEARCH_SELECTED_ASSETS),
        )

    def test_single_asset_automatically_passes_gate(self) -> None:
        steps = FixedPipelinePlanner().plan(RequestMode.SINGLE_ASSET_ANALYSIS).steps
        self.assertEqual(PipelineStep.AUTO_PASS_REQUESTED_ASSETS, steps[0])

    def test_asset_update_validates_time_before_posting_decision(self) -> None:
        steps = FixedPipelinePlanner().plan(RequestMode.ASSET_UPDATE).steps
        self.assertLess(
            steps.index(PipelineStep.VALIDATE_EVENT_TIME),
            steps.index(PipelineStep.DECIDE_POSTING),
        )

    def test_portfolio_scenario_has_no_personal_state_mutation_steps(self) -> None:
        steps = set(FixedPipelinePlanner().plan(RequestMode.PORTFOLIO_SCENARIO).steps)
        forbidden = {
            PipelineStep.EXTRACT_TRANSACTION_INTENT,
            PipelineStep.DECIDE_POSTING,
            PipelineStep.PROJECT_PERSONAL_STATE,
            PipelineStep.ADVANCE_STATE_VERSION,
        }
        self.assertTrue(steps.isdisjoint(forbidden))


if __name__ == "__main__":
    unittest.main()
