# ANALYSIS-FIRST 독립 검토 01

- 검토 대상: 통합 소스 `bb0c124069ea086e2d04f1d233258e923a7567da` (기준 `46306d23b29eed81eea349c777d186bc00cf4fab`).
- 검토자: 별도 Codex `/root/review_analysis_first_01`, 읽기 전용 검토. 구현자 A/B/C 및 총괄의 테스트 결과를 검증 대신 사용하지 않았다.
- 집중 unittest: 선택 자산 9, equity 통합 15, 기술 섹션 7, 브리핑 9, 합계 **40 PASS**. 별도 위조/정상 경로 probe로 아래 반례를 재현했다.

| 우선순위 | 확인된 반례 | 담당 수정 |
|---|---|---|
| P1 | 선택 자산 보고서는 동일 calculation ID·metric을 유지하고 `valuation.findings`에 `적정가 999999 JPY/share`를 삽입해도 그 위조 문장을 표시했다. 저장된 Phase5 `result_json` 전체와 대조해야 한다. | C `selected_asset_research.py`, 회귀 테스트 |
| P2 | 기존 `deep_research.py`가 `LAST_VALID_CLOSE`의 합법적 가격 출처 설명을 Phase5 저장 후 findings에 추가한다. 신규 전체 동등성 검사가 이를 위조로 판단해 정상 valuation을 `AVAILABLE`에서 `PARTIAL`로 낮추고 숫자를 숨긴다. 저장 결과 무결성을 유지하면서 출처 설명을 별도로 렌더해야 한다. | A `analysis_modes.py`/담당 경로, 회귀 테스트 |
| P2 | 성공한 기술 섹션의 lines/metadata/calculation_ids 어디에도 `formula_version`과 지표 기간이 없어 상세 계산 규약을 추적할 수 없다. | B `technical_section.py`, 회귀 테스트 |
| P2 | 선택 자산 본문에 `dcf_scenario_base=1234.50` 같은 내부 metric 코드가 나타난다. | C `selected_asset_research.py`, 회귀 테스트 |

원본 공급자의 진위, caller가 제출한 조정·달력 receipt의 독립 확인은 이 검토에서 증명되지 않았다. 이 기록은 `bb0c124`에 대한 **문제 발견** 결과이며 수정 후 source의 통과 판정이 아니다. B 보정 source `c591b25`는 root `056e708`에 통합했다. A/C 후속 source와 최종 검증 버전은 별도 기록한다.

## 수정 후 독립 재검토 — `e4c3988b8699d21baf0d730223dab9c48374ee49`

A `1d4fce3`→root `964d43b`, C `6c382b1`→root `e4c3988`을 통합한 source를 같은 검토자가 다시 읽기 전용으로 확인했다. 관련 unittest **26 PASS**. 저장 계산과 다른 선택 자산 findings/DCF 값은 숨겨지고, 정상 마지막 유효 종가 설명과 DCF 한국어 표시명은 통과했다. 총괄도 같은 source에서 새 wheel/sdist 빌드와 전체 **646 OK(skip1)**를 확인했다.

그러나 P2 두 건이 남았다. (1) B의 `calculation_detail` metadata는 실제 `report.markdown`에 렌더되지 않아 R08 공식 버전·기간이 사용자 상세 근거에서 사라진다. B에 보고서 렌더 결과 회귀 테스트와 수정을 회송했다. (2) A의 마지막 유효 종가 예외는 저장 행을 확인하지만 반환 outcome의 `selected.observation.instrument_id`와 `selected.freshness.status` 불일치를 차단하지 못했다. 동일 evidence ID에 다른 종목/FRESH를 조합한 위조 runtime 반례에서 note가 반환됐다. A에 selected object와 저장 observation/receipt의 일치 검증을 회송했다. 이 SHA 역시 최종 통과 버전이 아니다.

B source `2dca452`→root `11aa626`와 A source `7597793`→root `3214f6a`에 두 P2 보정을 반영했다. 별도 최종 검증에서 발견한 선택 자산 미래 종가 P2는 C source `60f4e2976f6ca765a60871cd47b585c475b1572e`→root `9e781ecf92288b1d95731837dec50e12bc81755d`로 수정했고 동일 검증자가 새 SHA에서 재검증했다. 자세한 첫 미통과·최종 통과 증거는 `ANALYSIS-FIRST-VERIFY-01.md`에 있다. 이 독립 코드 검토 기록 자체가 후속 SHA 전체의 별도 재검토를 주장하지 않는다.
