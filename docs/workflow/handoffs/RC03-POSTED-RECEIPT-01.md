# RC03-POSTED-RECEIPT-01 인계

- 요구사항: `REQ-2026-09-23-v1` R14/R16.
- 기준: 총괄 지정 root `c6e63d9a664d7f9f356685fd15221752328c2827`.
- Branch/worktree: `codex/luna-price-rc03-rc04` / `C:/Users/lsn/.codex/worktrees/luna-price-rc03-rc04/lsn-asset-mng-skills`.
- 담당 파일: `runtime/investment_stack/execution/dispatcher.py`, `tests/unit/test_execution_dispatcher.py`.

## 변경

- R01 독립 검토 RC03의 반례: `DECIDE_POSTING` 단계에서 POSTED receipt를 받은 뒤 `PROJECT_PERSONAL_STATE` handler가 실패하고, 이어 run-local task-state logger도 `OSError`를 내면 dispatcher 예외 경로의 `_record_state` 예외가 밖으로 전파되어 `ModeResult`가 반환되지 않을 수 있었다.
- handler 예외 및 required handler 부재 경로에서 상태 기록을 보호한다. 로깅까지 실패하면 `FAILED/RunStatePersistenceError` 상태를 반환하며 이미 확보한 mutation receipt를 유지한다.
- composite update→analysis는 posted 상태의 update가 FAILED이면 기존 receipt 검사로 분석 단계를 실행하지 않는다.

## 검증

- 전용 regression은 합성 `POSTED` receipt, project handler 예외, project state logger 예외를 함께 주입하고 `FAILED` 결과, POSTED receipt 보존, `RunStatePersistenceError`, 후속 analysis 미실행을 확인한다.
- 실행: `tests.unit.test_execution_dispatcher`: **8/8 PASS**.
- 개인 DB는 사용하지 않았다. run-local log는 synthetic stub이며 주문·원장 write가 없다.

## 남은 문제

- 실제 원장 서비스의 원자적 write/reprojection 장애는 synthetic handler boundary 밖이다. 공개·개인 DB를 대상으로 검증하지 않았다.
