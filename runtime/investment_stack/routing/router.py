"""Small deterministic router; it never builds or asks an LLM for a graph."""

from __future__ import annotations

import re
from collections.abc import Iterable

from investment_stack.routing.models import RequestIntent, RequestMode, RoutingDecision


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
        r"\b(bought|sold|deposited|withdrew|transferred|repaid|borrowed|received\s+(?:a\s+)?dividend)\b",
        r"(?:샀(?:어|다|습니다)?|매수했(?:어|다|습니다)?|추가매수했(?:어|다|습니다)?|구입했(?:어|다|습니다)?|팔았(?:어|다|습니다)?|매도했(?:어|다|습니다)?|입금했(?:어|다|습니다)?|출금했(?:어|다|습니다)?|송금했(?:어|다|습니다)?|이체했(?:어|다|습니다)?|상환했(?:어|다|습니다)?|대출받았(?:어|다|습니다)?|배당\s*받았(?:어|다|습니다)?)",
    )
    _NEGATED_TRANSACTION = (
        r"\b(don't|do\s+not|never)\s+(?:buy|sell)\b",
        r"(?:매수|매도|구매|사|팔)(?:하지\s*말고|하지\s*않고|안\s*하고|말고)",
    )
    _BUY_QUESTION = (
        r"\b(should\s+i|would\s+it\s+be\s+wise\s+to)\s+(?:buy|sell)\b",
        r"(?:매수|구매|사도)\s*(?:해도\s*될지|해도\s*될까|할지|할까|하는\s*게\s*좋을지)",
    )
    _ORDER_COMMAND = (
        r"\b(buy|sell)\s+(?:me\s+)?(?:some\s+)?(?:more\s+)?[A-Z0-9.$-]+\b",
        r"(?:매수|매도)해(?:줘|주세요|요)?(?:\s|$|[.!?])|(?:사|팔)\s*줘",
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
        """Return a fixed mode while keeping transaction safety intents authoritative."""

        normalized = " ".join(text.strip().split())
        if not normalized:
            raise RoutingError("Request text must not be empty")

        try:
            hinted_mode = RequestMode.parse(mode_hint) if mode_hint is not None else None
        except ValueError as exc:
            raise RoutingError(str(exc)) from exc

        # Classify safety-sensitive language before honoring a mode hint.
        if _contains_any(normalized, self._REPORT_REFRESH):
            inferred = RoutingDecision(RequestMode.REPORT_REFRESH, "matched report refresh intent", intent=RequestIntent.REPORT_REFRESH)
        elif _contains_any(normalized, self._HYPOTHETICAL + self._SCENARIO):
            inferred = RoutingDecision(RequestMode.PORTFOLIO_SCENARIO, "matched hypothetical non-posting scenario intent", intent=RequestIntent.HYPOTHETICAL)
        elif _contains_any(normalized, self._NEGATED_TRANSACTION):
            inferred = RoutingDecision(RequestMode.SINGLE_ASSET_ANALYSIS, "negated transaction is not a transaction fact", intent=RequestIntent.NEGATED_TRANSACTION)
        elif _contains_any(normalized, self._BUY_QUESTION):
            inferred = RoutingDecision(RequestMode.SINGLE_ASSET_ANALYSIS, "buy/sell question routes to analysis", intent=RequestIntent.BUY_QUESTION)
        elif _contains_any(normalized, self._ORDER_COMMAND):
            inferred = RoutingDecision(
                RequestMode.SINGLE_ASSET_ANALYSIS,
                "trade execution command is outside the supported request scope",
                intent=RequestIntent.ORDER_COMMAND,
                supported=False,
                unsupported_reason="Orders are not executed; provide a completed historical transaction fact or request analysis.",
            )
        elif _contains_any(normalized, self._ASSET_UPDATE):
            inferred = RoutingDecision(RequestMode.ASSET_UPDATE, "matched completed transaction fact", intent=RequestIntent.TRANSACTION_FACT)
        elif _contains_any(normalized, self._COMPARISON):
            inferred = RoutingDecision(RequestMode.ASSET_COMPARISON, "matched explicit comparison intent")
        elif _contains_any(normalized, self._THESIS):
            inferred = RoutingDecision(RequestMode.THESIS_REVIEW, "matched thesis review intent")
        elif _contains_any(normalized, self._PORTFOLIO):
            inferred = RoutingDecision(RequestMode.PERSONAL_PORTFOLIO_ANALYSIS, "matched personal portfolio analysis intent")
        else:
            inferred = RoutingDecision(RequestMode.SINGLE_ASSET_ANALYSIS, "non-empty analysis request defaults to the requested single asset")

        if hinted_mode is None:
            return inferred
        if not inferred.supported:
            return inferred
        if hinted_mode is RequestMode.ASSET_UPDATE and inferred.intent is not RequestIntent.TRANSACTION_FACT:
            return RoutingDecision(
                RequestMode.ASSET_UPDATE,
                "mode hint cannot turn a question, negation, or analysis into a transaction fact",
                explicit=True,
                intent=inferred.intent,
                supported=False,
                unsupported_reason="ASSET_UPDATE requires a completed transaction fact and a validated typed intent.",
            )
        return RoutingDecision(hinted_mode, "explicit mode hint", explicit=True, intent=inferred.intent)
