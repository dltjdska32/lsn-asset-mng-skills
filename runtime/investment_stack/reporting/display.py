"""Korean user-facing labels for report state.

Internal enum/database values stay stable in English. Only rendered output is localized.
"""

from __future__ import annotations

_STATUS_LABELS = {
    "AVAILABLE": "확인 완료",
    "PARTIAL": "일부 정보 확인 불가",
    "UNAVAILABLE": "확인 불가",
    "FRESH": "실시간 시세",
    "DELAYED": "지연 시세",
    "LAST_VALID_CLOSE": "최근 거래일 종가",
    "STALE": "오래된 시세",
    "UNKNOWN": "확인 불가",
    "HIGH": "높음",
    "MEDIUM": "보통",
    "LOW": "낮음",
    "REQUIRED": "필요",
    "NOT TRIGGERED": "불필요",
}


def ko_status(value: object | None, *, fallback: str = "확인 불가") -> str:
    if value is None:
        return fallback
    raw = getattr(value, "value", value)
    return _STATUS_LABELS.get(str(raw), str(raw))
