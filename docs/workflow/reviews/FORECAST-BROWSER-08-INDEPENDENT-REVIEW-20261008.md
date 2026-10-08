# FORECAST-BROWSER-07/08 독립 수락 검토

판정: **08 수락. 별도 최종 검증으로 진행.** 구현은 브라우저 ChatGPT, 독립 검토는 새 Codex 세션 `/root/forecast_browser07_independent_review`가 맡았다. 런타임을 검토자가 수정하지 않았다.

## 확인한 소스와 증빙

- 루트 입력 기준 `70fdc63de0ea65382862c2129faf93bfc7833721`, 격리 06 기준 `bb3091e75ac2e6106b483afe894264b8a23ef630`.
- 07 delta ZIP: 13075 bytes, SHA256 `7d24a0d8abc1dd667c9d5548292260448fe8f3aaea9d71e05bcbaf765ead7e2f`, 입력/출력 SHA 3파일 일치.
- 08 delta ZIP: 6931 bytes, SHA256 `3a9ff0c8c70983bc1a96e53e9db05364d2ab79a8f05492acb7d976b33f9f0c68`, 07 대비 입력/출력 SHA 2파일 일치.
- 최종 누적 변경: `adapters/chronos2.py`, `adapters/kronos.py`, 신규 `test_browser07_actual_api.py`, `test_browser08_nullable_identity.py` 네 파일.
- 독립 수락 후 총괄이 고정한 커밋: `8c993d4c0c5c7af090e52c8f462634f6f90e65c0`.

## 새 독립 세션이 직접 실행한 검증

`workspace/cache/browser-gpt-forecast/review07/test_independent_actual07.py`에 별도 반례를 작성했다. 기존 소스 테스트 및 원래 9개 readonly probe를 수정하지 않았다. 기존 Python review venv를 사용하고 PYTHONPATH를 격리 후보 runtime/tests로 고정했다.

| 단계 | 직접 실행 결과 |
|---|---|
| 수정 전 24 독립 검사 | 13 실패 / 11 통과, 6.82초 |
| 07 + 24 독립 검사 및 관련 회귀 | 102 통과, 26.99초 |
| 07 nullable identity 추가 반례 | 4 실패 / 24 통과, 7.81초 |
| 08 + 동일 28 독립 검사 및 04/05/06/07/08 회귀 | 115 통과, 24.90초; 기존 CLI regex 경고 2개 |

07에서 추가로 발견한 결함은 pandas StringDtype의 `pd.NA`를 `eq(...).all()`이 건너뛰는 문제다. 누락된 ID와 target_name을 한 행 또는 전행에 넣은 네 반례가 COMPLETE로 통과했다. 브라우저 GPT가 08에서 `notna().all()`과 `eq(...).fillna(False).all()`로 전행 유효성을 보장했고 동일 반례가 거부됐다.

UTC/Tokyo/New York 요청의 12/60개월 경로, DST 달력, provider의 UTC-naive 입력, 반환 timezone의 동일 instant를 검사했다. wrong/mixed/null target identity, ID 불일치, 잘못된 시각, 중간 NaN/Inf/0/음수/crossing quantile 및 naive 요청을 차단했다. Kronos upstream 경로 append/insert, 성공·import/constructor 예외에서 순서·중복·목록 객체·bytecode flag 복원을 확인했다. 기존 ignored executable/foreign cached module 검사도 유지했다.

독립 회귀 실행 cwd는 루트였다. PYTHONPATH의 후보 소스는 고정됐지만 기존 04 CLI subprocess는 루트 scripts를 사용한 한계가 있다. 별도 최종 검증은 새 고정 소스 복사본 cwd와 `FORECAST_REVIEW_ROOT`를 설정하여 이 범위를 다시 확인한다.

## 총괄의 실제 모델 확인 — 독립 세션 결과와 구분

07과 08 각각 별도 CPU inference venv에서 실제 local safetensors와 공식 고정 Kronos source를 사용했다. 모델 mock 및 네트워크 다운로드 없이 합성 월봉 120개를 넣었다. Chronos/Kronos 12/60개월 COMPLETE, Chronos Asia/Seoul 12/60개월 COMPLETE, Kronos repeated/cold load 및 sys.path/flag 복원 PASS. 실행 후 세 snapshot inventory와 Kronos source pin/ignored executable 검사가 통과했다. 각 실행 exit 0.

로그: `workspace/cache/browser-gpt-forecast/actual-pretrained-smoke07-20261008.log`, `actual-pretrained-smoke08-20261008.log`. JSON은 후보 `workspace/cache/browser-gpt-forecast/` 아래 같은 이름이다. 최종 검증 세션도 이를 직접 재실행해야 한다.

**금융 정확도/OOS/실제 종목 성과는 미검증이다.** 실제 weights의 합성 입력 연결 성공을 5년 예측 성능으로 해석하지 않는다. 새 최종 검증 완료 전 루트 런타임 통합은 보류한다.
