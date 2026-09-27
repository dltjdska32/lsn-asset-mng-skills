# GEMINI31-A-05 — 정상 경로 다음 반례 결속

담당 Gemini 3.1 Pro High A. Branch `codex/gemini31-a`, 기준 HEAD `077ee538e13ff470900cb628ac3caa40ceee8581` + A-01/A-02/A4 미커밋 변경. **ReadFile/ReplaceFileContent/WriteFile만 사용. RunCommand·shell·git·tests·pip·web 도구 호출 절대 금지.** 총괄이 실행한다.

총괄의 독립 positive probe `scripts/workflow/contract-request-registered-probe.py --repo <A>`가 방금 PASS, 기존 관련 45/45 PASS. 이제 `evidence/manager.py`, `contracts/storage.py`, 신규 `tests/unit/test_contract_request_descriptors.py`, 자기 `handoffs/GEMINI31-A-05.md`만 수정하라.

반례: 등록된 request가 slot `price`를 요구하는데 snapshot이 빈 slots이거나 다른 slot만 갖는 경우, evidence 없는 slot, descriptor instrument와 snapshot instrument 불일치, descriptor의 as_of 이후 공개된 typed evidence, eligibility decision의 policy_version 불일치, 손상된 저장 request descriptor 및 정상 reopen을 테스트하라. 요청 slot 집합을 완전하게 검증하고 부분 coverage는 명시적 별도 결과 없으면 snapshot 완료로 수락하지 않는다. as_of 비교는 timezone-aware 시각으로 하며 ISO 문자열의 사전식 비교에 의존하지 않는다. 공개시각은 slot 자기 주장 대신 검증된 typed evidence projection에서 읽는다. `request_hash=None` legacy 경로는 보존한다. 등록/저장/읽기 시 descriptor hash 재계산도 유지한다. 사소한 부분만 손대고 완료 즉시 응답하라. 실행 못 한 검증·남은 갭 인계.
