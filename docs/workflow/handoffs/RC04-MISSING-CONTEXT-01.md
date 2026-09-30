# RC04-MISSING-CONTEXT-01 인계

- 요구사항: `REQ-2026-09-23-v1` R02/R14; 설계: `DESIGN-2026-09-23-v0.1` 초안.
- 독립 리뷰: 총괄 전달 same-missing-context 반례 (2026-09-27 후속 task).
- 기준: 직전 RC04 구현 commit `a7f319d08c8e706baf9ba5fdd8b01d0288f3c785`.
- Branch/worktree: `codex/luna-price-rc03-rc04` / `C:/Users/lsn/.codex/worktrees/luna-price-rc03-rc04/lsn-asset-mng-skills`.
- 소유 파일: `runtime/investment_stack/execution/analysis_modes.py`, `tests/integration/test_r14_equity_mode_bundles.py`.

## 변경

- 이전 비교는 좌/우 context가 같기만 하면 통과했기 때문에 두 자산의 기간 시작·보고 주기·보고 구분·회계 기준·연결 기준·조정 기준·정정 정보가 모두 누락된 경우도 compatible로 승인했다.
- 각 필수 차원이 양쪽에서 정확히 하나로 해석되고, 내부 충돌이 없으며, 좌우가 일치할 때만 reporting context를 적합 처리한다. period end는 기존 단일 기간 확인에 추가해 context에서도 검증한다.
- 비교 가능 positive fixtures에 명시적 보고 metadata를 넣었다. annual/quarterly, US-GAAP/IFRS, 그리고 동일하게 전부 누락된 context 각각에서 period-end 일치만으로는 비교하지 않음을 검증한다.

## 검증

- `tests.integration.test_r14_equity_mode_bundles`: **6/6 PASS**.
- 전체 `unittest discover -s tests -q`: 보정 포함 **566 tests, OK, skipped=1**.
- 개인 DB 및 주문 API 사용 없음.

## 남은 점

- 필수 source metadata가 없는 실제 disclosure는 comparison PARTIAL/비교 중단으로 처리된다. 허용 가능한 metadata 대체 규칙은 별도 설계 승인이 없다.
