# GEMINI31-A-R01-01 Handoff

## 수정 사항 (Changes)
1. **`runtime/investment_stack/deep_research.py` 내 `_current_price` 수정**
   - 현재가 검증 시 `FRESH` 상태의 관측 데이터만 통과시키도록 변경했습니다. (`STALE` 등의 다른 상태는 거부)
   - `instrument_id`와 `currency`가 정확히 일치하는지 검증을 추가했습니다.
   - 관측 시각(`timestamp`)이 존재하는지 확인합니다.
   - 거부 사유와 함께 튜플 `(Decimal | None, str | None)` 형태로 반환하도록 하여 호출자가 경고 메시지를 받아 처리할 수 있게 변경했습니다.
2. **`analyze_equity` 수정**
   - 반환된 `current_price`의 경고(warning)를 받아 `normalization_warnings`에 함께 포함하고 `record_task_state`에 기록하여 투명성을 높였습니다.
3. **`tests/unit/test_r01_price_binding.py` 신규 작성**
   - `Phase4ResearchRuntime` 등을 `MagicMock`으로 구성하여 외부 의존성 없이 독립적으로 실행 가능한 합성 픽스처 기반 표준 `unittest` 테스트를 추가했습니다.
   - FRESH, STALE 상태, Currency/Instrument 불일치, 관측시간 부재 등 다양한 엣지 케이스에 대해 올바르게 `None` 및 경고를 반환하는지 검증합니다.

## 미실행 검증 및 남은 갭 (Unexecuted Tests & Remaining Gaps)
- 쉘 실행이 금지되어 작성한 코드를 직접 실행하지 못했습니다. 코디네이터가 아래 커맨드를 통해 직접 테스트를 수행해야 합니다.
  ```bash
  python -m unittest tests.unit.test_r01_price_binding
  ```
- R02-R05, R09 및 후속 재무 데이터 정규화에 대해서는 이번 작업에 포함되지 않았으므로 다음 작업으로 넘깁니다.
- 기존 API와의 호환성 문제가 생길 수 있는 부분(예: `_current_price` 반환 타입이 변경되어 다른 곳에서 혹시 호출 중이라면 에러 발생 가능, 다만 현재는 `analyze_equity` 내부에서만 호출되는 것으로 파악됨)에 대해 전체 통합 테스트를 통한 확인이 필요합니다.

## 기준 커밋
- Base Commit: `d6ef79bc90bb08f0bd170b37653c65a927b029b3`
