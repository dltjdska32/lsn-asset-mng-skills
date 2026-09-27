# GEMINI31-C-03-R1 — 끊긴 C-03 마무리

같은 Gemini 3.1 Pro High C worktree, 기준 HEAD `2b772fd584942d70636645958be1f020d879014d` + C-03 미커밋 `decisions/briefing.py`. 지난 호출은 Gemini 503으로 끊겨 **완료 아님**. 파일 read/write만 하라. RunCommand/shell/git/tests/pip/web 도구 호출 금지.

앞서 원 `GEMINI31-C-03.md`를 따르되 이미 고친 snapshot hash/bound slot 검증은 보존한다. 총괄이 중간 버전에서 `tests/decisions` 4개 중 1 FAIL 확인: `test_briefing_available_wait`의 기존 문자열 `A결과 통합 필요`가 새 문구와 안 맞는다. assertion을 의미에 맞게 수정하고 hash·slot 불일치 반례 테스트를 추가하라. `InvestmentReportBuilder.build`의 실제 마크다운 5섹션 순서와 본문/상세 ID 노출을 검증하는 합성 테스트도 작성하라. 가능하면 기존 report fixture를 사용하고 개인 DB는 쓰지 않는다. 새로운 BUY 판단은 금지. `handoffs/GEMINI31-C-03.md`에 작업·미실행 검증·남은 부분 기록 후 즉시 응답하라.
