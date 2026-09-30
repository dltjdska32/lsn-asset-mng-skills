# GEMINI31-A-02 — request descriptor 결속 누락 보완

- 담당: Gemini 3.1 Pro High A, branch `codex/gemini31-a`, HEAD `077ee538e13ff470900cb628ac3caa40ceee8581`와 A-01 미커밋 변경. A-01 소유 파일만. shell/git/테스트/웹 금지; 총괄이 실행한다.
- A-01 실행은 마지막 모델 API 연결 오류로 receipt `status=ERROR`이지만 코드 두 파일과 인계가 실제로 기록됐다. 총괄의 독립 probe에서 미등록 64자리 해시 거부 PASS, 계약/저장/게이트/슬롯 단위 45/45 PASS. **이것은 descriptor 전체 계약 통과가 아니다.**
- A-01 코드를 검토해 다음 결속 누락을 발견했다. `snapshot.instrument_id=None`이면 요청 instrument와 비교가 건너뛴다. 요청 `as_of`와 정책 버전은 snapshot/선택 근거에 연결되지 않는다. evidence_id가 없는 slot은 request_slot의 존재/metric/기간/단위 검사도 건너뛴다. request의 필수 슬롯 누락이나 빈 selection도 허용될 수 있다. `SlotSpec.matches_candidate`의 입력 메타를 단순 이름 치환하면 기간/단위/통화와 정책 제약이 실제로 확인되는지 테스트해야 한다. 잘못된 descriptor가 저장 후 fetch/reopen에서 검출되는지도 확인한다.
- 정상 SelectionRequest 등록 → 적격 스냅샷 → S1/S2 → 계산 → reopen을 유지하면서, 위 변형 각각을 거부하거나 명시적인 partial/legacy 규약으로 처리하라. 데이터 의미 없는 강제 값이나 승인되지 않은 정책 규칙을 만들지 않는다. `request_hash=None` legacy 경로 의미를 명시한다. 충분한 합성 회귀 테스트를 A 담당 테스트에 추가한다.
- A-02 인계에 실제 수정/실행하지 않은 테스트/남은 갭 기록. 총괄이 다시 probe·계약 audit·회귀를 수행한다.
