# GEMINI31-C-ACTION-02 — 행동 산식 첫 테스트와 fail-closed 검증

Gemini 3.1 Pro High C, HEAD `f7d74653b093ef2b13980658bedd72b66bc1696e` + ACTION-01 미커밋 코드. C `decisions/action.py`, C 전용 test_action.py 및 handoff만. file read/write만; RunCommand/shell/git/tests/pip/web 금지. 총괄 테스트.

ACTION-01 최종 provider `ERROR`였지만 코드가 남아 총괄이 `tests/decisions` 13개를 실행했고 **11 PASS, 2 ERROR**. `test_buy_budget_constraints`는 예산으로 1 lot도 살 수 없는 경우 함수가 빈 tranches를 정확히 반환하는데 테스트가 `[0]`을 읽어 IndexError. 빈 tranches/WAIT/reason으로 수정. `test_sell_quantity_cap`은 실제 InvestmentDecision enum에 없는 `SELL`을 사용해 AttributeError; 지원 값 `REDUCE`를 사용한다.

안전 경계도 함께 고친다. 현재 코드의 `policy.get('fees',0)`, `verified_fx=1`, `currency='USD'`, `target_sell_quantity=disposable_quantity` 등 결측 default로 실제 규모를 만들어서는 안 된다. 승인된 입력이 없으면 금액/수량은 unavailable. `assert isinstance(...)`는 운영 검증이 아니므로 명시적 타입/finite/domain 검증으로 fail-closed 처리한다: 가격·가치>0, margin 0<=m<1, lot>0, fees>=0, FX>0, budget/available cash/headroom/risk budget 비음수, bool/문자열/nonfinite 거부. 다른 통화이면 검증된 환율과 통화 방향/기준을 요구하고 임의 1:1 FX를 쓰지 않는다. `policy`가 단순 존재하는 것만 승인으로 오인하지 말고 승인 근거/버전 입력이 없으면 WAIT. 개인 `state_version`도 입력 state와 결속돼야 한다. 13F/차트 플래그를 임의로 `UNVALIDATED`가 아니라고 적어 BUY가 열리지 않게 검증된 gate만 사용한다. 앞선 A 도메인/정책 registry가 없으므로 끝까지 non-posting WAIT/조건부 초안만.

각 오류·음수/0/NaN/문자열/누락/통화/lot/fees/예산/매도 상한을 합성 unittest로 검사하고, 실제 개인 DB는 사용하지 않는다. `handoffs/GEMINI31-C-ACTION-02.md`에 변경/미실행 검증/남은 완성 범위 기록.
