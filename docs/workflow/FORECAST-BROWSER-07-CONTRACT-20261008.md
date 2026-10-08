# FORECAST-BROWSER-07: 실제 사전학습 API 결함 보완

사용자 최신 지시 `수정해`에 따라 브라우저 ChatGPT가 구현하고 Codex가 설계, 수신 무결성 검사, 독립 검토 및 별도 최종 검증을 맡는다. 원격 push, 배포, 주문은 범위 밖이다.

- 작업 ID: FORECAST-BROWSER-07
- 요구사항: ACTUAL-01 Chronos provider 시간 형식, ACTUAL-02 실제 target_name 출력 결속, ACTUAL-03 Kronos Python 전역 상태 복원.
- 설계 버전: 이 문서 2026-10-08, 기존 F01–F07 계약 유지.
- 루트 기준: `70fdc63de0ea65382862c2129faf93bfc7833721`.
- 격리 구현 검토 기준: `bb3091e75ac2e6106b483afe894264b8a23ef630`, `workspace/cache/forecast-browser-gpt`.
- 담당 파일: `runtime/investment_stack/forecasting/adapters/chronos2.py`, `kronos.py`, 신규 `tests/forecasting/test_browser07_actual_api.py` 또는 같은 범위의 신규 회귀 검사.
- 의존성: 내려받아 검증한 실제 Chronos/Kronos/tokenizer weights, 고정 Kronos source. 이를 수정하거나 GPT에 업로드하지 않는다.
- 완료 조건: 현재 입력 대비 delta ZIP 및 input/output SHA 검증; 새 독립 검토에서 세 결함 정상/악성 입력 검사; 실제 local weights 12/60개월 adapter 추론 및 경로 복원 통과; 새 최종 검증 세션의 회귀/빌드 확인; 사용자 WIP 원시 바이트 보존 후 총괄만 통합 커밋.

시간대가 있는 요청은 기존 PIT 검증을 통과해야 한다. Chronos provider에 전달할 때 UTC로 변환한 후 timezone 정보를 제거하고, provider 출력은 UTC 시각과 정확 비교한다. 요청 자체의 naive 허용으로 해결하지 않는다. 실제 `target_name`은 내부 target과 전행 일치해야 하며 가격·quantile만 수치로 처리한다. 전체 예측 경로의 유한성, 양수, quantile 순서, ID 및 시각 검사를 유지한다.

Kronos는 기존 RLock 안에서 `sys.path` 전체를 저장하고 성공/예외 모두 원래 순서와 중복을 복원한다. bytecode 차단 및 flag 복원, ignored executable 및 foreign cached module 거부를 유지한다. 공식 소스의 `sys.path.append('../')`까지 회귀 검사에 포함한다.

실제 weights 추론 성공은 합성 입력에 대한 연결 검증이다. 실제 금융 정확도, 5년 예측 신뢰성, out-of-sample 수익률 검증을 대신하지 않는다. 이전 실패 증빙은 보존한다.

## FORECAST-BROWSER-08 추가 수락 조건

07 수신 파일 SHA와 실제 가중치 추론은 통과했지만 독립 검토의 pandas nullable 문자열 반례에서 `eq(...).all()`이 `pd.NA`를 건너뛰어 ID/target_name 누락을 수락했다. 두 열의 mixed/all missing 네 반례가 재현됐다. ACTUAL-02의 전행 identity 결속 조건 안에서 08을 배정한다.

- 기준: 미커밋 07 후보와 ZIP SHA `7d24a0d8abc1dd667c9d5548292260448fe8f3aaea9d71e05bcbaf765ead7e2f`.
- 담당: 브라우저 GPT, `chronos2.py`의 ID/target_name 검사 및 신규 `tests/forecasting/test_browser08_nullable_identity.py`만.
- 07 Chronos 입력 SHA: `533e4d1cadb4fd59c15b029bd207ad9bfb4d3087ba25fca5a9cf57ca6793094c`.
- 완료 조건: mixed/all-missing ID와 target_name 명시 거부, 정상 nullable ID/target_name 수락, 기존 07/readonly 검사 유지 및 실제 가중치 재시험 후 독립·별도 최종 검증.

07은 아직 수락/통합하지 않았다. 누락 검사에 `notna`와 NA를 false로 처리하는 일치 검사를 명시하며 요청의 naive/PIT 정책을 유지한다.
