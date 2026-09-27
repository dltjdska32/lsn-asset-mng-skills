# LUNA-A-R14-01 — 일곱 고정 요청 모드의 실제 실행

- 요구사항: REQ-2026-09-23-v1 R14·R16, 설계: DESIGN-2026-09-23-v0.1 §7·§8.
- 담당: GPT-6 Luna Medium A task `01a0e2a4-f627-7610-8cbf-fabe9bad1a70`, branch `codex/luna-a-transfer-02`, worktree `C:/Users/lsn/.codex/worktrees/f01e/lsn-asset-mng-skills`.
- 선행: A의 R02–05/R09·HTTP 슬라이스 체크포인트 인계, B/C 최신 통합 코드 전달 후 착수. 현재 공유 기준 `a5849e1`이며 실제 착수 시 총괄이 새 통합 SHA를 갱신해 전달한다.
- 파일 소유: `runtime/investment_stack/routing/**`, `pipelines/**`, 신규 `execution/**`, `cli.py`, `asset_analysis.py`와 전용 R14/R16 테스트. `deep_research.py`는 A 선행 슬라이스 종료 후 동일 담당만 수정. B의 provider/기술 계산, C의 institutional/decisions/reporting 파일은 직접 수정하지 않는다.

완료 조건은 단순 route/plan 출력이 아니라 7개 모드 각각의 서비스 호출·실제 결과물·partial/unsupported 판정·task state와 근거 참조를 확인하는 것이다. 고정 planner와 handler whitelist를 유지하고, 누락 handler를 성공 처리하지 않는다. `ASSET_UPDATE`는 확인/검증 후 기존 ledger 경유 원자적 receipt만 POSTED; draft/확인 대기/실패는 개인 DB 불변. `REPORT_REFRESH`와 시나리오는 재기장하지 않는다. 부정문·매수 질문·가정은 거래 사실로 라우팅하지 않고, 복합 요청에서 미확정 거래는 기존 확정 상태 분석에 섞지 않는다. 개인 데이터·인증정보는 합성 fixture만 사용한다.

담당 인계에는 착수 기준과 최종 commit SHA, 각 모드의 직접 실행 결과·테스트, 미실행 live 검증, 남은 제약을 기록한다. 총괄이 통합 SHA에서 별도로 회귀 확인한다.
