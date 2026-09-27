# GEMINI31-A-SEC-02 Handoff

## 수정 사항 (Changes)
이전 SEC-01 파서에서 누락되었던 코드 안전성과 테스트 실패 문제들을 해결했습니다:
1. **엄격한 단위 및 차원 검증 도입**: `_SEC_SUPPORTED_TAGS`와 `_DEI_SUPPORTED_TAGS`를 `SecTagDef` 데이터 클래스로 정의하여 각 태그가 요구하는 `kind`("money", "per_share", "shares")와 `is_duration` 여부를 엄격히 설정했습니다. 이로 인해 revenue/shares, EPS/USD 등의 잘못된 차원 데이터가 원천 차단됩니다.
2. **malformed value 안정성 확보**: `val`이 dict나 list 등 hashable하지 않은 타입일 때 발생하던 `TypeError`를 방지하도록 먼저 타입 체크를 수행하고 안전하게 스킵 처리했습니다.
3. **timezone-aware `analysis_as_of` 변환**: `analysis_as_of`에 UTC offset 정보가 없는 경우 `tzinfo=timezone.utc`를 부여하여, timezone-aware인 `filed_dt`와 비교 시 발생하는 `TypeError`를 해결했습니다.
4. **결정적 순서 보장 정렬 키 추가**: 반환되는 관측치(`observations`) 리스트를 `namespace/tag/unit/period_end/start/accn/filed/val` 순서의 키로 명시적으로 정렬하여 딕셔너리 순서와 무관한(permutation invariance) 결정적인 관측 순서를 보장했습니다.
5. **Duration/Instant Metric 날짜 규칙 적용**: `is_duration`이 True인 태그(예: Revenue)는 반드시 유효한 `start` 날짜가 존재해야 하며 `start <= end` 조건을 만족해야 합니다. 이를 어기면 `calculation_input_approved=False` 처리되며 reason에 사유를 명시합니다. Instant 태그(예: Shares)는 `start`가 없어도 승인됩니다.

## 신규 반례 합성 테스트 추가 (Synthetic Tests)
- `tests/unit/test_r04_sec_companyfacts.py` 픽스처에 기간(start) 필드를 정상 부여하여 승인 거절을 방지했습니다.
- 순서 불변성 확인을 위한 `test_permutation_invariance` 케이스를 추가했습니다.
- Duration 메트릭의 start 누락, start가 end보다 큰 경우, dict 타입 값 파싱 등의 반례를 검증하는 테스트 케이스를 보강했습니다.

## 미실행 검증 및 남은 실제 소비 결합 (Unexecuted Tests & Remaining Gaps)
- 쉘 실행 불가로 인해 총괄 코디네이터의 직접 검증이 요구됩니다.
  ```bash
  python -m unittest tests.unit.test_r04_sec_companyfacts
  ```
- **남은 갭**: SEC Company Facts의 파싱 수직 슬라이스는 완료되었으나, 다수 생성된 SEC 관측치들이 `Phase4ResearchRuntime` 및 `Phase5AssetAnalysisRuntime`의 `deep_research` 실소비 경로로 넘어가 단일 값으로 적절히 Resolution 되고, 재무제표 표시에 정상 노출되는지에 대한 "실제 소비 연결" 검증은 아직 미완 상태입니다 (R02 후속 작업으로 연결 필요).

## 기준 커밋
- Base Commit: `65388c1a8b2813982c52148d52cb2b069924a05e` (A-01 미커밋 반영 기준)
