# IMPL-C-FIX-03 — C 체크포인트의 규칙·테스트 일치

- 담당: Antigravity Gemini C, 기존 conversation `a0efd37f-f4f2-4e2b-b7bc-8378c4a29926` / `codex/gemini-c` / 별도 worktree `C:/Users/lsn/lsn-asset-mng-worktrees/gemini-c`.
- 기준 코드: `377dbb4e7c3f29bfd011c049acf4dd9dd98def0f` (WIP). REQ-v1 R12–13, 설계 v0.1, D18. 소유: providers/sec_13f.py, institutional/**, C 전용 테스트·인계. A/B 공통 파일 금지. 한도 초기화 뒤 21:40 KST 이후 실행.
- 현재 담당 26 tests에서 2 FAIL. `test_missing_row_coverage_and_absence_safeguard`는 filed_date 자체가 빠져 생기는 scale 경고와 누락행 2건 경고를 합쳐 3건인데, 2건을 기대한다. 경고를 삭제하지 말고 각각의 사실과 coverage 전파를 검사한다. `test_trade_gate_allows_formal_approval_with_validated_report_only`는 synthetic `score_status='VALIDATED'`+문자열 approval_ref만으로 ENABLED를 기대해 현재 안전한 disabled gate와 충돌한다. 실제 backtest/holdout/cost/승인 registry가 없으므로 기대를 DISABLED로 고치고 가짜 승인 경로를 부정 테스트로 만든다. A의 trusted typed gate context가 완료된 뒤 실제 연결을 별도로 검증한다.
- source vintage를 report period로 추정하지 않고 UNKNOWN/불확실 척도 보존, 누락행과 amendment/absence 비교 제한을 유지한다. 실제 SEC archive XML은 현재 403이므로 live 원문 E2E가 됐다고 적지 않는다. 담당 테스트 및 기존 반례 실행·정확한 HEAD·미확인 한계를 `docs/workflow/handoffs/IMPL-C-FIX-03.md`에 기록한다.
