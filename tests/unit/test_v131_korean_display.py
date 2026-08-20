import unittest
from investment_stack.reporting.display import ko_status

class V131KoreanDisplayTests(unittest.TestCase):
    def test_user_facing_statuses_are_korean(self):
        expected = {
            "AVAILABLE": "확인 완료", "PARTIAL": "일부 정보 확인 불가", "UNAVAILABLE": "확인 불가",
            "FRESH": "실시간 시세", "DELAYED": "지연 시세", "STALE": "오래된 시세",
            "UNKNOWN": "확인 불가", "HIGH": "높음", "MEDIUM": "보통", "LOW": "낮음",
        }
        for raw, label in expected.items():
            self.assertEqual(label, ko_status(raw))
