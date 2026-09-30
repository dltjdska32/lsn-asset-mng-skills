# GEMINI31-A-03 — 짧은 descriptor 결속 마무리

Gemini 3.1 Pro High A, fresh conversation, branch `codex/gemini31-a`, HEAD `077ee538e13ff470900cb628ac3caa40ceee8581` + A-01/A-02 미커밋 변경. **파일 읽기/쓰기만 사용. `RunCommand`를 절대 호출하지 마라. 테스트/인계에 명령을 적기만 하고 실행하지 마라.**

이번 한 번에는 `runtime/investment_stack/evidence/manager.py`, `contracts/storage.py`, A 전용 `tests/unit/test_contract_request_descriptors.py`, `docs/workflow/handoffs/GEMINI31-A-03.md`만 다뤄라. 최우선은 **등록된 진짜 SelectionRequest → 적격 Snapshot의 정상 저장/reopen**을 합성 테스트로 증명하고, 잘못된 요청 해시·종목 None·요청 slot 누락·evidence 없는 선택·as_of 미래 자료·policy_version 불일치 각각을 거부하는지 확인하는 것이다. 빈/partial은 조용히 COMPLETED처럼 승인하지 말고 계약 의미를 명시한다. `request_hash=None` 기존 legacy snapshot을 깨뜨리지 않는다. 형식만 맞는 SHA는 이미 root probe가 거부 확인했다. 저장 descriptor 자체의 손상 검증도 테스트하라. 잘못된 부분만 수정하되 기존 계약 테스트 회귀를 피하라. 총괄이 테스트를 실행하고 실패를 다시 전달할 것이다.

인계에 기준 SHA, 실제 변경, 실행하지 않은 검증, 남은 gap을 짧게 기록하라. 여기까지 끝나면 즉시 답하고 중단하라.
