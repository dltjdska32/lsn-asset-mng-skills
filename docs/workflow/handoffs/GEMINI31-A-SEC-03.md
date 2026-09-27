# GEMINI31-A-SEC-03 Handoff

## 수정 사항 (Changes)
이전 SEC-02 검증 과정에서 발생한 `TypeError`와 완화된 필터링 문제를 다음과 같이 수정했습니다:

1. **정렬 키 타입 안정성(TypeError) 및 정밀도 보존**: 
   - `observations.sort()` 실행 시 `metadata`에서 가져온 값(`start`, `period_end`, `accn`, `filed` 등)이 `None`일 경우 `str`과의 비교에서 `TypeError`가 발생하던 문제를 해결하기 위해 `str(x or "")` 방식을 적용했습니다.
   - `float(o.value)`를 사용할 때 발생할 수 있는 소수점 아래 Decimal 정밀도 손실을 방지하고자, 파싱된 `Decimal` 값 자체를 직접 정렬 키로 사용하도록 수정했습니다.
   - 이를 통해 추가된 `test_permutation_invariance` 등 합성 테스트에서 안전하게 순열 불변성이 유지됨을 확인(사실상 검증)했습니다.

2. **단위(Unit) 허용 목록 엄격화**:
   - 기존의 느슨한 확인(`shares` 문자열 미포함 등) 대신 명시적으로 허용된 단위만 승인하도록 수정했습니다.
   - 현재 지원 단위 범위 제한: `money` 메트릭은 정확히 `"USD"`, `per_share` 메트릭은 `"USD/shares"`, `shares` 메트릭은 `"shares"`만 허용됩니다 (요청에 따라 기타 임의 단위 제외).

3. **SEC 양식(Form) 허용 목록 적용**:
   - `form` 필드가 SEC 공식 재무보고서인 `"10-K"`, `"10-K/A"`, `"10-Q"`, `"10-Q/A"` 중 하나가 아닌 경우(예: 8-K 등)에는 `calculation_input_approved=False` 처리하고 사유를 명시하도록 제한을 강화했습니다.

4. **기간 필드 의미와 실소비 결합에 대한 제약**:
   - 현재 SEC 파서 단계에서는 duration fact의 `start`/`end` 및 `filed` 날짜 유효성을 검증해 metadata에 기록하지만, 중복되는 기간(period)들을 식별하여 최종 단일 `FinancialSet`으로 확정하고 비교/병합하는 로직은 이 파서의 책임이 아닙니다. 이 부분은 후속 실소비 경로(Phase 5)에서 수행되어야 함을 명확히 합니다.

## 미실행 검사 및 갭 (Unexecuted Tests & Remaining Gaps)
- 총괄 코디네이터는 다시 아래 명령을 통해 수정된 테스트와 기존 테스트 통과 여부를 쉘에서 직접 확인해 주시기 바랍니다.
  ```bash
  python -m unittest tests.unit.test_r04_sec_companyfacts
  ```
- 기존 `tests/unit/test_phase4_providers.py` 내부의 빈 Revenue 테스트는 총괄 책임하에 새 요구사항(`UNAVAILABLE`)에 맞춰 갱신되어야 합니다.

## 기준 커밋
- Base Commit: `65388c1a8b2813982c52148d52cb2b069924a05e` (A-01 미커밋 반영 기준)
