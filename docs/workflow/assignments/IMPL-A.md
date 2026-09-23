# IMPL-A / ANALYSIS-09

담당: Antigravity Gemini A, `gemini-3.8-flash-high`, effort high. 브랜치 codex/gemini-a. 작업 폴더 C:/Users/lsn/lsn-asset-mng-worktrees/gemini-a.
요구사항 REQ-2026-09-23-v1 R01–05·09·16. 설계 DESIGN-2026-09-23-v0.1 및 CONTRACT-01의 검토 반영 계약. 기준 SHA는 총괄 실행 메시지의 검증된 계약 commit을 따른다. 의존성 CONTRACT-01 통합·테스트.

소유: runtime/investment_stack/freshness/{engine,models}.py, evidence/research.py, providers/{execution,adapters}.py, research.py, deep_research.py, normalization/**, calculations/{valuation,equity,common}.py, 신설 valuation assumptions 모듈, 신규 tests/unit/test_r01_r05_*.py·test_r09_*.py 및 A 전용 fixtures. 공통 contracts는 계약 완료 이후 변경 요청만 기록하며 기존 다른 테스트는 수정하지 않는다. 기존 API 호환이 안전과 충돌하면 원인과 필요한 기존 테스트 변경을 인계한다.

구현 목표: 새 라이브러리만 만들지 말고 실제 deep_research 수집→선택→재무/가격 계산 경로를 수정한다. 목적별 선택 결과를 재사용하고 provider_results 원시 배열에서 재선택하지 않는다. STALE/UNKNOWN/future 가격 차단, 기간/기준 coherence, 명시적 invalid scale fail-closed, SEC nested companyfacts 실제 fact mapping·날짜-only 공개 cutoff·정정 vintage, unusable/partial 이후 fallback 및 적격 기존 metric 보존. DCF는 FCFF/FCFE/순부채·현금/주식수 domain과 출처 있는 명시적 가정, 보수·기준·낙관·민감도·입력계보. 정책 없는 숫자는 unavailable/conditional로 남기고 임의 defaults를 넣지 않는다.

완료 조건: design §8의 R01–05·09 반례를 실제 소비 API까지 검증하는 독립 fixture assertion, input permutation, invalid/nonfinite/unit mismatch, restatement/future date, fallback 순서·coverage, DCF domain와 lineage. 새로운 test 이름은 unittest discover에 포함되도록 tests/unit 아래에 둔다. 테스트 실행은 총괄이 수행하며 결과를 돌려준다. Gemini는 shell 도구·git·pip를 실행하지 않고 읽기/쓰기 도구로 구현한다. 테스트를 실행하지 않았다면 통과를 주장하지 않는다.

수정은 소유 파일과 docs/workflow/handoffs/IMPL-A.md만. 코드·문서에서 개인 데이터·credentials 접근 금지. 자동주문 금지. commit/push/타 worktree 수정 금지. 인계에 추가/변경 API, B/C 연결 요구, 실행/미실행 검증, 제한과 미완료를 구분한다. 기준 SHA와 최종 소유파일 목록 포함.
