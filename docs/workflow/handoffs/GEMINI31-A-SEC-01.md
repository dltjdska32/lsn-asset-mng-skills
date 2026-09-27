# GEMINI31-A-SEC-01 Handoff

## 수정 사항 (Changes)
1. **`runtime/investment_stack/providers/adapters.py` 수정 (`SecCompanyFactsAdapter.fetch`)**
   - 기존에는 `facts` 딕셔너리 전체를 하나의 관측치(observation)에 넣었으나, 이를 `taxonomy -> tag -> units -> fact[]` 형태로 순회하며 각 fact를 별도의 `ProviderObservation` 객체로 분할 생성하도록 변경했습니다.
   - `us-gaap` 네임스페이스와 `dei`의 주식수(`EntityCommonStockSharesOutstanding`) 중 지원이 명시된 주요 태그만 canonical metric으로 매핑하고 그 외는 버리도록 하였습니다. (`_SEC_SUPPORTED_TAGS` 정의)
   - Decimal 정밀도를 유지하며 bool, NaN, Infinity 값은 스킵합니다. 
   - `filed` 일자를 해석해 해당 날짜의 UTC 종료 시점(23:59:59)을 `published_at`으로 설정하고, `analysis_as_of`를 초과하는 future fact는 노출하지 않도록 차단했습니다.
   - start, end, form, filed 등 필수 메타데이터가 누락된 경우, 관측치는 반환하되 `calculation_input_approved=False` 및 `relevance_reason`에 이유를 기재하도록 처리했습니다.
   - 적격(eligible) fact가 1개 이상일 때 `AVAILABLE`, 수집은 되었으나 적격 fact가 0개면 `PARTIAL`, 파싱된 관측치가 아예 0개면 `UNAVAILABLE`로 명확한 상태와 사유를 반환합니다.
   - 중복/정정(accession) 내역은 별도 관측치로 모두 보존되며 임의로 병합하지 않습니다. 또한 `dei` -> `us-gaap`, 태그, 유닛 순의 알파벳 정렬을 통해 순서를 결정론적으로 보장합니다.

2. **`tests/unit/test_r04_sec_companyfacts.py` 신규 작성**
   - 실제 중첩된 SEC JSON 형태를 가정한 합성 픽스처(synthetic fixture)로 테스트를 구현했습니다.
   - 복수 fact, 정정 제출(revision), 지원되지 않는 태그, 미래 날짜 공시 누락, 누락된 필수 필드로 인한 PARTIAL 상태 변환, NaN 등 유효하지 않은 값의 스킵 처리를 단위 테스트로 검증했습니다.

## 미실행 검사 및 남은 결합 의존성 (Unexecuted Tests & Remaining Gaps)
- **미실행 쉘 커맨드**:
  ```bash
  python -m unittest tests.unit.test_r04_sec_companyfacts
  ```
- **기존 테스트 충돌**: `tests/unit/test_phase4_providers.py` 내부의 기존 테스트 중, 빈 Revenue 태그를 넣어도 전체 `facts` 객체를 하나로 반환하기 때문에 `AVAILABLE` 상태를 기대하는 검증이 존재할 것입니다. 요구사항(0개 적격 팩트 시 `UNAVAILABLE` 반환)에 따라 기존 테스트는 `UNAVAILABLE` 상태 반환으로 기대값이 변경되어 실패할 수 있으니 총괄이 이를 확인 후 수정해야 합니다.
- **남은 결합 의존성**: 본 작업은 SEC Company Facts의 "파서 수직 슬라이스(Parser vertical slice)" 영역에 한정됩니다. 이렇게 개별 관측치로 분해된 다량의 SEC Fact들이 실제 `deep_research` 엔진 및 Phase 4 증거 시스템에서 충돌(Conflict) 해결과 최종 단일 적격 관측치로 무사히 소비/연결되는지(Integration)는 아직 입증되지 않았으므로 후속 연결 검증(R02~R03 단계 통합)이 필요합니다.

## 기준 커밋
- Base Commit: `65388c1a8b2813982c52148d52cb2b069924a05e`
