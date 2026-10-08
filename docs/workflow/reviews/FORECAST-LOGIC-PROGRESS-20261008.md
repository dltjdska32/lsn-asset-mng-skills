# 예측 로직 보완 중간 검토

2026-10-08 / Codex 설계·독립 검토, Antigravity Gemini 3.1 Pro High 구현. 완료 보고서가 아니다. 대상은 격리된 세 forecasting worktree이며 기존 루트의 개인원장/최근 이벤트 미커밋 변경은 보존했다.

## 우선 해결할 오류

1. **미래 학습 데이터가 과거 분석에 들어가는 누수(P1)**: DATA-02 `a124234`, `TabularMLAdapter.forecast()`는 train/cal/eval 순서만 검사하고 request.as_of와 비교하지 않는다. 완비된 2030/2031/2032 cutoff artifact가 2020 요청에 PARTIAL/point를 반환함을 독립 반례로 재현했다. 이전 미래 cutoff 검사가 통과한 이유는 필수 evaluation_cutoff 자체가 빠져 있었기 때문이다. DATA-03에 회송했다.
2. **예측 대상 혼동(P1)**: 같은 함수가 target=`revenue_growth`를 미래 주가 CAGR처럼 복리 적용한다. 가격수익률/총수익률/사업성장률을 구분하는 artifact schema가 필요하다. 독립 반례 실패, DATA-03 회송.
3. **covariates 공개시각 미검사(P1)**: CORE-03 `9de3041`, `ForecastRequest.validate()`는 metadata 키 존재만 검사한다. 각 실제 값·timestamp·publication·길이와 as_of를 검증해야 한다. 미래 변수는 이름이 아닌 시간 및 가정 출처로 판별해야 한다. CORE-04 회송.
4. **저장 통합·무결성(P1)**: 기존 run DB 검증은 공식 마이그레이션으로 정해진 정확한 스키마를 요구한다. 임의 forecasting DDL을 추가하면 기존 검증과 충돌한다. 공식 SQL-only run migration, 실제 run/instrument 결속, 엄격한 JSON, 구성 모델 링크와 transaction 원자성을 설계 revision02로 요구했다. INTEGRITY-02 진행 중.
5. **5년 CAGR 기간 기준 불일치(P2)**: CORE-03 `ForecastingEngine.run()`은 steps/12로 MC CAGR을 계산하면서 metadata에는 actual365.25라고 기록한다. 실제 target_date와 분석 기준시각 사이 기간으로 일관되게 계산해야 한다. CORE-04 회송.
6. **ROIC가 WACC보다 낮은 성장 기업 배제(P2)**: `calculate_terminal_scenario()`가 성장>0/ROIC<WACC면 예외를 낸다. 가치 파괴 위험을 경고해야 하지만 사업 성장 자체가 불가능한 것은 아니다. 재투자율을 모델링하지 않은 상태에서 이 조건을 산식 금지 규칙으로 사용할 수 없다. CORE-04 회송.
7. **오류 모델 격리 누락(P2)**: malformed adapter 결과가 ensemble에서 빠져도 저장 단계에서 전체 실행을 중단할 수 있다. 중앙 출력 검증과 request-bound ERROR 정규화가 필요하다. 모델 간 차이도 제외된 잘못된 모델을 포함해 계산하면 안 된다. CORE-04 회송.

## 직접 실행한 근거

- 수정 전 외부 원본: 53 PASS. 실제 사전학습 금융 추론이나 5년 OOS 성능 검증을 의미하지 않는다.
- CORE-03 `9de3041`: 기존/구현/독립 계약 반례 합계 65 PASS, 1 warning, 1.87s. 위 정적 감사 오류가 있어 수락하지 않았다.
- DATA-02 `a124234`: forecasting+초기 독립 반례 37 PASS, 8 warnings, 3.74s. 더 강한 독립 반례 7개는 5 PASS/2 FAIL, 2.36s. 실패 원인은 위 P1 두 건이다.
- INTEGRITY-01 `509e561`: manifest/path/instrument 독립 반례 3 FAIL. 수정02 이후 결과는 아직 검토 전이다.
- INTEGRITY-02 `6a1ecc2`: native run DB E2E 등 기존/구현/독립 10개 검사 8 PASS/2 FAIL, 1.09s. 새 반례에서 Chronos/Kronos 모두 2020년 5단계 요청에 2030년 단일 행을 COMPLETE로 반환했다. CORE와 별개로 actual predictor 출력 경로를 검사해야 하므로 INTEGRITY-03에 회송했다. 저장 인자와 forecast 종목 불일치, 일반 boolean metadata, prototype DB도 추가 독립 검사 대상으로 등록했다. 최종 통합 전이다.

검증 로그와 readonly Codex 반례는 각 worktree의 ignored `workspace/cache/`에 보존했다. Gemini가 보고한 성공 문구와 테스트 수는 위 직접 실행 결과와 구별한다.

추가 독립 Integrity8개는3PASS/5FAIL(1.17s): predictor 경로2건, 저장 인자에 의한 forecast 종목 바뀜, 정상booleanmetadata 거부, prototypeDB 사전 역할/스키마 검증 누락. Gemini API 계정 한도로 후속 구현 호출이 중단됐고, core/data 마지막 부분 수정도 미커밋·미수락으로 보존한다. 정확한 재개 상태는 `../handoffs/FORECAST-LOGIC-QUOTA-20261008.md`를 따른다.

## 수락 조건과 남는 경계

세 담당 수정 commit을 통합한 동일 SHA에서 native XGBoost/LightGBM 합성 PIT 학습→artifact→실제 예측, 공식 run DB 저장 후 기존 validator 통과, loader 전에 잘못된 weights/source 차단, 전체 회귀, fresh wheel/sdist 검사를 수행한다. 이어 별도 새 Codex 세션이 최종 검증한다. 이 단계 전에는 완료 또는 실전 사용 준비로 표시하지 않는다.

실제 Chronos/Kronos checkpoint 금융 추론, 실데이터 5년 walk-forward/OOS, 시장별 기업행동·상장폐지·생존편향 검증과 투자 우선순위 유효성은 별도 실증 과제다. 이번 수정이 통과해도 이를 완료했다고 간주하지 않는다. MC 손실확률은 지정 가정에 조건부이며 자동 종목 순위를 승인하지 않는다. 기존 7개 모드 및 매시간 포트폴리오 자동 실행은 이번 통합 완료와 별개다.
