# INTEGRATE-01 배정 (분석·브리핑 결과 통합 후)

Gemini A / gemini-3.8-flash-high high / codex/gemini-a worktree. REQ-v1 R14·16 및 R01–17 전체 연결, DESIGN-v0.1/실행v0.2/REVIEW-DESIGN F06–F08. 기준SHA는 후속 실제 실행 메시지로 지정하며 아직 실행 지시가 아니다.

소유: routing/**, pipelines/**, execution/** 신규, cli.py, asset_analysis.py, deep_research.py, providers/{registry,factory,__init__}.py, evidence/manager.py·contracts/**의 필요한 검토된 연결, 공통 exports/config/invariants, 신규 tests/unit/test_r14_r16_*.py·통합 테스트, handoffs/INTEGRATE-01.md. B/C 파일 직접 수정 금지, 연결 문제는 인계 요청. legacy 테스트 수정이 필요한 경우 안전 계약을 약화하지 않고 변경 이유를 기록하라. shell/git/pip/web tools 금지, tests는 총괄 실행.

일곱 RequestMode를 그대로 유지하고 fixed pipeline의 실제 execute_mode 및 CLI execute(JSON 입력 파일)을 구현한다. route/plan 반환만으로 완료를 주장하지 않는다. SourcePlan과 eligible coherent selection, 기술지표·valuation·13F·brief를 실제 결과 경로에 연결한다. 각 필수 step의 receipt와 required outputs를 검증하고 unsupported handler는 UNSUPPORTED, 부족자료는 PARTIAL/UNAVAILABLE, 예외는 FAILED로 구분한다. 빈 보고 파일 생성만으로 COMPLETED 금지.

모드별 실제 산출물: ASSET_UPDATE=확정 사건의 idempotent mutation receipt, PERSONAL_PORTFOLIO_ANALYSIS=동일 personal pin 기반 노출/집중/유동성 결과와 보고, SINGLE_ASSET_ANALYSIS=수집·계산·판단·브리핑, ASSET_COMPARISON=기간/통화 비교 가능한 자산별 결과와 비교표, PORTFOLIO_SCENARIO=명시 what-if 입력에 대한 비기록 가정 결과, THESIS_REVIEW=명시 thesis 기준과 현재 근거의 유지/훼손/부족 판정, REPORT_REFRESH=원본 분석 요청의 non-posting 재실행. 필수 사용자 입력이 없으면 fabricated input 대신 구체적인 partial 상태.

질문/부정/주문명령은 거래등록과 구분. UPDATE_THEN_ANALYSIS는 기존 확정 mutation receipt 후 새 pin, draft 제외, retry idempotency, refresh에서 과거 mutation replay 0회. reader는 단일 검증 read transaction에서 db_instance/version/projection 일관성 확보·immutable snapshot 반환. 개인 schema 불변, run DB에 개인 원장 전체 복제 금지. 일반 단일 분석은 개인 DB 생성/접근을 요구하지 않는다. 자동 주문 없음.

완료 조건: 7모드 각각 실제 결과 assertions, mixed request/confirmed/draft/negation/refresh, synthetic personal DB invariance, collection→normalization→selection→calculation→decision→Korean briefing E2E, future/stale/invalid scale·source failure 포함. latest selected snapshot 재선택 금지와 calculated input binding 숫자 일치 확인. 실증하지 않은 live market/13F weights는 제한을 유지한다.

인계에 exact entrypoints/options/input examples(합성만), actual/partial/unsupported 결과표, 바뀐 API·파일·버전·테스트·제한을 기록한다. PACKAGE-B에 확정 API와 필요한 truststore Windows 의존성/패키지데이터 설정을 전달할 수 있게 작성한다.
