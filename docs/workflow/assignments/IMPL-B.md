# IMPL-B / ANALYSIS-08

담당: Antigravity Gemini B, gemini-3.8-flash-high, effort high. 브랜치 codex/gemini-b. 작업 폴더 C:/Users/lsn/lsn-asset-mng-worktrees/gemini-b.
요구사항 REQ-2026-09-23-v1 R06–08·16. 설계 DESIGN-2026-09-23-v0.1 및 CONTRACT-01 검토 반영 계약. 기준 SHA는 총괄 실행 메시지의 검증된 계약 commit. 의존성 CONTRACT-01 통합·테스트.

소유: runtime/investment_stack/providers/market_quotes.py·ohlcv.py, web_research/quote_sources.py·adapter.py·bundle.py·models.py, calculations/technical.py, 신규 tests/unit/test_r06_r07_*.py·test_r08_*.py 및 B 전용 fixtures. 신설 package 내부 init 허용. 공통 provider factory/registry/contracts/deep_research/calculations init은 수정하지 말고 연결 요구를 인계한다.

구현 목표: 공개 source 후보/순서와 실제 public quote/OHLCV adapter를 주입 가능한 HTTP transport로 구현한다. source identity·종목·거래소·currency·observed/retrieved/published·delay를 검증하며 snippet을 가격으로 채택하지 않는다. market coverage가 불명확하면 unsupported. 실패 시 다음 source 시도/시도 근거 유지. live 원문 접근은 가능한 도구로 확인하고, 실제 확인 못한 source는 명확히 미검증으로 기록한다. HTTP live probe용 공개 URL/파서 호출 명령은 인계하여 총괄이 실행할 수 있게 한다. 서비스 권한 우회 금지.

OHLCV: finite Decimal, ordered completed bars, duplicate/gap/calendar/adjustment/split metadata, OHLC bounds/volume validation, 부적격 데이터 차단. 지표는 explicit caller periods만 받고 SMA/EMA/Wilder RSI/MACD/TR/ATR/volume/volatility와 trend/support/resistance/breakout 조건을 명세한다. 기간/신호 임계값을 사용자 정책으로 발명하지 않는다. 권한 없는 trading signal은 unavailable gate. 구현을 소비할 typed result/API를 A/통합자에 문서화한다.

완료 조건: design §8 R06–08 assertions, 독립 손계산 fixture, minimal samples/seed/0 denominator, prefix invariance, invalid/future/incomplete/mixed adjustment 배제. fixture와 live를 분리한다. 신규 테스트는 tests/unit 아래 discover 가능. Gemini shell/git/pip 실행 금지, 파일 read/write와 허용된 공개 웹 도구만 사용. 총괄이 테스트를 실행하고 결과를 되돌린다. 미실행 테스트 통과 주장 금지.

수정은 소유 파일과 docs/workflow/handoffs/IMPL-B.md만. 개인DB/credentials 접근·자동 주문·commit/push/타 worktree 수정 금지. 인계에 API·A/C 연결 요구·검증/미검증·남은 제한·기준SHA·변경 파일 포함.
