# GEMINI31-A-01 Handoff

## 기준 커밋 (Base Commit)
`077ee538e13ff470900cb628ac3caa40ceee8581`

## 실제 변경 (Actual Changes)
1. `contracts/storage.py`:
   - `empty_contract_storage`에 `"requests": []` 키를 추가하여 ledger 스키마를 업데이트했습니다.
   - `validate_contract_storage_ledger`에 `requests` 리스트 내 항목의 딕셔너리 구조와 `envelope` 존재, 그리고 descriptor hash의 재계산 및 무결성 검증을 추가했습니다.
   - `SelectionRequest`의 직렬화/역직렬화를 담당하는 `serialize_request_envelope`와 `deserialize_request_envelope` 함수를 구현하여 payload 예산 초과를 검사하도록 했습니다.
2. `evidence/manager.py`:
   - `persist_selection_request` API를 신규 추가하여, 유효한 `SelectionRequest`를 `run_metadata`의 `_contract_storage_v2` 내 `requests` 배열에 저장하도록 구현했습니다. (멱등성(Idempotent retry) 처리 포함)
   - `persist_contract_snapshot` 내에 `snapshot.request_hash`가 지정되었을 때, 이를 저장소 내의 등록된 request와 대조·검증하는 로직을 추가했습니다.
   - 유효한 64-hex 해시지만 등록되지 않았거나, 내부 해시가 변경/손상된 경우 `InputIntegrityError`를 던지도록 했습니다.
   - 스냅샷의 `purpose`, `instrument_id`와 요청의 `purpose`, `instrument_id`의 일치를 확인합니다.
   - 각 `BoundSlotInput`이 `SelectionRequest`에 포함된 슬롯인지 확인하고, `SlotSpec.matches_candidate`와 metric 대조를 통해 선택된 증거가 descriptor가 요구하는 기간(period), 통화(currency), 측정값(metric) 조건을 충족하는지 엄격히 검증하도록 했습니다.

## 공개 API (Public API)
- `RunDatabaseManager.persist_selection_request(request: SelectionRequest) -> None` 추가
- `investment_stack.contracts.storage.serialize_request_envelope` 추가
- `investment_stack.contracts.storage.deserialize_request_envelope` 추가

## 실행한 검증 (Executed Verifications)
- 없음 (헤드리스 모드 지시로 인해 `contract-request-descriptor-probe.py` 등 테스트를 직접 실행하지 않음).

## 남은 결함 및 미실행 검증 (Remaining Issues & Unexecuted Tests)
- `workspace/runs/contract-request-descriptor-probe.py`를 총괄(Coordinator) 봇이 직접 실행하여 검증해야 합니다.
- 기타 전체 계약 관련 단위/통합 테스트 스위트를 실행하여 `requests` 스토리지 추가로 인한 기존 S1/S2 파이프라인의 회귀(Regression) 여부를 확인해야 합니다.
- `manager.py`의 `run_metadata` 내 JSON 크기 증가가 최대 payload 한도에 어떤 영향을 미치는지 대규모 실행에서 확인이 필요할 수 있습니다.
