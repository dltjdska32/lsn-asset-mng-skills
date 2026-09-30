# GEMINI31-A-FALLBACK-03 — R05 fixture·coverage 경계 재수정

Gemini 3.1 Pro High A, HEAD `962930d` + FALLBACK-01/02 WIP. 소유 `providers/execution.py`, `tests/unit/test_r05_fallback_eligibility.py`, 새 `handoffs/GEMINI31-A-FALLBACK-03.md`만. 파일 도구만, RunCommand/shell/git/tests/pip/web 금지. R05/DESIGN-v0.1.

총괄 신규+기존 acceptance 14개 실행: **1 FAIL**. `test_fundamentals_skip_missing_observation_time`에서 기대 p2, 실제 p1. 원인은 테스트 `_obs(obs_at=None)` helper가 `obs_at or DEFAULT`로 missing 시각을 다시 기본 시각으로 채우는 것. sentinel을 써서 '인자 생략'과 명시적 None을 구별하고 진짜 시각 없는 관측치를 테스트하라. test가 코드 경계를 실제 검증하도록 하라.

`required_metrics` 제공 시 그룹키 `(period_end, currency)`가 둘 다 빈 문자열이어도 메트릭 집합을 완성하여 중단한다. 기간 필수 duration financial metric은 period_end가 없으면 coverage complete라 판단하지 말고, 같은 종료일이라도 period_start/reporting_frequency/accounting_standard/consolidation/adjustment_basis가 다른 fact를 무조건 합치지 말라. 보수적 그룹핑 또는 coverage 미완으로 다음 공급자 호출. 기존 신규 fixture도 적격 그룹 metadata를 채워라. CURRENT_PRICE result 안에 유효 관측치 1개와 더 최신 부적격 관측치 1개가 섞인 경우 downstream `Phase4ResearchRuntime.persist_and_select(results)`가 raw 전부를 재선택할 위험이 남는다. 이 과제에서는 `execution.py`만 수정하므로 이 문제를 명확히 인계하고 **전체 R05/가격 안전 완료 주장 금지**. 혹시 이 문제를 추가 코드 없이 fail-closed로 막으려면 가격 result의 모든 observation이 적격일 때만 중단하도록 할 수 있다. 테스트에 혼합 결과를 넣어 중단 여부를 검증하라. 그 다음 Phase4 실소비 연결은 별도 과제.
