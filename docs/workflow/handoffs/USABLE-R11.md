# USABLE-R11 저장 원문 결속 인계

- 기준 커밋: `feadc133347ddcb40fce83fc2089810f3e78d586`. 브랜치: `cursor/usable-r11-binding`. 이 결속은 아직 커밋하지 않았다. `investment-stack-for-gpt.zip`은 업로드 산출물이며 변경에 포함하지 않는다.
- 실행: 한 Cursor 세션이 같은 작업 폴더에서 순차 수정했다. 구현 A/B/C용 별도 브랜치·worktree 병렬은 하지 않았다. 개인 실제 DB, 자동 주문, 라이브 시세 재조회는 실행하지 않았다.
- 시세·DCF: `source_documents`에 본문과 sha256을 저장한다. `yahoo_chart_v1`, `naver_quote_v1`, `explicit_dcf_assumption_v1`가 종목·통화·시각·세션·값을 다시 뽑을 때만 verified Money가 된다. 본문이 없으면 기존 CLOSE-R11 WAIT 문구를 유지한다. 주말의 마지막 유효 거래일 종가는 `LAST_VALID_CLOSE`다.
- D09: 보수·기준·낙관 가정이 원문 excerpt와 저장 계산에 모두 맞을 때만 적정가를 연다. 근거 없는 beta/ERP/terminal/성장률 기본값은 없다. 적정가는 시장 예측 가격이 아니다.
- 개인 원장: 수량·현금·부채는 POSTED 투영이다. 비상자금·예정 지출·미체결 주문은 `reservation_coverage`가 그 state_version을 COMPLETE로 선언할 때만 합산한다. 선언이 없으면 WAIT다. 빈 선언은 예약 0이라는 명시 진술이다. 평가액은 시가 합 + 현금 − 부채다. 투자가능 현금은 현금 − 예약이다. 통화가 다르면 `yahoo_fx_v1` 재추출이 있을 때만 변환한다.
- D12 B: 브리핑이 run.db와 원장을 다시 읽을 때만 조건부 진입가·예산·수량·축소 조건을 쓴다. 호출자가 만든 정책·수량 객체는 숫자를 열지 못한다. 주문과 원장 반영은 없다.
- 호스트·CLI: 두 경로가 있을 때만 7개 모드 호스트를 연다. 하나라도 없으면 오류, 둘 다 없으면 빈 서비스와 exit 3. 호스트는 라이브 조회를 거부한다. CLI JSON의 `report_sections`는 저장된 섹션 문장이다.
- 차트·13F: 차트 숫자는 저장 봉 재계산 섹션이 AVAILABLE일 때만 브리핑에 일부 들어가며 매매 수량이 아니다. 포트폴리오 호스트는 연구 스펙 없이 차트 숫자를 만들지 않는다. 13F 거래 반영은 DISABLED다.
- 스키마: run migration 3 `source_documents`, personal migration 4 `reservation_coverage`/`cash_reservations`. 둘 다 append-only다.
- 검증: 프로젝트 `.venv`로 `python -m unittest discover -s tests` → **704 OK, skip 1**. 그 전에 같은 suite가 기존 `dist` 파일 PermissionError로 패키징 2건만 실패했고, `python -m build --outdir dist` 뒤 재실행이 통과했다. 패키징·스킬 미러 테스트 11개 중 설치본 검사 1개는 skip, 나머지는 OK. 합성 E2E는 현금 100000 USD, NASDAQ:ABC 10주, 시세 100, 기준 적정가 125, 예약 1750, 투자가능 현금 97250, 평가액 100000, 1·2·3차 100.00/93.75/87.50 USD에 23/24/26주, 추가 예산 7000 USD, 거래 건수 불변. 원문 없는 run은 `진입 가격·금액·수량 대기`.
- 독립 검토: 구현과 다른 세션이 `reviews/USABLE-R11-REVIEW-01.md`에 기록했다. 집중 26 OK와 합성 프로브 10/10. 지정 실패 모드에서 새 P1/P2 없음. 전체 704는 그 검토가 반복하지 않았다.
- 최종 검증: 검토와 다른 세션이 `reviews/USABLE-R11-VERIFY-01.md`에 기록했다. 그 세션이 직접 `python -m unittest discover -s tests`를 실행해 **704 OK(skip 1)**를 확인했다. runtime/tests는 수정하지 않았다.
- 남은 WAIT: 라이브 공급자 본문의 진위, 실제 개인 금액 입력, 2026-09 고정 달력 밖의 거래일, 기간 외 13F 채택, 포트폴리오 모드의 저장 연구 스펙이 없는 차트 숫자.
