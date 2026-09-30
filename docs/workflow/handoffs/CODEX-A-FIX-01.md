# CODEX-A-FIX-01 인수 사본

총괄이 `codex/impl-a-luna` HEAD `16a22e0a789b3ce526934474ad3f271fee0cda33`의 원본 인계를 복사했다. 총괄이 같은 SHA에서 계약99/99, storage audit29/29, gate audit12/12를 재실행했다. 이후 유효 64-hex request_hash의 미등록 descriptor 수용이 새 반례에서 드러나 `CONTRACT-FIX-07`로 회송했으므로 공통계약 최종 인수는 보류한다.

## 기준 및 현재 상태

- 시작 기준 HEAD: 49837ea3072914a00a7c65eff484789ea94d050a; 브랜치 codex/impl-a-luna
- 구현 검증 완료 상태. 총괄이 요청한 로컬 commit은 이 인계 작성 후 생성한다.
- 개인 DB·인증정보·네트워크·자동 주문 미사용. 감사는 합성 임시 run.db만 사용.

## 변경 내용

- PublicAvailability projection에서 DTO에 없는 available_at 참조를 고치고 EXACT/DATE_INTERVAL/UNKNOWN의 exact/interval/timezone/locator 의미를 보존.
- snapshot write에서 typed envelope를 재검증하고 projection 캐시, evidence row ID, 값·통화·단위·instrument·public time 및 입력된 fingerprint/eligibility 참조를 검사.
- run open에서 contract ledger와 typed evidence projection을 검증하고 손상 시 invalid 반환.
- ledger read 시 calculation bound inputs를 참조 snapshot과 대조하고 active pointer의 target scope를 검증.
- evidence manager Decimal import 및 mappingproxy JSON projection 오류 수정.
- 13F purpose의 formula requirement 하향을 막고 gate purpose와 calculation purpose를 결속.
- A 테스트 fixture의 SelectionRequest import, canonical currency-unit 사용, cross-run FK 검증 전제 수정.

## 실행 검증

- 전체 contract unittest, root project .venv / Python 3.14 + tzdata 사용: 99 tests OK.
- 총괄 공유 contract-storage-audit-probes.py: 29 PASS / 0 FAIL / 0 BLOCKED. 정상 quote/holding snapshot, S1/S2, calc persist/reopen 및 각 저장·읽기 반례를 검사. root 공유 폴더 쓰기 제한 때문에 스크립트 사본을 임시 폴더에 두고 실행했으며 원본은 수정하지 않음.
- 총괄 공유 contract-audit-04-probes.py: 12 PASS / 0 FAIL / 0 BLOCKED.
- test_contract_storage_audit.py: 8 tests OK.
- git diff --check: 통과.

## 남은 제한

- 실제 유효 SelectionRequest descriptor를 registry/reference에 저장해 request_hash를 재계산하는 계약은 구현하지 않음. 현재는 비 SHA-256 형태 hash를 저장 경계에서 거부하며, 64자리 digest 자체가 descriptor에 연결됐는지는 아직 증명하지 못함.
- Eligibility는 evidence metadata의 eligibility_decisions에서 참조를 찾아 ELIGIBLE만 허용한다. 일반적인 persisted eligibility decision registry는 없음.
- Public time이 evidence projection에 알려져도 slot에서 생략되면 레거시 호환으로 허용한다. slot이 시간을 제공하면 typed evidence와 일치해야 하며 임의 시간은 거부한다.
- validate_calculation_for_use의 실제 downstream 소비 경로 전체 연결은 미확인이다.
- Python environment가 달랐던 첫 테스트 실행은 timezone 오류가 포함됐지만, 총괄이 알려준 venv에서 최종 전체 계약 테스트를 재실행하여 통과 확인.

## 미실행

- 전체 애플리케이션 테스트와 별도 Codex 독립 검토/최종 검증은 미실행.
- remote push/deploy 미실행.
