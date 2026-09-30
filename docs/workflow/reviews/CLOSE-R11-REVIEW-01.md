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

## 재검토 1 — 수정 source `8fc94d7ad87d3ee5ae39f784910ce58be32f2b33`

같은 독립 검토자는 앞선 시세 5종 위조·자가 기입 DCF 가치·임의 ID/flag 보고서 숫자 노출이 닫힌 것을 합성 반례로 다시 확인했다. 일요일의 정상 직전 거래일 종가는 유지됐다. 다만 **아직 통과 아님**: `market_observations.observed_at`만 근거 시각과 다르게 바꾸거나, 비달력 FRESH의 `claimed_market_time`만 오래된 시각으로 바꿔도 가격이 `verified=True`로 나오는 P1이 재현됐다. evidence/market provider ID 불일치 또는 두 source identity 모두 누락도 허용되는 P2가 재현됐다. A 담당에게 정확한 반례를 회송했다. 개인 평가·예약금·거래 규칙이 없는 실사용 R11은 계속 WAIT이며, 이 부분을 검토 통과로 해석하지 않는다.

## 재검토 2 — 수정 source `6e9b0ce70b12a7cece613eea4b3bd020ea105d9b`

저장된 두 관측시각·claimed 시각·provider 불일치와 source 누락은 차단되고 정상 일요일 직전 종가는 유지됐다. DCF 자가 기입 출처와 formatter 수치 위조도 계속 차단됐다. 독립 검토자의 .venv 집중 **25 decision + 4 report + 3 portfolio integration PASS**. **하지만 미통과**: 임의 HTTPS URI와 서로 맞춘 가짜 provider ID/이름의 근거 행은 여전히 `verified=True` 시세가 된다. URL 문자열·DB 내부 일치는 공급자 원문의 진위를 증명하지 못한다. 현재 schema에 인증 가능한 quote source-content receipt가 없으므로 D12 시세 release 자체를 fail-closed 하도록 A에 재회송했다. 이 경계는 일반 Phase4/5의 고정 거래일 분석과 별개다.

## 최종 재검토 — 수정 source `9fa62bd30fc5214b2ee275748e28515babe8f15f`

같은 독립 검토자는 변경된 **D12 안전 대기 경계에서 새 P1/P2 없음**으로 판정했다. 저장 행끼리 일치하는 정상 FRESH와 일요일의 NASDAQ 직전 유효 거래일 종가도 달력/시각 자격은 확인하되, 인증된 공급자 원문 receipt가 없어 D12 `quote_per_share=None`과 명시적 이유를 반환한다. 가짜 HTTPS URI/제공자, 잘못된 달력·시각·종목·단위·provider, 자가 기입 DCF 근거도 행동 가격으로 승격되지 않는다. 임의 ID/flag 수량 산식은 `ARITHMETIC_ONLY`, 공개 보고서는 PARTIAL/WAIT이며 진입가·예산·수량을 숨긴다. 검토자가 프로젝트 `.venv`에서 decision/report/portfolio/selected-asset/equity 집중 **63/63 PASS**를 직접 확인했고 원본 수정은 없었다.

이 판정은 **R11 실사용 완료가 아니다.** 인증 가능한 시세·DCF 원문 receipt, 개인 시가/FX·예약금·미체결 주문·수수료/거래 단위 결속이 없어 사용자별 가격·금액·수량은 WAIT다. 일반 Phase4/5의 합성 주말 종가 경로 통과는 실제 공급자 원본 진위나 광범위 거래소 일정의 검증을 뜻하지 않는다. 다른 Codex 최종 검증은 별도 기록한다.
