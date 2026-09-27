# GEMINI31-A-05 Handoff

## 작업 내역 (Changes Made)

1. **`runtime/investment_stack/evidence/manager.py` 수정**
   - `persist_contract_snapshot` 내에서, SelectionRequest에 정의된 요청 slot 집합이 모두 제공되었는지 검증하도록 추가했습니다 (부분 coverage 불가 원칙 구현).
   - `as_of` 비교 로직을 timezone-aware `datetime`으로 변환하여 비교하도록 수정했습니다 (ISO 문자열 사전식 비교 제거).
   - `as_of` 공개 시각 확인 시, snapshot의 `slot.public_available_at` 주장이 아닌, 검증된 `canonical` projection의 `public_available_at` 값을 읽어서 비교하도록 변경했습니다.

2. **`tests/unit/test_contract_request_descriptors.py` 신규 작성**
   - 빈 slots 제공, 요청되지 않은 다른 slot 제공, evidence 없는 slot 제공 등의 예외 상황 반례 추가.
   - Descriptor와 snapshot의 instrument 불일치 반례 추가.
   - Timezone-aware 기반 `as_of` 이후의 evidence 검출 반례 추가.
   - Eligibility decision의 `policy_version` 불일치 검증 테스트 포함.
   - 손상된 request descriptor hash 시뮬레이션 후 `manager.open()` 실패 및 정상 복구 후 reopen 성공 확인.
   - `request_hash=None` 레거시 경로 정상 작동 확인.

## 기준 정보

- **Base Commit**: `077ee538e13ff470900cb628ac3caa40ceee8581`

## 남은 갭 및 미실행 검증 (Remaining Gaps & Unexecuted Tests)

- RunCommand, 테스트 도구 및 git 등 쉘 호출 권한이 전면 차단되어 있으므로 작성한 파이썬 코드를 직접 실행하여 검증하지 못했습니다.
- 총괄 코디네이터가 아래의 테스트 커맨드를 실행하여 검증을 부탁드립니다.
  ```bash
  pytest tests/unit/test_contract_request_descriptors.py -v
  ```
- 혹시 Timezone Parsing이나 Dict Key 참조(`canonical["public_available_at"]`) 과정에서 Type Mismatch(예: NoneType)가 발생하는지 실무 데이터로 확인해야 할 갭이 있습니다.
