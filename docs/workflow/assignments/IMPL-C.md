# IMPL-C / ANALYSIS-13

담당: Antigravity Gemini C, gemini-3.8-flash-high, effort high. 브랜치 codex/gemini-c. 작업 폴더 C:/Users/lsn/lsn-asset-mng-worktrees/gemini-c.
요구사항 REQ-2026-09-23-v1 R12–13·16. 설계 DESIGN-2026-09-23-v0.1 및 CONTRACT-01 검토 반영 계약. 기준 SHA는 총괄 실행 메시지의 검증된 계약 commit. 의존성 CONTRACT-01 통합·테스트.

소유: runtime/investment_stack/providers/sec_13f.py, institutional/{models,normalize,compare,scoring,validation}.py와 해당 신규 package init, 신규 tests/unit/test_r12_*.py·test_r13_*.py 및 C 전용 fixtures. 공통 contracts/provider factory/registry/deep_research는 수정하지 말고 연결 요구를 인계한다.

목표: SEC 원문/version을 확인해 공개시점(as-of)/holding quarter/retrieved 분리, date-only conservative cutoff, 원본·대체·추가 정정 체인, SH/PRN·put-call·CUSIP identity·신고 value scale·split·coverage/confidential omission을 보존한다. 주입 가능한 transport 기반 수집→XML parse→effective holdings→동일 비교범위 변화 경로를 구현한다. 평가금액≠매입원가, 부재≠매도. 실제 live 접근·schema reference와 fixture 검증을 구분한다. 접근 못한 source는 숨기지 않는다.

R13은 point-in-time feature·검증 harness를 구현하되 실제 검증 데이터/사전 등록 기준/비용·baseline/holdout·coverage/누출 검증 없이는 UNVALIDATED이며 매매 판단에 반영 금지. 임의 가중치·threshold를 승인된 production 기본값으로 발명하지 않는다. Feature·검증 report API를 통합자에 제공한다.

완료 조건: design §8 R12–13 원본/정정 cutoff, addition/restatement·중복·confidential/notice·missing identity·units/split/coverage fixtures; future leakage와 미승인 점수 gate 실제 소비 경로 테스트. 신규 테스트는 tests/unit 아래 discover 가능. Gemini shell/git/pip 실행 금지, 파일 read/write와 허용된 공개 웹 도구만 사용. 총괄이 실행·검증 후 피드백한다. 미실행 테스트 통과 주장 금지.

수정은 소유 파일과 docs/workflow/handoffs/IMPL-C.md만. 개인DB/credentials 접근·자동주문·commit/push/타 worktree 수정 금지. 인계에 API·A/B 연결 요구·검증/미검증·남은 제한·기준SHA·변경 파일 포함.

실행환경 보완: print mode read_url이 실제 soft-deny되므로 현재 Gemini는 자기 worktree의 file read/write만 사용한다. 웹/셸/외부폴더 도구 금지. 총괄의 로컬 source-checks 및 workspace/runs/source-inputs 공개 응답을 사용하고 추가 live endpoint는 인계 요청한다. 총괄 조회와 본인 검증을 구분한다. TLS 검증 비활성화나 인증정보 발명 금지.
