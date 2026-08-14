from __future__ import annotations

import unittest

from investment_stack.routing import RequestMode, RequestRouter, RoutingError


class RequestRouterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.router = RequestRouter()

    def test_explicit_mode_accepts_every_closed_set_member(self) -> None:
        for mode in RequestMode:
            with self.subTest(mode=mode):
                decision = self.router.route("opaque request", mode_hint=mode.value)
                self.assertEqual(mode, decision.mode)
                self.assertTrue(decision.explicit)

    def test_representative_requests_route_deterministically(self) -> None:
        cases = {
            "FANUC 2주 6400엔에 샀어": RequestMode.ASSET_UPDATE,
            "현재 내 자산 분석해": RequestMode.PERSONAL_PORTFOLIO_ANALYSIS,
            "FANUC 분석해": RequestMode.SINGLE_ASSET_ANALYSIS,
            "FANUC와 삼성전자를 비교해": RequestMode.ASSET_COMPARISON,
            "BTC 비중을 5%로 올리면 어떻게 돼?": RequestMode.PORTFOLIO_SCENARIO,
            "내 FANUC 투자 논지를 검토해": RequestMode.THESIS_REVIEW,
            "지난 투자 보고서 갱신해": RequestMode.REPORT_REFRESH,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(expected, self.router.route(text).mode)

    def test_report_refresh_precedes_generic_analysis(self) -> None:
        self.assertEqual(
            RequestMode.REPORT_REFRESH,
            self.router.route("분석 다시 생성해").mode,
        )

    def test_hypothetical_requests_always_use_non_posting_scenario_mode(self) -> None:
        cases = (
            "What if I sell FANUC?",
            "What if I buy more FANUC?",
            "FANUC 2주 팔면 어떻게 돼?",
            "BTC 비중을 5%로 늘리면?",
            "금 10% 넣으면 포트폴리오 어떻게 변해?",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(RequestMode.PORTFOLIO_SCENARIO, self.router.route(text).mode)

    def test_confirmed_real_world_mutations_use_asset_update_mode(self) -> None:
        cases = (
            "FANUC 2주 팔았어",
            "FANUC 2주 샀어",
            "BTC 0.05개 추가매수했어",
            "현금 200만원 입금했어",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(RequestMode.ASSET_UPDATE, self.router.route(text).mode)

    def test_empty_text_is_rejected(self) -> None:
        with self.assertRaises(RoutingError):
            self.router.route("   ")

    def test_unknown_explicit_mode_is_rejected(self) -> None:
        with self.assertRaises(RoutingError):
            self.router.route("anything", mode_hint="GENERIC_DAG")


if __name__ == "__main__":
    unittest.main()
