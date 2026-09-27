# GEMINI31-A-FALLBACK-01 Handoff

## 수정 사항 (Changes)
`ProviderFallbackExecutor`(`runtime/investment_stack/providers/execution.py`)의 다음 공급자 재시도(fallback) 선정 기준을 R05 요구사항에 맞춰 강화했습니다. 기존에는 상태가 `AVAILABLE`이거나 `PARTIAL`이면서 1개 이상의 관측치만 있으면 단순하게 해당 공급자의 결과를 `selected`로 확정했으나, 이제는 요청의 목적(capability)에 따라 실제 계산에 유효한 결과인지 판단(`_is_eligible_for_purpose`)합니다.

1. **CURRENT_PRICE 검증**:
   - `FreshnessEngine`을 통해 상태가 `FRESH`인지 검사합니다.
   - 요청에 `instrument_id` 또는 `quote_currency`가 지정된 경우 관측치와 일치하는지 확인합니다.
   - 가격 값이 `finite`한 양의 실수(`> 0`)인지 검증합니다.
   - 이 조건 중 하나라도 만족하는 관측치가 없다면 해당 결과는 부적격으로 판정되어 다음 공급자를 호출(fallback)합니다.

2. **FUNDAMENTALS 검증**:
   - 최소 하나 이상의 `calculation_input_approved=True`인 숫자형(numeric) 관측치가 포함되어 있어야 합니다.
   - `analysis_as_of` 기준시각을 초과하는 미래의(future) 관측치는 후보에서 제외합니다.
   - 요청 파라미터로 `required_metrics` 리스트가 주어진 경우, 반환된 관측치들이 해당 필수 메트릭 집합을 모두 충족하는지 검사합니다. (부분 충족 시 다음 공급자 호출)
   - `required_metrics`의 타입이 잘못 전달된 경우 fail-closed(부적격 판정) 처리합니다.

3. **신규 합성 단위 테스트 작성 (`tests/unit/test_r05_fallback_eligibility.py`)**:
   - 비적격 2개 이후 정상 3번째 공급자 선택, 모든 결과 부적격 시 `selected=None`, stale 가격 뒤 fresh 가격, SEC partial 뒤 신규 공급자, required metric 누락 뒤 완성, 미래 관측 반례 등의 다양한 재시도 시나리오를 합성 테스트로 구현했습니다.

## 갭 및 후속 작업 (Remaining Gaps & Next Steps)
- 본 과제는 Structured Provider 계층에서의 fallback 선정 로직만을 구현한 수직 슬라이스입니다.
- **R05 미완료**: 이 작업만으로 전체 R05가 완료된 것이 아닙니다. `Phase4ResearchRuntime` 레벨에서의 Web Research fallback(`used_web_fallback=True` 동작) 및 `deep_research` 실소비처와의 완벽한 연결은 아직 검증되지 않았으며 후속 구현이 필요합니다.
- **미실행 테스트**: 쉘/터미널 실행 권한이 없으므로 직접 테스트를 구동하지 못했습니다. 총괄 코디네이터가 아래 커맨드를 통해 단위 테스트 통과를 직접 확인해 주시기 바랍니다.
  ```bash
  python -m unittest tests.unit.test_r05_fallback_eligibility
  ```

## 기준 커밋
- Base Commit: `962930d494f67a7e4844a312b1eb97d9f51903e8` (SEC-02 완료 기준)
