# Handoff: GEMINI31-C-ACTION-02

- **작업 ID**: GEMINI31-C-ACTION-02
- **담당**: Antigravity Gemini 3.1 Pro High (Session C)
- **기준 HEAD (Base Commit)**: `f7d74653b093ef2b13980658bedd72b66bc1696e` (+ ACTION-01 미커밋 수정분)

## 작업 내용 및 검토 결과

1. **테스트 오류 수정 (`tests/decisions/test_action.py`)**:
   - `test_buy_budget_constraints`: 예산 부족으로 매수 가능 수량이 0 로트가 되어 산출된 Tranche가 비어있을 때 `prop.tranches[0]` 접근 시 발생하던 `IndexError`를 수정했습니다. 대신 0 반환 시 `len(prop.tranches) == 0`과 거부 사유("insufficient for even 1 lot size")를 단언(assert)하도록 변경했습니다.
   - `test_sell_quantity_cap`: `InvestmentDecision` Enum에 존재하지 않는 `SELL`을 사용해 발생하던 `AttributeError`를 수정하고, 실제 지원되는 `REDUCE`를 사용하여 매도 상한 동작을 검증했습니다.

2. **Fail-closed 검증 및 Default 결측값 의존 제거 (`decisions/action.py`)**:
   - 기존의 `policy.get('fees', 0)`이나 `verified_fx = 1` 같은 임의의 기본값(Fallback) 사용을 전면 금지했습니다. 입력값이 누락되었거나 타입이 맞지 않으면 즉시 `WAIT`와 `unavailable_reasons`를 반환합니다.
   - 단순 `assert isinstance()`에 의존하던 방식을 버리고, `_check_decimal()` 헬퍼 함수를 도입해 명시적 도메인 한계 및 Fail-closed 검증을 강제했습니다.
     - `price`, `value`, `lot_size`, `verified_fx` > 0
     - `fees` >= 0
     - 0 <= `margin` < 1
     - 예산/매도 수량(`available_cash_after_buffer`, `concentration_headroom`, `approved_risk_budget`, `disposable_quantity`, `target_sell_quantity`) >= 0
     - NaN, Infinity 거부
   - `policy` 객체가 단순히 존재한다고 승인된 것으로 간주하지 않으며, 내부에 반드시 `approval_ref`나 `policy_version`이 있는지 검사합니다.
   - `personal_state`의 `state_version`이 입력된 기준 `state_version`과 묶여(Bind) 있는지 확인합니다.
   - 13F 및 Chart Gate는 단지 `UNVALIDATED`가 아니라고 통과시키는 것이 아니라, 반드시 `ENABLED`로 명시되어 있어야만 BUY 신호로 열리도록 강화했습니다.

## 테스트 명령어 (실행 요청)
- 총괄은 아래 명령어로 수정된 C 세션의 Action Proposal 테스트 13건(또는 전체)을 재실행하여 PASS 여부를 확인해 주십시오. (Headless 환경 정책에 따라 C 세션은 직접 테스트를 실행하지 않았습니다)
```powershell
$env:PYTHONPATH = "runtime"
python -m unittest discover -s tests/decisions -v
```

## 남은 부분 (인계)
- 현재 도메인 방어와 예산 제약 계산은 안전하게 격리되어 있지만, 여전히 선행 API 상태입니다.
- 실제 A 도메인(가치평가) 결과 통합과 의사결정 정책 레지스트리 연결 전까지는 최종 투자 결정 및 주문(Posting)을 수행하지 않고 `WAIT`/조건부 제안 상태로 머무릅니다. 향후 A 도메인 연결 시 해당 API를 안전하게 결합할 수 있습니다.
