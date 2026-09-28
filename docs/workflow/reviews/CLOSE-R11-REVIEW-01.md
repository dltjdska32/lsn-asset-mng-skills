# CLOSE-R11 독립 검토 01

- 검토 대상 source: `a01c4c19cdd32538e4c213824d3de6d128d86f3c` (2026-09-28).
- 검토자: 별도 Codex 세션 `/root/close_r11_review_01`; 구현 A/B와 총괄은 검토자가 아니다.
- 범위: R01/R09/R10/R11/R17, D12-B 시세·가치·개인 원장 결속, 비거래 보고/수량 산식. 검토자는 원본을 수정하지 않았고, 합성 임시 run.db 반례와 집중 20개 테스트를 수행했다. 검토자의 기본 Python은 `tzdata`가 없어 통합 import에 실패했으며, 총괄의 프로젝트 venv에서 36개 결합 테스트는 별도 통과했다.
- 판정: **수정 필요.** 이 source를 최종 통과로 보지 않는다.

## 재현된 문제

1. P1 R01: `policy_b_market`이 저장된 `FRESH`/`LAST_VALID_CLOSE` 문자열을 재검증 없이 가격 승인에 사용했다. 9월 28일 cutoff에서 9월 1일 시각을 `FRESH`로 표시하거나, 임의 `calendar_id`로 9월 25일 종가를 표시해도 `Money(..., verified=True)`가 나왔다. 기존 합성 fixture는 뉴욕 개장 전 시각을 당일 종가로 표시했다.
2. P1 R01: selected evidence와 결합된 market row의 `instrument_id`를 다른 종목으로 바꿔도 가격이 승인됐다. evidence `USD/share`와 market `KRW/share`/KRW 조합도 단위 불일치로 거부되지 않았다.
3. P1 R11 완료성: 개인 원장의 고정 POSTED 수량·현금·부채는 읽기 전용으로 검증되지만, 시가 평가액·포트폴리오 분모·비상자금/예정 지출·미체결 예약·수수료/거래 단위가 없다. 실제 포트폴리오 통합 경로는 따라서 항상 WAIT다.
4. P2 R09: DCF 가정 evidence의 비어 있지 않은 URI/이름과 자기 기입 값만으로 가치가 `verified=True`가 됐다. `https://example.invalid/source` 합성 fixture에서도 검증된 가치가 나왔다. 원문 내용과 값의 독립 결속이 필요하다.
5. P2 R11/R17: 공개 formatter에 임의 evidence/calculation ID와 caller-created `verified=True` 정책·거래 규칙을 주면 조건부 진입가·예산·수량을 표시했다. 반대로 축소 조건이 감지된 정책은 WAIT 분기에서 근거가 사라졌다.

## 회송과 현재 상태

- A 담당에게 1·2·4의 재현과 pinned calendar/시각·종목·단위 재검증, 불완전한 DCF source receipt의 fail-closed 처리를 회송했다. A source/재검증 대기.
- 총괄은 `42920ee`에서 formatter의 숫자 release를 닫고, 수량 산식을 `ARITHMETIC_ONLY`로 표시했다. 이 수정은 검토 대상 SHA 뒤의 변경이며 독립 재검토·최종 검증 전이다.
- 개인 실사용 입력은 아직 결속되지 않는다. 사용자 값을 임의 생성하거나 실제 개인 DB를 개발 테스트에 사용하지 않는다.
