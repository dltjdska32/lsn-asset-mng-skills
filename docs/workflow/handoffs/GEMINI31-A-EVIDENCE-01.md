# GEMINI31-A-EVIDENCE-01 Handoff

## 수정 사항 (Changes)
`Phase4` Evidence 저장 및 선택 경계(`runtime/investment_stack/evidence/research.py`)의 안전성을 강화하고 정밀도 손실 문제를 해결했습니다:

1. **선택된 가격 관측치의 유효성 및 안전 검사 추가 (`persist_and_select`)**:
   - `ProviderObservation`의 값이 `bool` 타입이거나, `NaN`, `Infinity` 등 계산할 수 없는 비정상(non-finite) 수치인 경우 계산 후보(candidates)에서 차단하도록 필터링을 추가했습니다.
   - 특히 `metric == "current_price"`인 관측치는 유한한 양수(`> 0`)여야만 후보로 승인됩니다 (음수, 0 차단).
   - **중요**: 이러한 부적격 값들은 후보 선택(`SelectedEvidence`)에서는 제외되지만, 로컬 데이터베이스(`run.db`)에는 원본 그대로 저장되어 호출 이력과 진단 정보가 유실되지 않도록 보존됩니다.

2. **SEC Decimal 정밀도 유실 방지**:
   - 기존에는 `isinstance(value, (str, int, float))`만 체크하여 `Decimal` 객체가 유입되면 `NULL`로 폐기되었습니다.
   - 이제 `isinstance(value, Decimal)`인 경우 강제로 `float` 캐스팅하여 SQLite의 `REAL` 정밀도 유실을 유발하지 않도록 `str(value)`를 통해 exact string 형태로 DB에 저장하게 만들었습니다. (SQLite의 동적 타이핑을 활용하여 스키마 구조 변경 없이 문자열 그대로 기록)

3. **신규 합성 테스트 2건 추가**:
   - `tests/unit/test_r05_price_evidence.py`: 부적격 최신 가격들(0, 음수, NaN, bool)이 있을 때 이들은 DB에만 저장되고, 대신 과거의 적격(Stale) 가격이 `partial=True` 상태로 정상 선택됨을 검증합니다.
   - `tests/unit/test_r04_decimal_evidence.py`: 고정밀 `Decimal` 값이 float 손실 없이 DB에 정확한 텍스트로 보존되는지 합성 DB를 통해 검증합니다.

## 미실행 검사 및 갭 (Unexecuted Tests & Remaining Gaps)
- 터미널 직접 실행이 불가능하므로, 총괄 코디네이터가 아래 명령어로 신규 및 기존 테스트를 검증해 주시기 바랍니다.
  ```bash
  python -m unittest tests.unit.test_r05_price_evidence
  python -m unittest tests.unit.test_r04_decimal_evidence
  ```
- **DB 스키마 유지**: 기존 DB 계약과의 충돌을 피하기 위해 테이블 스키마는 일절 건드리지 않았습니다.
- **Instrument / Currency 불일치 방어 위치**: `persist_and_select` 함수는 인자로 `ProviderRequest`를 받지 않아 요청 종목과 통화를 알 수 없으므로, 여기서 알 수 없는 currency/instrument의 차단은 불가능합니다. 이는 반드시 Phase 4 상위 Request 경계(후속 작업)에서 체크되어야 합니다.
- **R05/가격 안전 수직 슬라이스 한계**: 이 과제만으로는 전체 request-level 유효성 검증과 R05 Web Fallback Retry 통합이 완료된 것이 아닙니다. 완료를 주장하지 않습니다.

## 기준 커밋
- Base Commit: `9f5f2b5524c468888ee5c3535488461b50cf8b6e` (Structured Fallback Checkpoint 기준)
