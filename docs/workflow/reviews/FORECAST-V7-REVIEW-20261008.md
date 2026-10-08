# Forecasting bootstrap v7 독립 검토

검토일: 2026-10-08 KST. 요청: 사용자가 Downloads의 GPT 작업 산출물 확인 요청.
대상: `C:/Users/lsn/Downloads/lsn-forecasting-pretrained-bootstrap-patch-v7-20261006 (2)/v7_work`.
이 검토는 해당 외부 패키지에 한정된다. 프로젝트 전체 REVIEW-CODE-01 또는 VERIFY-01의 완료를 뜻하지 않는다.
관련 기준: R01/R03/R07/R09/R15/R16, 현재 ARCHITECTURE.md의 고정 기준시점·계산 계보·부분 실패 원칙.

## 결론

실험용 모듈로는 활용 가능하나 현재 상태 그대로 운영 프로젝트에 통합하거나 예측 결과를 투자 판단에 사용하는 것은 보류해야 한다. 아래 P1 네 건과 P2 두 건을 코드 검토와 반례 실행으로 확인했다. 수정주가 미사용은 정적 확인이며 나머지는 반례로 재현했다. 코드 수정·패치 적용·모델 다운로드·개인 DB 접근은 하지 않았다.

## 확인된 문제

1. **[P1] 5년 목표값의 미래 정보가 학습·검증 경계를 넘는다.** `scripts/train_tabular_forecaster.py:18–19`와 `scripts/walk_forward_tabular.py:34`는 입력의 `as_of`만으로 학습을 분리한다. `future_as_of` 또는 목표 수익률이 실제로 관측 가능한 시각은 검사하지 않는다. `2019-12-31` 학습 종료시점에도 `2024-12-31` 결과로 만든 5년 수익률 행이 학습에 들어간다는 반례를 직접 확인했다. 특성의 공시시점 검사만으로는 이 누출을 해결할 수 없다. 각 fold의 당시 시점 이전에 목표값까지 알려진 행만 학습에 포함하고, 잔차 보정·모델 선택에도 같은 경계를 적용해야 한다. 기존 OOS 점수는 수정 후 다시 산출해야 한다.

2. **[P1] 미완성 월봉을 미래 월말의 완료 봉으로 취급한다.** `scripts/run_pretrained_forecast.py:43–51`는 모든 일봉을 월말로 resample하며 `:89`에서 그 인덱스를 `as_of`로 사용한다. `2026-10-08` 한 행이 `2026-10-31` 월봉·예측 기준일로 바뀌었다. 요청 기준일을 별도로 고정하고 마지막 완료 월봉만 모델에 넣어야 한다. 더 넓게 `ForecastRequest.validate()`도 미래·역순·중복 timestamps를 검사하지 않아 `as_of=2026-01-01`에 2027년 이후 이력이 수용되는 반례를 확인했다.

3. **[P1] 실제 모델 로딩 시 체크포인트 검증이 강제되지 않는다.** `forecasting/adapters/chronos2.py:31–34`, `adapters/kronos.py:36–40`은 `from_pretrained()`를 바로 호출한다. 다운로드 스크립트의 해시 검사를 실행하지 않은 로컬 파일, 이후 변경된 파일, 기본 원격 모델 ID도 이 경로를 사용할 수 있다. 잘못된 바이트를 가진 임시 `model.safetensors` 디렉터리가 세 모델/토크나이저 loader 호출까지 도달함을 대체 loader로 확인했다. 실제 모델이 잘못된 바이트를 역직렬화했다는 주장은 아니다. 로드 직전 허용 revision·파일 해시·소스 provenance를 검사해야 문서의 검증 의무가 보장된다. Windows 절대 경로도 `available()`의 POSIX 접두사 검사에서 빠진다.

4. **[P1] NaN 예측이 COMPLETE 앙상블을 만든다.** `forecasting/contracts.py:49–60,93–101` 및 `ensemble.py:69`는 양수 비교 위주이며 유한성 검사가 없다. Kronos point=NaN, Chronos point=100, 정상 anchor 입력으로 `status=COMPLETE`, `point=NaN`이 반환됨을 직접 확인했다. 입력·모델 출력·quantile·가중치에 유한성 검사를 적용하고 부적격 component를 제외한 뒤 상태를 다시 계산해야 한다.

