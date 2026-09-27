# LUNA-C-PORTFOLIO-MODES-01 인계

## 배정과 기준

- 범위: R14 `PERSONAL_PORTFOLIO_ANALYSIS`·`PORTFOLIO_SCENARIO`의 C-owned 비게시 계산/보고 서비스
- 기준 root/source SHA: `27d95e452444a1d1e2121841644362f1eadc40db`
- 구현 branch: `codex/luna-c-portfolio-modes-01`
- C 구현 소스 SHA: `d9d3e15c635226bba5c59af94f973d34d5a7b24a`
- 변경 파일: 신규 `runtime/investment_stack/reporting/portfolio_modes.py`, 신규 `tests/unit/test_r14_portfolio_modes.py`, 본 handoff
- A dispatcher/factory/execution, B calendar/quotes, C `thesis_refresh.py` 및 개인 DB는 수정/사용하지 않음

## 구현 내용과 라우터 연결 계약

- `PortfolioAnalysisRequest`는 positive `state_version`, `snapshot_ref`, 시간대가 있는 analysis/state clock, 평가통화, 자산·현금·부채, FX 근거, 위험 관측치·기간 정책·위험 정책을 타입으로 받는다. FX는 선택됨·ELIGIBLE·FRESH/CURRENT·관측/공개 기준시각이 pinned clock 이하여야 환산한다. 미평가 자산은 allocation 결과에도 유지하고, 누락 가치·FX·risk/time/policy는 UNKNOWN/PARTIAL로 표시한다.
- `analyze_portfolio(request)`는 기존 `AllocationAnalyzer` 및 `PortfolioRiskAnalyzer`의 비게시 순수 계산을 사용해 총자산/현금/부채/순자산, 평가된 자산군·통화 비중, 기간별 위험값과 승인 위험 한도를 `PortfolioAnalysisResult`와 `ReportSectionInput`으로 반환한다. 승인 위험 정책 및 기간 정책이 없으면 한도/위험은 확정하지 않는다. 내부적으로 수량·예산을 만들지 않는다.
- `simulate_portfolio_scenario(request, scenario, gate_verifier=...)`는 명시적 값 변경·가상 FX·마지막 과거가격 위험 stress를 별도 immutable 입력으로 적용해 before/after 및 알려진 delta를 반환한다. active gate references와 외부 registry verifier가 없거나 false면 WAIT이고 차이를 만들지 않는다. 불완전한 baseline도 전체 차이를 만들지 않는다. scenario FX assumption은 평가통화 방향만 허용하며 값 가정 reference를 결과에 남긴다. 위험 stress는 예측이나 최신 시세가 아님을 출력한다.
- A 고정 라우터는 확정 snapshot을 `PinnedPortfolioState` 등으로 변환하고, point-in-time 적격 observation을 제공한 다음 `ReportSectionInput`을 기존 report/review 경로에 넘긴다. Scenario의 `gate_verifier`는 실제 등록된 승인/검증 provenance를 검사하는 read-only adapter여야 한다. 보고 persistence, 자료 수집, materiality/deep research orchestration은 기존/A 소유 fixed services가 담당한다.

## 검증

- 명령: `$env:PYTHONPATH='runtime'; C:/Users/lsn/lsn-asset-mng-skills/.venv/Scripts/python.exe -m unittest tests.unit.test_r14_portfolio_modes tests.unit.test_phase5_materiality_allocation_risk tests.unit.test_phase5_equity_valuation tests.unit.test_phase5_fund_alternative tests.integration.test_phase5_asset_runtime tests.unit.test_phase6_report_review -v`
- 결과: **44 tests PASS** (신규 전용 7개 + Phase 5 allocation/risk/valuation/runtime + Phase 6 report 회귀), 2026-09-27.
- 신규 테스트는 memory-only typed fixtures를 사용했다. 보유자료·정책·FX·시계열은 모두 합성값이다. 개인 DB/임시 personal DB, run DB, 거래 writer를 열거나 호출하지 않았다.
- `py_compile runtime/investment_stack/reporting/portfolio_modes.py`: PASS. `git diff --check`: PASS.
- 전체 저장소 회귀, 외부 provider/network, 실계정/실제 DB/주문, A dispatcher end-to-end는 실행하지 않았다.

## 남은 문제

- 서비스는 입력으로 받은 pinned holdings/evidence를 계산하며 개인 상태 loader나 market/FX fetcher를 제공하지 않는다. A는 저장소 검증된 state/snapshot과 freshness·eligibility를 확인한 typed inputs를 주입해야 한다.
- Scenario gate verifier와 위험 정책 reference의 실 registry 연동은 A 통합 시 연결·검증해야 한다. 이 구현 자체는 local input의 approval marker를 실제 registry 증거로 승격하지 않는다.
- 전용 및 reporting/Phase 5 회귀 완료, 전체 코드 독립 검토와 별도 최종 검증은 미실행이다.
