# RC04-METRIC-LEVEL-CONTEXT-01 인계

- 요구사항: `REQ-2026-09-23-v1` R02/R14.
- 독립 검토 기준: root `979cc5efb5d8bbb54e198ed9cb02ec891444c7de`; same-missing review thread `01a0e30c-b115-7db0-9a6c-b05a962b2d8c`.
- Branch/worktree: `codex/rc04-metric-level-context` / 별도 `luna-rc04-metric-context` worktree.
- 담당 파일: `runtime/investment_stack/execution/analysis_modes.py`, `tests/integration/test_r14_equity_mode_bundles.py`, 본 handoff.

## 변경

- 이전 pair context가 asset의 모든 financial observations에서 차원별 set union을 만들어, 다른 지표 metadata가 해당 지표의 누락한 `start`/`restatement`를 보충해 주는 반례가 있었다.
- 실제 선택된 각 observation에서 `_observation_metrics`로 canonical metric을 구하고 그 값의 source context를 직접 수집한다. 지표의 context가 없거나 복수/conflicting이면 그 지표 비교값과 delta를 제외한다.
- 주요 derived valuation comparison도 입력 financial metric dependencies의 context가 양 자산과 필요한 입력들 사이에 모두 일치해야 한다. 지원하지 않는 derived formula는 비교 허용하지 않는다.
- `metric_context_checks`를 calculation input matrix와 result에 저장한다. 어떤 common metric의 context 비교가 빠져 있으면 matrix는 incomplete이고 report는 partial이지만, 같은 context가 확인된 다른 지표 비교는 유지한다.

## 검증

- `KEYENCE`의 EPS 하나에서 `start`와 `restatement`만 지운 합성 회귀를 추가했다. 다른 지표들의 aggregate metadata가 asset-level context를 완성해도 EPS comparison/delta는 생성되지 않고 `revenue` 비교는 유지됨을 검증한다.
- `tests.integration.test_r14_equity_mode_bundles`: **7/7 PASS**.
- 전체 suite는 실행하지 않았다. 개인 DB/실거래는 사용하지 않았다.

## 남은 점

- Derived valuation dependency whitelist는 P/E, P/B, EV/EBITDA, price/sales, dividend yield만 지정했다. 여타 valuation metric은 metric-level context source map이 추가되기 전까지 비교에서 제외된다.
