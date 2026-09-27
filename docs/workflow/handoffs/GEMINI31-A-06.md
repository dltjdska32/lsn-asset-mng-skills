# GEMINI31-A-06 Handoff

## 수정 사항 (Changes)
1. **`tests/unit/test_contract_request_descriptors.py` 재작성**
   - pytest 종속성을 제거하고 `unittest.TestCase` 및 `tempfile.TemporaryDirectory`를 사용하도록 변경하여 표준 venv 환경에서 실행 가능하도록 수정했습니다.
   - `add_contract_evidence`에 불완전한 딕셔너리 대신, `MarketQuote` DTO와 `encode_envelope`를 사용하여 실제 런타임과 동일한 방식으로 증거 데이터를 생성하도록 수정했습니다.
   - `test_policy_version_mismatch` 테스트는 정상적인 typed evidence를 먼저 등록한 후, 직접 DB에 접근하여 `eligibility_decisions` 메타데이터를 수정하는 방식으로 구현했습니다.
   - `test_corrupt_descriptor_and_reopen` 테스트는 손상된 해시로 인한 실패를 예상할 때 예외를 잡는 대신, `manager.open()`이 반환하는 `RunValidationReport`의 `valid == False`를 확인하도록 assert 구문을 수정했습니다.

## 미실행 검증 및 남은 갭 (Unexecuted Tests & Remaining Gaps)
- 쉘 실행이 금지된 Headless 환경으로 인해, 총괄 코디네이터가 아래 커맨드를 통해 직접 테스트를 실행하여 결과를 확인해야 합니다.
  ```bash
  python -m unittest tests.unit.test_contract_request_descriptors
  ```
- 테스트 격리 및 DTO 생성 방식이 기존 unittest와 완전히 일치하는지 실제 환경에서의 동작 확인이 필요합니다.

## 기준 커밋
- Base Commit: `077ee538e13ff470900cb628ac3caa40ceee8581` (A-05 미커밋 변경사항 포함)
