# FORECAST-BROWSER-07/08 통합 인계

완료: 사용자 `수정해` 요청의 실제 사전학습 어댑터 결함을 브라우저 GPT가 구현하고 Codex가 설계·독립 검토·별도 최종 검증·로컬 통합했다.

## 변경과 기준

- 입력 루트: `70fdc63de0ea65382862c2129faf93bfc7833721`.
- 수락 고정 소스: `8c993d4c0c5c7af090e52c8f462634f6f90e65c0`, tree `3db5a62bdda0a2b108d850b36937d0217350fe22`.
- 루트 소스 통합: `bc0fd92df010ea1a01fa5960f01d5786f15278b0`.
- `runtime/investment_stack/forecasting/adapters/chronos2.py`: 검증된 aware 시각을 provider 경계에서 UTC-naive로 변환, 실제 target_name 출력과 ID 전행 결속, nullable 누락 차단, 명시 가격·quantile 및 전체 경로 검증 유지.
- `runtime/investment_stack/forecasting/adapters/kronos.py`: RLock 안에서 전체 sys.path 내용·순서·중복·목록 객체 및 bytecode flag를 성공/예외에 복원. 공식 source/weights를 수정하지 않았다.
- 신규 source tests: `tests/forecasting/test_browser07_actual_api.py`, `test_browser08_nullable_identity.py`.

07/08 ZIP CRC, 경로 제한, 중복 이름, 정확 delta input/output SHA 검사 통과 후 격리 후보에만 적용했다. 기존 테스트 및 readonly probes는 유지했다. 07 독립 검토에서 추가 nullable 결함을 발견하여 08로 보완한 뒤 수락했다.

## 실행한 검증

- 새 독립 검토: 수정 전 24개 13 FAIL/11 PASS; 07 관련 102 PASS 후 nullable 4 FAIL/24 PASS; 08 독립 28개와 관련 회귀 **115 PASS**.
- 새 별도 최종 세션: 595 Git blobs와 10 probes/helper 불변; fresh wheel/sdist PASS; 전체 **989 PASS/2 SKIP/206 subtests PASS**, 195.56초.
- 실제 local weights CPU/offline: Chronos/Kronos 12/60개월 COMPLETE, Chronos Seoul 12/60 COMPLETE, Kronos 반복/cold/default bytecode false 및 상태 복원 PASS. 실행 후 3 snapshot과 고정 source 무결성 PASS. 07,08 총괄 실행과 새 최종 세션 직접 실행 모두 exit 0.
- 루트 통합 후: 새 07/08, 기존 06 반복 로딩 및 native E2E **39 PASS**, 24.57초. 로그 `workspace/cache/browser-gpt-forecast/root-integration08-tests.log`.
- 루트 네 파일은 수락 Git blob과 정확 대조했고 기존 사용자 WIP7의 raw SHA256은 통합 전후 보존했다. 다른 WIP는 커밋하지 않았다.

최종 검증 상세: `reviews/FORECAST-BROWSER-08-FINAL-VERIFY-20261008.md`; 독립 상세: `reviews/FORECAST-BROWSER-08-INDEPENDENT-REVIEW-20261008.md`.

## 미실행/남은 문제

실제 금융 자료의 정확도·walk-forward·5년 OOS·GPU·자동 7개 모드/시간별 브리핑/Top10 통합은 이 수정 요청에서 검증하지 않았다. 입력은 합성 월봉 120개다. CPU 모델 연결이 성공한 것을 투자 성능으로 해석하지 않는다. 기존 skip 2건은 Windows symlink privilege 및 공유 venv에 wheel을 설치하지 않은 installed-skill 검사이며 빌드 산출물 allowlist는 검사했다.

원격 push, 배포, 주문, 개인 DB 접근, credential 업로드, weights Git commit은 하지 않았다. 가중치는 로컬 cache에 유지한다.
