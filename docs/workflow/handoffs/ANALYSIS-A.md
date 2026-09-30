# ANALYSIS-A 구현 인계

- 작업: ANALYSIS-A, R10/R17 가격·가치평가 숫자 결속 검토 및 분석 전용 보완
- 요구사항/설계: `REQ-2026-09-23-v1` / `DESIGN-2026-09-23-v0.1`
- 기준: `46306d23b29eed81eea349c777d186bc00cf4fab`
- 브랜치/작업 폴더: `codex/analysis-a` / `workspace/cache/analysis-a`
- 후속 기준: 총괄 커밋 `1d4fce3fc577fb95ce4dc796135209114a0b060d` 이후 추가 변경 (미커밋; AGENTS의 총괄 단독 commit 규칙에 따라 총괄 통합 대상)

## 변경

- `runtime/investment_stack/decisions/briefing.py`: `VALUATION_MODEL`의 `ANALYST_SCENARIO` 출력은 계산 상태가 `CALCULATED`여도 확정 적정가로 읽히지 않도록 조건부 산출값으로 표시한다.
- `runtime/investment_stack/execution/analysis_modes.py`: 매수/추가매수/축소 수치의 보고서 노출은 계속 차단한다. 값이 run에 존재해도 요청 컨텍스트의 ID 일치만으로 독립 검증되는 적격성·종목·고정 cutoff 근거가 되지 않는다는 이유를 브리핑에 추가했다. 유효 DCF/시나리오 출력이 있을 때만 가정 기반 조건부 가치라고 표시하고, 값이 없으면 적정가 범위 미산출을 명시한다. D12 매수 기준·안전마진 정책 부재와 기준시각·검증 한계는 별도로 기록한다.
- 후속 위조 방지: 보고서로 가기 전에 저장에 쓰는 `Phase5AssetAnalysisRuntime._jsonable` serializer와 동일한 JSON canonical 변환으로 `AnalysisResult` 전체를 만들고, 자동 추가된 calculation ID만 제거한 뒤 `metadata.calculation_id`가 가리키는 동일 run.db calculations row와 대조한다. 저장 row가 없거나 값이 다르면 section에서 분석 내용을 모두 숨기고 PARTIAL/UNAVAILABLE 및 사유를 남기며 mode result도 PARTIAL로 표시한다. 검증에 실패한 결과의 metric을 근거로 시나리오 존재/부재 문구를 만들지 않는다.
- LAST_VALID_CLOSE 후속 회귀: `deep_research`가 Phase5 저장 이후 findings에 추가하는 종가 note를 정식 결과 비교에서 무조건 허용하지 않는다. run.db의 같은 instrument에 대해 SELECTED market evidence, market observation, 단 하나의 freshness receipt가 확인되고 receipt가 LAST_VALID_CLOSE일 때만 허용한다. returned `SelectedEvidence` 안의 observation ID/instrument/value/unit/currency/observed time/claimed close time/session/provider/metadata와 freshness 상태·모든 receipt 필드가 저장 행과 일치해야 한다. receipt 공개·유효시각과 관측·종가 시각은 고정 run cutoff 이하여야 한다. exact matching receipt에서 독립 재생성한 note만 비교 뒤 추가한다. 정상 종가는 유지하고 forged selected/finding 내용은 차단한다.
- `tests/decisions/test_briefing.py`: `CALCULATED` analyst scenario가 조건부 가치로 표시되고 규모는 계속 WAIT임을 검증한다.
- `tests/integration/test_r14_equity_mode_bundles.py`: ID가 같은 다른 숫자 및 같은 값의 다른 종목 위조가 최종 브리핑에 나오지 않음을 검증하고, DCF 가정 미제공과 D12 정책 부재의 별도 표기·고정 cutoff를 검증한다. 같은 calculation ID/evidence IDs의 가짜 DCF `1234.50`은 분석 섹션에서 숨기고 PARTIAL로 표시하며, 동일 run.db 결과와 Decimal metadata 결과는 일치 검증됨을 확인한다.

## 저장 계약 blocker

`bind_persisted_numeric`은 run.db에 저장된 숫자·typed output·evidence ID·공개시각 equality를 확인하지만 eligibility 정책/평가 영수증, 용도 및 instrument identity를 검증한다고 보장하지 않는다. run.db의 evidence metadata에는 `eligibility_decisions`가 있지만, 현재 그 결정은 독립적으로 검증되는 불변 계약이 아니다. 요청이 제공한 `EligibilityDecision.eligible(...)`만으로는 저장 evidence의 동일 ID에 붙은 정책 평가를 입증할 수 없다. 또한 저장 calculation/selection에서 instrument identity를 계산값과 결속하는 독립 검증 경로가 이 요청 인터페이스에 없다. 따라서 숫자 출력 연결은 안전하게 완료할 수 없어 fail-closed로 남겼다.

후속 저장 계약에는 최소한 다음이 필요하다.

1. EligibilityDecision 자체를 계약 envelope로 저장하고 선택 slot이 eligibility ID와 그 envelope hash를 참조하도록 한다.
2. 결정에 purpose, instrument ID, input fingerprint, policy version, assessment time/cutoff, 평가 결과·reason codes를 포함하고, 정책/평가기 버전 또는 재현 가능한 receipt를 검증한다.
3. CalculationRecord 및 선택 snapshot에도 instrument ID를 저장해 evidence projection → eligibility receipt → slot → calculation output → 최종 binding 전 경로에서 일치 검증한다.
4. 고정 `analysis_as_of`는 run metadata에서만 읽고, public availability 및 eligibility assessment가 해당 cutoff 이전인지 검사한다.

## 검증

- 통과: `tests.decisions.test_briefing`, `tests.decisions.test_persisted_context`, `tests.integration.test_r14_equity_mode_bundles`, `tests.integration.test_r01_weekend_price_e2e` — serializer·LAST_VALID_CLOSE 재생성·검증 실패 안내·위조 selected 대조 보정 포함 전체 34 tests, OK. 위조 DCF/findings, 정상 동일 결과, Decimal metadata, 정상 LAST_VALID_CLOSE와 종목/값/통화/claimed-time/status/future-public-time 위조를 포함.
- 통과: 변경된 Python 파일 `compileall` 및 `git diff --check`.
- 통과: 변경된 Python 파일 `compileall` 및 `git diff --check`.
- 확인된 반례: 동일 evidence/calculation ID와 다른 요청 숫자, 동일 값과 다른 instrument, 고정 cutoff 뒤의 evidence, 계산된 analyst scenario의 조건부 표기, 정책 부재 시 WAIT.
- 미실행: 전체 회귀, wheel/sdist 빌드, 독립 코드 검토 및 최종 검증. 총괄 통합 이후 별도 수행 대상이다.
- 미완: run.db에서 신뢰 가능한 eligibility receipt와 계산 instrument를 복구·검증하는 계약이 추가되기 전까지 최종 브리핑의 가격·가치 숫자 노출은 차단 상태다. 진입/추가매수/축소 가격·수량은 정책 부재로 WAIT다.
