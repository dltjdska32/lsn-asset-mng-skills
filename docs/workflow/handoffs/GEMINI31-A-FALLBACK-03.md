# GEMINI31-A-FALLBACK-03 Handoff

## 수정 사항 (Changes)
FALLBACK-02에서 발견된 합성 테스트 오류 및 coverage 검증의 경계 사례를 보완했습니다.

1. **테스트 오류 수정 (`tests/unit/test_r05_fallback_eligibility.py`)**:
   - `test_fundamentals_skip_missing_observation_time` 테스트에서 관측시각 누락을 시뮬레이션할 때, `_obs` 헬퍼 함수가 `obs_at=None`을 인자 생략과 구별하지 못하고 기본값(디폴트 시각)으로 덮어쓰는 문제가 있었습니다. `MISSING` 객체(sentinel)를 활용해 "인자가 생략된 경우"와 "의도적으로 `None`을 넘긴 경우"를 명확히 구분하여 실제 `observation_time=None` 상태가 정상적으로 검증되도록 수정했습니다.

2. **CURRENT_PRICE 리트라이 안전장치 강화 (`providers/execution.py`)**:
   - 기존에는 가격 관측치 리스트 내에 적격 관측치가 단 1개라도 있으면 즉시 성공으로 간주하고 해당 `ProviderResult`를 선택했습니다.
   - 하지만 더 최신의 "부적격 관측치"가 혼재되어 있는 경우, Downstream 시스템(`Phase4ResearchRuntime`)이 이를 전부 재평가하며 부적격 최신 값을 선택할 위험이 존재합니다.
   - 이를 원천 차단(Fail-closed)하기 위해, `CURRENT_PRICE`의 경우 **단 한 개의 관측치라도 부적격 사유(시간 미달, 종목 불일치 등)가 있다면 전체 Result를 부적격으로 판정하고 다음 공급자(Fallback)로 넘기도록(ALL 조건)** 수정했습니다. 관련 합성 테스트(`test_current_price_mixed_reject`)도 신규 추가했습니다.

3. **FUNDAMENTALS `required_metrics` 보수적 그룹핑 보완**:
   - 메트릭 완성 조건을 판정할 때, 단순히 `(period_end, currency)`만을 기준으로 그룹핑하는 것은 부족했습니다. 같은 종료일이라 하더라도 `period_start`, `reporting_frequency`, `accounting_standard`, `consolidation`, `adjustment_basis`가 다르면 결코 하나로 결합할 수 없는 팩트들이기 때문입니다.
   - 그룹핑 키에 위 속성들을 모두 추가하여 훨씬 엄격하게 보수적 그룹핑을 적용했습니다.
   - 또한 `period_end` 자체가 아예 비어있는 메트릭(예: 일부 duration 메트릭이 오류로 누락된 경우)은 `required_metrics` coverage 판정 그룹에서 무조건 탈락하도록 예외 처리했습니다.

## 미실행 검사 및 갭 (Unexecuted Tests & Remaining Gaps)
- 총괄 코디네이터는 다시 한번 아래의 커맨드를 쉘에서 실행해 주시기 바랍니다.
  ```bash
  python -m unittest tests.unit.test_r05_fallback_eligibility
  ```
- **R05/가격 안전 완료 주장 금지**: `execution.py` 레벨에서 Mixed Result를 리트라이로 차단함으로써 1차 방어선을 구축했으나, `Phase4ResearchRuntime.persist_and_select(results)` 등 하위 실소비처에서 관측치를 어떻게 최종 선택하는지에 대한 "실제 연결 검증"이 별도로 완료되어야만 전체 R05 및 가격 안전성이 확보됩니다. 이번 슬라이스에서는 해당 영역을 다루지 않았습니다.

## 기준 커밋
- Base Commit: `962930d494f67a7e4844a312b1eb97d9f51903e8` (FALLBACK-01, 02 미커밋 반영 기준)
