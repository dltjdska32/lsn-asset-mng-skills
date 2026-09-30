# LUNA-C-FX-RISK-FIX-01 인계

## 배정 및 기준

- 범위: C portfolio risk weights의 평가통화 정규화와 FX fail-closed 회귀
- 기준 root SHA: `57aca433d62161ad537eaabae8ca1cd31c935d73` (C portfolio service 통합 포함; 요청 최소 기준 `9873d1f` 이후)
- branch: `codex/luna-c-fx-risk-fix-01`
- C implementation source SHA: `01a8ddb3fe311fdda1d4681e4268c4b7bdede87d`
- 담당 변경: `runtime/investment_stack/reporting/portfolio_modes.py`, `tests/unit/test_r14_portfolio_modes.py`, 본 handoff
- A/B 소유 파일은 변경하지 않음. 개인 DB·거래 writer 미사용.

## 수정

- `_analyze`가 FX를 적용해 만든 평가통화 `converted_positions`를 `_risk_result`에 전달한다. risk weight는 원통화 `market_value / gross_assets`가 아니라 `평가통화 시장가치 / 평가통화 총자산`으로 산출한다.
- 평가통화 가격 series와 적격 FX가 일치해야 risk를 계산한다. FX 누락·반대 방향 pair·point-in-time 부적격으로 총자산을 평가통화로 완성할 수 없으면 gross assets와 risk를 UNKNOWN으로 둔다. FX를 암묵적으로 역산하지 않는다.
- 양성 회귀는 USD 800 + USD 200 + 현금 100과 JPY 80,000(FX 0.01 USD) + USD 200 + 현금 100의 gross=1100 및 위험 volatility 동일성을 확인한다.
- 음성 회귀는 JPY→USD 근거가 없고 반대 방향 USD→JPY만 있는 상태에서 gross/risk가 UNKNOWN임을 확인한다.

## 검증

- 관련 Phase 5/6 회귀 명령: `$env:PYTHONPATH='runtime'; C:/Users/lsn/lsn-asset-mng-skills/.venv/Scripts/python.exe -m unittest tests.unit.test_r14_portfolio_modes tests.unit.test_phase5_materiality_allocation_risk tests.unit.test_phase5_equity_valuation tests.unit.test_phase5_fund_alternative tests.integration.test_phase5_asset_runtime tests.unit.test_phase6_report_review -v`
- 결과: **47 tests PASS**, 2026-09-27. 이 중 전용 portfolio mode test 10개.
- `git diff --check`: PASS. 실제 DB·개인 자산 데이터·외부 provider·주문은 사용하지 않음.
- 전체 저장소 unittest 및 A dispatcher E2E 미실행.

## 남은 통합

- FX pair/latest eligibility 및 evaluation currency series 검증은 upstream typed inputs에서 계속 보장해야 한다. Risk weight 계산은 converted market values를 사용하며 historical risk observations는 이미 평가통화여야 한다.
- 전체 독립 코드 검토 및 별도 최종 검증은 후속 담당 범위다.
