# FORECAST-BROWSER-01 실제 수신 패치 검토

판정: **수용 불가, 2차 수정 요청 전송 완료**. 구현은 브라우저 GPT, 설계·독립 검토는 Codex. 원본 프로젝트로 통합하지 않았다.

## 산출물 확인

- 실제 다운로드: `C:/Users/lsn/Downloads/FORECAST-BROWSER-01-PATCH.zip`
- 26,391 bytes. SHA256 `2180caad4d030e7d63525a44f16caf6db33124d12f2099bc03052b88a6f3e32f`.
- ZIP CRC, 중복/경로 검사, 8개 변경 파일의 input/output SHA 모두 통과.
- 격리 리뷰 위치: `workspace/cache/forecast-browser-gpt`, 입력 스냅샷 커밋 `baf846e7ac1a5184727294d1705cf11d514e50f5`.
- 잘못 전송된 base64는 적용하지 않았다. 실제 다운로드 ZIP만 적용했다.

## 직접 실행한 결과

Python 3.12 전용 리뷰 환경, Windows. `PYTHONPATH`에 격리 체크아웃과 runtime 설정, 플러그인 자동 로딩/bytecode 비활성화. 임시 DB는 OS Temp에만 생성.

1. 기존 forecasting 전체 + 독립 contract/data/integrity probes 56개 + 새 실제 CLI probe: **89 passed, 10 failed, 9 warnings, 5.01s**. 로그 `workspace/cache/browser-gpt-forecast/local-review-01.log`.
2. 새 Chronos 정상 호출 및 중간 경로 검증 probes: **3 failed, 0.57s**. 로그 `workspace/cache/browser-gpt-forecast/positive-review-01.log`.

첫 수집 시 PYTHONPATH/cwd가 잘못되어 import 2개 실패했다. cwd와 runtime/checkout 경로를 바로잡은 뒤 위 결과를 얻었다. 수집 실패를 구현 실패 수에 포함하지 않았다.

## 확인된 차단 문제

### P0 Chronos 정상 추론이 실행되지 않음

`runtime/investment_stack/forecasting/adapters/chronos2.py::Chronos2Adapter.forecast` 안에 `import numpy as np`가 추가되어, 앞쪽 `hist=np.asarray(...)`에서 `UnboundLocalError`가 난다. 정상 stub pipeline도 호출되지 않는다. 기존 잘못된 출력 거부 probe가 통과한 것은 정상 추론 작동의 증거가 아니다. 새 검사는 pipeline 호출을 먼저 확인한다.

### P0 실제 CLI 계약 불일치

`scripts/run_pretrained_forecast.py::main`은 `target_semantics='point'`를 넘긴다. 실제 synthetic 시장 DB로 실행하면 `ForecastRequest.validate`의 `invalid target_semantics`에서 traceback 및 exit 1로 종료한다. weights 없는 정상 입력은 UNAVAILABLE/PARTIAL로 종료해야 한다. 관련 anchor/MC/시간축 계약도 후속 점검 요청했다.

### P1 남은 정합성

- Snapshot revision은 40자리 길이만 검사하며 정확한 registry pin과 비교하지 않는다.
- Bootstrap local-files-only의 Kronos source 경로가 clone/fetch를 수행한다.
- Tabular 추론은 요청 feature units를 artifact units에 결합하지 않는다. stale history와 실제 elapsed horizon의 불일치도 해결 필요하다.
- Store canonical 판단은 일부 테이블 이름의 존재만 확인한다. ensemble의 active weight 집합과 component link/model ID 집합의 정확한 일치, duplicate 및 missing components 검증이 필요하다.
- 원격 GPT의 native XGBoost/LightGBM 및 bundle rollback 보고는 아직 로컬에서 재현하지 않았다. 지속 가능한 source tests로 제공 요청했다.

## 추가 로컬 검증

시간축 반례: 월봉 마지막 관측 `2019-12-31`, analysis_as_of `2023-01-01`, 60 ME steps, target `2024-12-31`인 요청이 validate를 통과한다. 분석일로부터 약 2년인데 nominal 5년으로 취급될 수 있다. 새 stale-history probe **1 failed, 0.60s**; 로그 `stale-review-01.log`. 02/03에서 해결하도록 이미 명시했으며 최종 수신 코드에 같은 반례를 재실행한다.

앵커만 사용하는 engine persistence에서 active weights는 `{'fundamental-anchor': 1.0}`인데 DB component/model JOIN 집합은 빈 집합이었다. 새 `independent_browser_positive_probes.py::test_engine_persists_every_active_component_including_fundamental_anchor`에서 **1 failed, 0.84s**로 재현했다.

전체 `pytest -q tests`: **765 passed, 14 failed, 1 skipped, 206 subtests passed, 141.45s**. 로그 `workspace/cache/browser-gpt-forecast/full-review-01.log`. Packaging 실패 2개는 dist 생성 선행조건 미충족이다. 별도 `python -m build --no-isolation`은 리뷰 환경 setuptools 미설치로 backend unavailable이었다. 코드 빌드 결함으로 단정하지 않는다. Root native E2E 실패 2개는 새 trainer 필수 인자 누락이고, storage schema 실패 1개는 개인/run DB 버전이 각각 4라 기존 숫자 차이 assertion과 충돌했다. 독립 migration 검증을 버전숫자 불일치와 혼동하지 않도록 후속 요청했다.

02 ZIP은 아직 다운로드/로컬 검증하지 않았다. 원격 보고가 96 passed/13 failed, build 미완료여서 승인하지 않고 03 수정 요청을 전송했다. 남은 fixture/API/native E2E/앵커 저장/보안 계약을 완료하고 별도 `FORECAST-BROWSER-03-PATCH.zip`을 제공하도록 요청했다.

추가 빌드 복구: 공식 Codex bundled runtime의 설치된 setuptools를 PYTHONPATH로 제공하여 리뷰 환경을 수정하지 않고 `python -m build --no-isolation`을 다시 실행했다. Wheel/sdist **빌드 성공**. Packaging만 재검증: **5 passed, 1 failed, 1 skipped, 0.50s**. 실제 sdist에 새 `tests/test_e2e_forecast.py`가 들어가 기존 exact allowlist와 불일치한다. 로그 `build-review-01-bundled.log`, `packaging-review-01.log`. 최초 전체 검증의 dist prerequisite 실패 2개와 구분한다.

## 후속 요청

동일 ChatGPT 대화 `https://chatgpt.com/c/6ac71fef-719c-83ee-9fbf-abcac113f33f`에 FORECAST-BROWSER-02 수정 지시를 전송했고 응답 중 상태를 확인했다. 최초 INPUT 대비 최종 수정 전체, SHA manifest, 실제 검증 인계서, durable tests를 포함한 별도 `FORECAST-BROWSER-02-PATCH.zip`을 요구했다. 기존/독립 tests 삭제·skip·약화 금지. 실금융 정확도, 5년 OOS, 자동 Top10, 기존 7mode 통합은 검증됐다고 주장하지 않는다.
