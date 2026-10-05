from __future__ import annotations

import unittest

from investment_stack.pipelines import FixedPipelinePlanner, PipelineStep
from investment_stack.routing import RequestMode, RequestRouter


class Phase8RequestModeAcceptanceTests(unittest.TestCase):
    def test_all_seven_modes_route_and_have_fixed_pipelines(self) -> None:
        samples = {
            "FANUC 2주 샀어": RequestMode.ASSET_UPDATE,
            "내 포트폴리오 분석해": RequestMode.PERSONAL_PORTFOLIO_ANALYSIS,
            "FANUC 분석해": RequestMode.SINGLE_ASSET_ANALYSIS,
            "FANUC이랑 삼성전자 비교": RequestMode.ASSET_COMPARISON,
            "FANUC 5% 추가하면 포트폴리오 어떻게 변해?": RequestMode.PORTFOLIO_SCENARIO,
            "이 투자 논지 검토해": RequestMode.THESIS_REVIEW,
            "보고서 갱신": RequestMode.REPORT_REFRESH,
        }
        router = RequestRouter()
        planner = FixedPipelinePlanner()
        self.assertEqual(7, len(RequestMode))
        for text, expected in samples.items():
            with self.subTest(text=text):
                decision = router.route(text)
                self.assertEqual(expected, decision.mode)
                plan = planner.plan(decision.mode)
                self.assertEqual(expected, plan.mode)
                self.assertTrue(plan.steps)

    def test_hypothetical_trade_never_enters_posting_pipeline(self) -> None:
        decision = RequestRouter().route("FANUC을 팔면 내 포트폴리오가 어떻게 변해?")
        self.assertEqual(RequestMode.PORTFOLIO_SCENARIO, decision.mode)
        steps = set(FixedPipelinePlanner().plan(decision.mode).steps)
        self.assertNotIn(PipelineStep.DECIDE_POSTING, steps)
        self.assertNotIn(PipelineStep.ADVANCE_STATE_VERSION, steps)
        self.assertIn(PipelineStep.RUN_NON_POSTING_SCENARIO, steps)

    def test_asset_update_is_the_only_mode_with_posting_decision(self) -> None:
        planner = FixedPipelinePlanner()
        posting_modes = {
            mode
            for mode in RequestMode
            if PipelineStep.DECIDE_POSTING in planner.plan(mode).steps
        }
        self.assertEqual({RequestMode.ASSET_UPDATE}, posting_modes)


if __name__ == "__main__":
    unittest.main()
