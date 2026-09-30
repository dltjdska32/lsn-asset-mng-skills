# RC04-COMPARISON-BASIS-01 인계

- 요구사항: `REQ-2026-09-23-v1` R02 (기간·회계 기준 통일), R14/R16 comparison path.
- 기준: 총괄 지정 root `c6e63d9a664d7f9f356685fd15221752328c2827`.
- Branch/worktree: `codex/luna-price-rc03-rc04` / `C:/Users/lsn/.codex/worktrees/luna-price-rc03-rc04/lsn-asset-mng-skills`.
- 담당 파일: `runtime/investment_stack/execution/analysis_modes.py`, `tests/integration/test_r14_equity_mode_bundles.py`.

## 변경

- 기존 comparison은 동일 `period_end`만으로 재무 기간 적합성을 판정했다. 이제 각 자산의 selected financial facts에서 기간 시작, 보고 주기/form, reporting period/fp, 회계 기준/basis, 연결 기준, 조정 기준, restatement의 context를 모아 검사한다.
- context 내 필드 충돌/복수 값 또는 자산 간 context 차이가 있으면 호환 불가 처리하고 그 쌍의 비교 수치를 만들지 않는다. matrix와 pairwise 결과에 양쪽 context 및 호환 boolean을 남기며 report path는 existing partial treatment를 쓴다.

## 검증

- 같은 `period_end`에서 annual vs quarterly 및 US-GAAP vs IFRS인 합성 자산쌍의 integration 회귀를 추가했다. 두 경우 모두 `period_compatible=True`, `reporting_context_compatible=False`, `compatible=False`, 비교값 없음, matrix 불완전/결과 partial을 확인한다.
- 실행: `tests.integration.test_r14_equity_mode_bundles` 및 RC03/Yahoo focused group 통과 (15 tests combined PASS).
- 개인 DB와 주문 API 미사용.

## 남은 문제

- source metadata가 기간/form/accounting basis를 제공하지 않는 경우 두 자산 모두 해당 dimension이 없으면 빈 차원으로 equality가 성립한다. 비교에 필요한 최소 metadata를 mandatory로 만들지는 않았으며, 이 선택은 설계/총괄 재검토 대상이다.
