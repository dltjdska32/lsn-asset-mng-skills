# BRIEF-01 배정 (실행은 통합된 분석 계약 수신 후)

Gemini C / gemini-3.8-flash-high high / codex/gemini-c worktree. REQ-v1 R10–11·17·16, DESIGN-v0.1 + 실행 계약v0.2 + REVIEW-DESIGN F06/F08. 실제 코드 기준SHA는 후속 실행 메시지로 전달하며 아직 실행 지시가 아니다.

소유: runtime/investment_stack/decisions/** 신규, reporting/{models,builder,display,runtime}.py와 관련 reporting/__init__.py, tests/unit/test_r10_r11_r17_*.py 신규, handoffs/BRIEF-01.md. 다른 소유 파일/개인 DB schema 수정 금지. C의 13F 파일은 선행 단계 소유 유지하되 변경 시 이유 기록. shell/git/pip/web tools 금지. 테스트는 총괄 실행 후 피드백.

실제 분석 결과/SelectedInputSet·CalculationRecord·검증된 personal snapshot pin을 소비하는 non-posting 제안과 한국어 5단계 브리핑을 구현하라. 숫자 셀은 bound calculation/output path/selection hash/currency/unit과 연결하고 값·통화·hash 변조를 거부한다. 기존 보고 경로에서 실제 새 브리핑을 생성해야 하며 독립된 unused renderer만 만들지 않는다.

정책 absent일 때 임의 안전마진/진입범위/분할비율/가중치/위험예산/수량을 만들지 않는다. 현재가 없으면 현재가 의존 배수·매매표는 unavailable지만 독립적인 적정가/기초 재무는 보존한다. 검증된 입력과 사용자가 명시한 정책이 있으면 진입/추가매수/축소 구간·수량·금액·조건을 계산한다. 가용현금·buffer·분모가 완전한 집중한도·lot·fees·FX·보유 수량·분할합계와 손실예산 제약을 적용하고 부족자료는 구체 사유를 출력한다. 제안은 transaction mutation 함수를 호출/생성하지 않는다. 13F UNVALIDATED aggregate·차트 미승인 신호는 BUY 결정에 사용하지 않는다.

형식: 지금 판단 → 가격·행동표 → 핵심 근거 → 판단 변경 조건 → 상세 근거. 본문 내부ID·긴 원문·무관 지표·중복뉴스를 제거하되 데이터시각/지연/충돌/조건은 유지한다. 실제 계산값의 단위/반올림/표시 정책을 고정하고 display rounding이 계산 입력을 바꾸지 않게 한다. 시험용 정책값은 synthetic explicit input임을 명시.

완료 조건: 실제 renderer 연결 테스트·숫자/hash/currency tamper rejection·정책/price missing gate·수량/현금/FX/lot/분할합계·미검증 13F 차단·합성 개인DB 불변. 인계에 실제 API와 integrator 연결 요구·제한·검증/미검증·기준SHA·변경 파일을 기록한다. 개인 reader backend는 A/INTEGRATE가 소유하므로 immutable input protocol로 연결한다.
