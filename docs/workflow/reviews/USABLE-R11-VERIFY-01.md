# USABLE-R11 최종 검증

검증자: 구현자·독립 검토(`USABLE-R11-REVIEW-01.md`)와 분리된 최종 검증 세션.  
구현자 704건 주장과 검토 문서를 증명으로 쓰지 않고, 이 작업 트리에서 명령을 직접 재실행했다.  
커밋·push·runtime/tests 편집 없음. 이 파일만 작성.

## 1. HEAD·상태

| 항목 | 결과 |
| --- | --- |
| 브랜치 | `cursor/usable-r11-binding` |
| `git rev-parse HEAD` | `feadc133347ddcb40fce83fc2089810f3e78d586` |
| HEAD 일치 | 예 (요구와 동일) |

`git status --short` (요약):

- 수정(`M`): `IMPLEMENTATION_STATUS.md`, `README.md`, `docs/workflow/decisions.md`, `docs/workflow/tasks.md`, `runtime/investment_stack/cli.py`, decisions·evidence·execution·migrations·personal·reporting 관련 다수, `tests/decisions/test_policy_b_market.py`
- 미추적(`??`): `docs/workflow/handoffs/USABLE-R11.md`, `docs/workflow/reviews/USABLE-R11-REVIEW-01.md`, `investment-stack-for-gpt.zip`(무시), `runtime/.../host.py`, `source_receipt.py`, `reserves.py`, `auxiliary_context.py`, migrations v0003/v0004, `tests/integration/test_usable_policy_binding.py` 등

바인딩은 **미커밋** 상태로 확인. 원격 push·커밋은 수행하지 않음.

## 2. 전체 단위 테스트

명령:

```text
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

결과(최종 줄, 직접 관찰):

```text
Ran 704 tests in 129.480s
OK (skipped=1)
```

종료 코드: `0`.  
패키징/dist 권한 실패는 **발생하지 않음**. `python -m build --outdir dist` 재빌드·재실행은 **하지 않음**(첫 전체 스위트가 통과).

PowerShell이 unittest의 stderr 점(.)을 `NativeCommandError`로 표시했으나, 최종 집계 줄과 exit code 0으로 통과를 확인함. 보지 않은 통과를 주장하지 않음.

## 3. 합성 바인딩 테스트 단언 확인

파일: `tests/integration/test_usable_policy_binding.py`

읽은 assertion 문자열(발췌):

- 조건부 진입 가격·수량:  
  `"1차 조건부 진입 100.00 USD/주, 예산 2333.33 USD, 수량 23주."`  
  `"2차 조건부 진입 93.75 USD/주, 예산 2333.33 USD, 수량 24주."`  
  `"3차 조건부 진입 87.50 USD/주, 예산 2333.33 USD, 수량 26주."`
- 신규 거래 없음:  
  `self.assertEqual(self.transactions_before, tuple(row["transaction_id"] for row in self.ledger.list_transactions()))`  
  (여러 케이스에서 반복)  
  `"주문이나 원장 반영은 하지 않습니다"`
- 13F ≠ 매매 조건:  
  `"13F 점수는 기간 외 검증 전 매매 조건으로 사용하지 않습니다"`
- 문서 없는 런 → WAIT:  
  `"진입 가격·금액·수량 대기"`  
  `self.assertNotIn("조건부 진입", markdown)` (`test_run_without_source_documents_keeps_action_numbers_waiting`)

## 4. Host·CLI 안전 경계

`runtime/investment_stack/execution/host.py`:

- `_refuse_live_fetch`: live URL 호출 시 `RuntimeError("configured host does not call live providers")` 발생.
- `compose_configured_host`: `build_default_provider_executor(..., transport=_refuse_live_fetch)`로 live fetch 거부.
- `open_configured_host`: 호출자가 준 `run_workspace`·`personal_db`만 연다.

`runtime/investment_stack/cli.py` `execute` 경로:

- 양쪽 경로가 없을 때 `open_configured_host`를 호출하지 않음 (`services is None`이면 빈 `RuntimeServices()`로 `execute_mode`).
- 한쪽만 있으면 `parser.error("configured execute host requires both --run-workspace and --personal-db")`.
- 양쪽이 있을 때만 `open_configured_host(...)` 호출.

합성 테스트 `test_cli_without_paths_stays_unconfigured_and_configured_cli_matches`도 bare CLI가 exit `3` / `"UNSUPPORTED"`임을 단언.

## 5. `check_13f_trade_gate` 호출 위치

런타임 호출 사이트(읽은 위치):

- `runtime/investment_stack/reporting/auxiliary_context.py` → `trade_context_note()` 내부에서만 `check_13f_trade_gate(...)` 호출.
- 용도: 고정 문구 `"13F 점수는 기간 외 검증 전 매매 조건으로 사용하지 않습니다..."` 및 `GateState.DISABLED` 상태 표시.
- `scoring.check_13f_trade_gate` 본체는 항상 `GateState.DISABLED`를 반환(주문 활성화 발명 금지).

주문/사이징/원장 반영 경로의 조건으로 쓰이지 않음을 이 호출 사이트와 DISABLED 반환으로 확인. P1/P2로 볼 근거는 이번 검증 범위에서 찾지 못함.

## 6. 판정

**이 작업 트리(HEAD `feadc133…` + 미커밋 바인딩)는 검증 통과.**

- 전체 스위트: 704 Ran, OK, skipped=1 (직접 관찰).
- 합성 바인딩·host live 거부·CLI 미구성·13F 비주문조건 확인.
- P1/P2 미발견 → pass로 기록. 발견했다면 pass라고 하지 않았을 것임.

### 남은 WAIT (범위 밖·의도적 미충족)

1. **live vendor authenticity** — 실벤더 본문·서명 진정성 미검증; host는 live fetch 거부.
2. **real personal amounts** — 실제 개인 DB·실금액 미사용(합성 원장만).
3. **calendar outside pinned September 2026** — `AS_OF`/`OBSERVED`가 2026-09-28 핀; 그 밖 달력 시나리오 미검증.
4. **out-of-period 13F** — 기간 외 13F는 매매 조건으로 쓰지 않으며, 기간 외 검증·가중치 승인 자체는 여전히 WAIT/DISABLED.

범위: 실제 개인 DB·자동 주문·live provider 호출 없음. `investment-stack-for-gpt.zip` 무시.
