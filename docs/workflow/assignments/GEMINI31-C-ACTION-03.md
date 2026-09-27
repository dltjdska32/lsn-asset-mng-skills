# GEMINI31-C-ACTION-03 — 승인 문자열로 조건부 수량 노출 차단

Gemini 3.1 Pro High C, HEAD `f7d74653b093ef2b13980658bedd72b66bc1696e` + ACTION-01/02 미커밋 코드. C decisions/action.py 및 tests/decisions/test_action.py, 새 handoff만. file read/write only; RunCommand/shell/git/tests/pip/web 금지. 총괄이 실행한다.

ACTION-02 신규 포함 decisions 13/13 PASS지만 **안전 계약 미완**: `policy_version`/`approval_ref` 임의 문자열만 입력하면 현재 `ActionProposal(decision=WAIT,tranches=(quantity>0,...))`가 나오고, `policy.get('requires_fx')` 거짓이면 통화 결속 없이 `fx_rate=1`을 발명한다. 승인 registry/개인 pin verification이 아직 없으므로 public ActionProposal에는 임의 문자열만으로 실행 가능한 수량·금액·tranche를 노출하지 마라. 정책/개인 pin의 검증된 provenance가 없는 현 단계에서는 `WAIT`, `tranches=()`와 필요 정보/조건만 반환한다. 숫자 연습이 필요하면 별도 **순수 arithmetic 결과** 타입/함수로 분리해 명시적 입력에서 budget min, fee+lot floor, sell cap을 계산하고 그 결과를 ACTION 제안으로 자동 승격하지 마라.

가격 통화와 예산 통화, FX 방향을 명시적으로 입력받아 비교하라. 같은 통화일 때만 1:1 identity, 다른 통화면 검증된 `budget_currency per quote_currency` 환율·시각·근거 없으면 unavailable; `requires_fx` 같은 caller bool로 판정하지 않는다. 수수료 단위(quote currency/per-unit인지 총액인지)를 고정하고 budget 내 총합을 증명한다. `policy`/`personal_state`의 모든 문자열 키·값은 신뢰된 승인/핀의 증거가 아님을 코드와 테스트에 반영한다. 금액 음수/0/비유한/문자열, lot, FX, 통화 불일치, 가짜 approval_ref, 자료 누락, 여러 tranche 합계 방어 테스트를 추가. A 도메인/정책 검증 연결 전 최종 판단은 보류.

`handoffs/GEMINI31-C-ACTION-03.md`에 13 PASS였어도 인수하지 않은 이유, 실제 수정/미실행 테스트/남은 API 연결을 기록.