5. **[P2] 공급자 중복 가격에서 최신 조회값을 선택하지 않는다.** `scripts/run_pretrained_forecast.py:24–39`의 쿼리는 `retrieved_at`을 읽지 않고 `observed_at`만 정렬한 뒤 마지막 행을 선택한다. 합성 DB에서 더 최신 A(가격 10, 조회 1월 5일) 대신 오래된 B(가격 20, 조회 1월 3일)를 골랐다. 같은 날짜에서 명시적인 공급자 품질·통화·수정 여부·조회시각·충돌 처리 규칙을 적용해야 한다.

6. **[P2] 수정주가를 조회하고도 예측에 사용하지 않는다.** `scripts/run_pretrained_forecast.py:26,43–51,93`은 adjusted_close를 읽지만 월봉과 Chronos history에는 raw close만 넣는다. 이력에 분할이 있는 경우 경제적 수익률 변화와 분할의 가격 변화가 섞인다. 가격 조정 방식·기준일을 확인하고 OHLC 전체를 일관되게 조정하거나 분할 구간을 차단해야 한다. 이 항목은 사용 경로 정적 확인이며 실제 분할 종목 추론까지 실행한 것은 아니다.

## 통합 및 패키징 한계

- `orchestrator_hook.py`는 엔진을 만드는 함수뿐이다. 적용 스크립트도 모듈·docs·scripts를 복사하며 기존 고정 pipeline의 호출 지점을 변경하지 않는다. standalone runner 실행은 가능하지만 현재 프로젝트의 7개 요청 모드·검증 valuation·보고서까지 연결됐다는 증거는 없다.
- `requirements-forecasting.txt`에 직접 사용하는 numpy/pandas/scikit-learn/huggingface_hub가 명시되어 있지 않다. 일부 전이 의존성에 기대므로 깨끗한 Windows 환경의 설치 검증이 필요하다.
- 앙상블에는 출처·기준시점·통화·평가기간을 결속하는 기존 프로젝트 계약 연결이 필요하다. 특히 현재 적정가와 5년 후 가격의 기간 정합성을 명시해야 한다.
- 문서는 실제 pretrained 추론을 완료하지 못했다고 정직하게 적었다. 파일에 보관된 `53 passed` 로그는 실제 다운로드·추론 성공 증거가 아니다.

## 직접 실행 결과와 한계

- bundled Python 3.12의 numpy/pandas로 기존 테스트 함수 직접 호출: **19 PASS / 0 FAIL**. pytest 실행을 대신한 부분 검증이며 전체 53개의 성공으로 해석하지 않는다.
- 요청된 의존성을 읽는 테스트 모듈 5개와 bootstrap test 1개는 requests/pytest/xgboost/huggingface_hub 부재로 미실행. 6개는 테스트 개수가 아닌 미실행 항목 수다.
- pytest/huggingface_hub를 검토용 workspace에 설치하려 했으나 pypi.org DNS 실패로 불가. 전역 환경 변경 없음.
- 합성 데이터·대체 loader 반례 6개 실행: 미래 월말, 미래 이력 수용, NaN COMPLETE, 학습 목표값 미래 누출, loader 해시 검증 우회, 중복 공급자 선택 오류를 재현.
- 실제 checkpoint 다운로드·공식 모델 로딩·CPU/GPU 추론·실데이터 5년 OOS 성능·현재 저장소 전체 회귀는 미실행.
- 재현 스크립트와 출력: `workspace/forecast-v7-review/probes.py`, `probe-results.json`, `run_available_tests.py`, `available-tests.json`.

수정 우선순위: 목표값 시점 분리 → 완료 봉·고정 기준시점 → loader 검증 → 숫자 적격성 → 공급자/분할 처리 → 설치 및 실제 inference → 기존 runtime 통합 검증.
