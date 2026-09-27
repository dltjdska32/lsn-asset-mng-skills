# GEMINI31-A-R01-02 — R01 신규 fixture 실행 오류

Gemini 3.1 Pro High A, HEAD `d6ef79bc90bb08f0bd170b37653c65a927b029b3` + R01-01 미커밋 변경. A 소유 `deep_research.py`, `tests/unit/test_r01_price_binding.py`, handoff만. file read/write만; RunCommand/shell/git/tests/pip/web 호출 금지. 총괄 테스트.

총괄이 새 테스트 5개를 실행했지만 **전부 ERROR**, 모두 `ProviderObservation.__init__() got an unexpected keyword argument 'evidence_id'`. 테스트 fixture가 실제 모델을 보지 않고 가상 필드를 만들었다. `ProviderObservation`은 evidence_id가 없고 `evidence_type, source_name, source_url, source_tier, provider_id` 등 필수 필드를 가진다. `SelectedEvidence`는 `observation, freshness, evidence_id, observation_id, partial, reason`이다(`selection_reason` 없음). `FreshnessAssessment(status,effective_time,age_seconds,reason)`와 `ResearchOutcome(selected,provider_results,used_web)`도 실제 시그니처에 맞춰라. `test_phase6_report_runtime` 등 기존 합성 fixture 예시를 참고할 수 있다. 단순 MagicMock으로 조건을 통과시키지 말고 실제 ProviderObservation과 적격/부적격 시각을 구성해 통합 analyze_equity 호출의 `valuation_input.current_price`와 경고를 검증한다.

R01-01 코드의 가격 `FRESH` 차단 의도는 보존하되 fixture를 실행 가능하게 고쳐라. 현재가 선택의 근거 ID 및 metric/타입 검증에 남은 갭이 있으면 인계. `handoffs/GEMINI31-A-R01-02.md`에 첫 5 ERROR와 수정·미실행 검증 기록.
