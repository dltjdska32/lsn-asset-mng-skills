"""Small deterministic router; it never builds or asks an LLM for a graph."""

from __future__ import annotations

import re
from collections.abc import Iterable

from investment_stack.routing.models import RequestMode, RoutingDecision


class RoutingError(ValueError):
    """Raised when a request cannot be routed safely."""


def _contains_any(text: str, patterns: Iterable[str]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


class RequestRouter:
    """Resolve text to one of seven modes using stable, inspectable precedence."""

    _REPORT_REFRESH = (
        r"\b(refresh|regenerate|update)\s+(the\s+)?(report|analysis)\b",
        r"(?:보고서|리포트|분석)\s*(?:갱신|새로고침|다시\s*생성)",
    )
    _HYPOTHETICAL = (
        r"\b(what\s+if|if\s+i|suppose(?:\s+that)?|scenario)\b",
        r"(?:[가-힣]+(?:으)?면|[가-힣]+한다면|[가-힣]+했을\s*때)"
        r"(?:[^.?!]{0,80}(?:어떻게|어떨|변해|달라|비중|포트폴리오|순자산|현금)|\s*[?？]|\s*$)",
    )
    _ASSET_UPDATE = (
        r"\b(bought|buy|sold|sell|deposit(?:ed)?|withdrew|withdraw|transferred|repay(?:ed)?|borrow(?:ed)?)\b",
        r"(?:매수|매도|샀|샀어|팔았|입금|출금|송금|이체|상환|대출|배당\s*받)",
    )
    _COMPARISON = (r"\b(compare|comparison|versus|vs\.?)\b", r"비교")
    _SCENARIO = (
        r"\b(what\s+if|scenario|rebalance|allocation)\b",
        r"(?:시나리오|리밸런싱|비중.+(?:올리|내리|바꾸|하면))",
    )
    _THESIS = (r"\b(thesis|investment case)\b", r"(?:투자\s*논지|가설\s*검토|논지\s*검토)")
    _PORTFOLIO = (
        r"\b(my\s+)?(portfolio|net\s*worth|personal\s+assets?)\b",
        r"(?:내\s*(?:자산|포트폴리오)|순자산|개인\s*자산|전체\s*포트폴리오)",
    )

    def route(
        self,
        text: str,
        *,
        mode_hint: str | RequestMode | None = None,
    ) -> RoutingDecision:
        """Return a mode; an explicit hint is validated and always wins."""

        if mode_hint is not None:
            try:
                mode = RequestMode.parse(mode_hint)
            except ValueError as exc:
                raise RoutingError(str(exc)) from exc
            return RoutingDecision(mode=mode, reason="explicit mode hint", explicit=True)

        normalized = " ".join(text.strip().split())
        if not normalized:
            raise RoutingError("Request text must not be empty")

        rules = (
            (RequestMode.REPORT_REFRESH, self._REPORT_REFRESH, "matched report refresh intent"),
            (
                RequestMode.PORTFOLIO_SCENARIO,
                self._HYPOTHETICAL + self._SCENARIO,
                "matched hypothetical non-posting scenario intent",
            ),
            (RequestMode.ASSET_UPDATE, self._ASSET_UPDATE, "matched personal asset mutation intent"),
            (RequestMode.ASSET_COMPARISON, self._COMPARISON, "matched explicit comparison intent"),
            (RequestMode.THESIS_REVIEW, self._THESIS, "matched thesis review intent"),
            (
                RequestMode.PERSONAL_PORTFOLIO_ANALYSIS,
                self._PORTFOLIO,
                "matched personal portfolio analysis intent",
            ),
        )
        for mode, patterns, reason in rules:
            if _contains_any(normalized, patterns):
                return RoutingDecision(mode=mode, reason=reason)

        return RoutingDecision(
            mode=RequestMode.SINGLE_ASSET_ANALYSIS,
            reason="non-empty analysis request defaults to the requested single asset",
        )
