# LUNA-C-BRIEF-BINDING-01 인계

## 배정 및 기준

- 범위: C R10–11/R17 브리핑 숫자 표시 결속 및 비주문 안전성 검증
- 기준 커밋: `83dfb2779f5afa2932f0f196adbe80f13ac89534`
- 브랜치: `codex/luna-c-brief-binding`
- 담당 파일: `runtime/investment_stack/decisions/briefing.py`, `tests/decisions/test_briefing.py`, `tests/decisions/test_action.py`, 본 인계 문서
- 의존성: A DCF typed input 포함 통합 기준 `83dfb27`; 공통 CalculationRecord, EligibilityDecision, SelectedInputSet 계약

## 변경

- 숫자는 purpose와 typed output kind가 명시된 CURRENT_PRICE/PRICE 또는 VALUATION_MODEL/VALUATION 계산만 후보로 삼는다. 일반 `result_numeric`, 이름, 설명 텍스트는 표시값으로 사용하지 않는다.
- CalculationRecord lineage, run/snapshot, 선택 슬롯의 모든 값·단위·통화·evidence/fingerprint·eligibility ID·공개시각과 ELIGIBLE purpose별 EligibilityDecision을 대조한다. 공개시각은 분석 기준시각 이하여야 한다.
- 계산 소비 검증을 통과한 단일 양수 가격/주 산출값만 표시하고 계산 ID·evidence ID·공개시각을 상세에 남긴다. 조건부 valuation은 조건부로 표시한다. 이름이 없는 SCENARIO_VALUE를 순서에 따라 시나리오로 추정하지 않는다.
- 계산된 수치가 있어도 브리핑은 WAIT이며 진입/추가매수·축소·금액·수량은 계산 불가로 남긴다. 승인 모양 필드 또는 mapping 순서가 action proposal을 활성화하지 않음을 테스트한다.

## 검증

- 실행: `$env:PYTHONPATH='runtime'; C:/Users/lsn/lsn-asset-mng-skills/.venv/Scripts/python.exe -m unittest tests.decisions.test_briefing tests.decisions.test_action tests.decisions.test_builder_briefing -v`
- 결과: 15 tests, OK (2026-09-27).
- 포함: 적격 typed 현재가, 조건부 valuation, generic 숫자 차단, 공개시각 전 숫자 차단, WAIT/무수량, action mapping 순서 불변.
- 개인 DB는 열거나 사용하지 않았다. 주문 시스템 호출도 없다. 테스트는 메모리 내 합성 계약만 사용한다.

## 미실행 및 남은 문제

- 전체 저장소 unittest, 외부 SEC/시장 네트워크, 실제 개인 DB 연결은 실행하지 않았다.
- `SCENARIO_VALUE`에 conservative/base/optimistic를 할당하지 않는다. 해당 타입에 명시적 scenario 식별자가 없기 때문이다.
- 안전마진/진입 구간, 개인 위험 예산, 축소 정책, 13F 가중치는 이 변경에서 정의하거나 승인하지 않았다. 최종 독립 코드 검토와 별도 최종 검증은 총괄/지정 세션이 수행해야 한다.
