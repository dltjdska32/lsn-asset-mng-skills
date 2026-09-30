# GEMINI31-C-ACTION-04 — WAIT 본문 수량 누출 및 산술 입력 검증

Gemini 3.1 Pro High C, HEAD `f7d74653b093ef2b13980658bedd72b66bc1696e` + ACTION-01~03 미커밋. C action.py/test_action.py/handoff만; file read/write only, RunCommand/shell/git/tests/pip/web 금지. 총괄 테스트.

ACTION-03 12/12 tests PASS이나 안전 검토에서 아직 결함: `ActionProposal`은 tranches=()여도 `conditions`에 `"Arithmetic evaluated BUY for 40 units"`처럼 **실행 가능한 수량/가격**을 노출한다. provenance registry 없는 현재 public proposal에서는 임의 approval_ref/policy_version/13f_gate/chart_gate 문자열만으로 수량·금액·매수가·매도가가 conditions/reasons/기타 필드에 노출되면 안 된다. public `calculate_action_proposal`은 WAIT/결측·필요한 검증 조건만 주고 숫자 산술은 호출하지 않거나 내부 `BudgetArithmeticResult`에만 둔다. 테스트에서 임의 문자열 정책 + 값으로도 public result 전체에 거래 수량·금액이 없고 tranches 비어있음을 확인하라. 등록/검증된 정책 타입이 없으니 조건 문자열도 '검증 대기' 정도로 한정한다.

순수 `calculate_budget_arithmetic`은 외부 호출이 가능하므로 Decimal type/finite/domain을 먼저 검증해 lot_size=0, 음수 budget/price/fees, NaN/Infinity, 잘못된 FX, 빈/불명 currency에 대해 exception 대신 invalid result를 반환하도록 한다. 명시된 quote/budget currency가 같은 때만 identity rate 1을 허용한다. 단일 tranche 계산이므로 여러 tranche 합계가 안전하다고 주장하지 않는다. `assert policy is not None` 등 운영 입력 검증으로 부적합한 구문도 제거하라. 현재 실제 A 결과/정책 registry 연결은 미완임을 인계에 유지한다. `handoffs/GEMINI31-C-ACTION-04.md` 기록.
