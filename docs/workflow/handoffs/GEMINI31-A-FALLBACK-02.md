# GEMINI31-A-FALLBACK-02 Handoff

## 수정 사항 (Changes)
이전 FALLBACK-01 과정에서 발생한 5개의 테스트 에러와 날짜 파싱 등의 안전성 문제를 해결했습니다:

1. **테스트 픽스처 및 Assert 오류 수정 (`tests/unit/test_r05_fallback_eligibility.py`)**:
   - `ProviderRequest` 생성 시 필수 필드인 `analysis_timezone="UTC"`를 모든 테스트에 명시적으로 추가하여 에러를 수정했습니다.
   - 존재하지 않는 `ProviderResult.provider_name` 접근을 올바른 프로퍼티인 `.provider`로 수정했습니다.
   - `_now()` 함수를 호출하여 동적으로 결정되던 `analysis_as_of` 및 `observation_time`을 고정된 ISO 8601 문자열(`"2024-04-01T00:00:00+00:00"` 등)로 대체하여 테스트가 시간에 구애받지 않고 결정적으로 통과되게 개선했습니다.

2. **관측치별 시간 검증 안전성 강화 (`execution.py`)**:
   - `FUNDAMENTALS` 로직에서 `observation_time(obs)`이 `None`을 반환하는 경우(즉, 관측시각이나 공개일이 없는 팩트)를 명시적으로 계산 후보에서 거부(`skip`)하도록 수정했습니다.
   - `observation_time()` 또는 `engine.assess()` 호출 시 발생할 수 있는 `ValueError` 예외를 개별 관측치 단위로 `try-except` 처리했습니다. 이로 인해 한 관측치의 포맷 오류가 멀쩡한 다른 관측치까지 통째로 버리는 전체 Result 에러로 번지지 않게 방지합니다.

3. **값 및 조건 필터링 강화**:
   - `request.instrument_id`가 있을 때, 팩트의 종목 기호와 불일치하는 경우 `required_metrics` 커버리지 셈에서 엄격하게 제외했습니다.
   - `bool`, `NaN`, `Infinity` 등 계산에 사용할 수 없는 값들을 명시적으로 제외했습니다.
   - `request.parameters['required_metrics']`의 경우 빈 문자열이나 whitespace만 있는 항목은 무시(`strip()` 후 체크)되도록 강화했습니다.

4. **보수적 Metric Coverage 집계 (Period/Currency 그룹핑)**:
   - 이전에는 한 Result 내에 여러 다른 기간이나 다른 통화로 반환된 메트릭이라 하더라도 단순 집합 합산(`Union`)을 통해 필수 메트릭이 충족되었다고 오판할 소지가 있었습니다. 
   - 이를 방지하기 위해 관측치를 `(period_end, currency)` 기준으로 그룹핑한 뒤, **최소한 단일 그룹 내에서 모든 `required_metrics`를 100% 충족하는 경우에만** 유효한 결과로 판정하는 보수적 제한을 적용했습니다.
   - *참고:* 완전한 기간(Period)/기준(Basis) 일관성(Coherence) 확보 및 재무제표 시계열 결합(FinancialSet) 로직은 Phase 5 소비처 및 후속 R02 작업의 역할입니다.

## 미실행 검사 및 갭 (Unexecuted Tests & Remaining Gaps)
- 쉘 실행 불가로 인해 코디네이터가 직접 검증해주셔야 합니다.
  ```bash
  python -m unittest tests.unit.test_r05_fallback_eligibility
  ```
- **주의**: 이 테스트가 통과되었다 하더라도, 아직 Web Fallback 리트라이(`used_web_fallback=True` 동작) 및 `deep_research` 엔진 자체와의 완전한 연결 및 소비가 완료된 것은 아닙니다 (R05 전체 완료 주장 금지).

## 기준 커밋
- Base Commit: `962930d494f67a7e4844a312b1eb97d9f51903e8` (FALLBACK-01 미커밋 반영 기준)
