# 04 실제 수신 패치 및 독립 수락 검토

판정: 미수락. 브라우저 GPT에 05 누적 수정 요청을 전달했고 응답 중 상태를 확인했다. 구현 담당 GPT, Codex는 설계/검토/합성 probes/검증 담당.

## 수신 및 직접 검증

- 자동 다운로드 `C:/Users/lsn/Downloads/FORECAST-BROWSER-04-PATCH.zip`: 71,844bytes, SHA256 `86bb96877503773356fe15267f6ea02b6ad857d1d388f8da2422f070f2b99475`.
- CRC/중복/경로/정확 inventory와 29개 최초 INPUT 또는 supplement input/output SHA 전부 직접 대조 통과. 격리 worktree `workspace/cache/forecast-browser-gpt`에만 적용. 기준 입력 commit `baf846e7ac1a5184727294d1705cf11d514e50f5`; 미커밋/미통합 후보.
- Forecasting/native E2E/schema + 원래 독립56 + runner/positive/input-binding: **142 passed, 1 skipped, 15.44s**. Skip은 Windows symlink 생성 권한에 한정. 로그 `workspace/cache/browser-gpt-forecast/local-review-04.log`.
- 새 wheel/sdist build 성공. 공식 bundled setuptools를 사용했고 리뷰 환경을 변경하지 않았다. 로그 `build-review-04.log`.
- 전체 회귀 직접 실행: **809 passed, 2 skipped, 206 subtests passed, 156.18s**. 로그 `full-review-04.log`. 아래 독립 반례는 기존 전체 suite에 포함되지 않았으므로 이 통과가 네 결함 해결을 뜻하지 않는다.
- Native XGBoost/LightGBM train-save-load-infer 통과는 합성 데이터에 한정하며 실제 금융 성능 증거가 아니다.

## 새 독립 수락 검토

별도 Codex `/root/browser_patch_04_acceptance_review`가 29개 SHA를 독립 확인하고 아래 네 P1을 합성 Git/공식 canonical 임시 run DB/cached predictor로 재현했다. 총괄도 같은 요구사항을 읽기 전용 `independent_acceptance05_probes.py`로 직접 실행해 **7 failed, 1.78s**로 확인했다. 이는 기존 142 PASS가 다루지 않던 반례다. runtime source는 수정하지 않았다.

1. `ensemble.py:96,204`: 채택 여부 확정 전 anchor_ratio_guard 실행. 제외될 current_fair_value anchor1000이 정상 peer100을 제거하여 UNAVAILABLE. 제외될 nominal anchor110은 split-adjusted 출력 basis를 오염시켜 예외. anchor eligibility 먼저 확정하고 채택된 anchor만 guard/출력에 사용해야 한다.
2. `integrity.py:151`: `git status --porcelain`은 ignored executable을 감지하지 못한다. tracked `model/kronos.py`를 ignored `model/kronos/__init__.py`가 shadow하여 pin/clean 확인을 통과하고 다른 코드가 import된다.
3. `store.py:217,227`: ensemble.components point100을 동일 ID/context의 saved point1000과 연결해 저장할 수 있다. bundle과 external-link 모두 active component의 실제 내용/semantics/provenance 결속 및 atomic 거부 필요. 공식 DB JOIN에서 `(1000,100)` 재현.
4. `adapters/tabular_ml.py:129,152`: target prefix 및 0.1y tolerance로 target1y/horizon5y 모순과59ME 기간이 허용된다. target/model identity/trained horizon/cadence exact binding 필요. cached predictor 분기 검사이며 native 성능 검사가 아니다.

## 05 요청

같은 GPT 대화에 네 재현과 정상/부정 반례, 기존 readonly probes 보존, 정상 native trainer/save/load 및 engine anchor links 유지, atomic rollback 검증을 전달했다. 최초 INPUT+supplement 대비 누적 ZIP/input-output SHA/실제 실행 handoff 반환을 요청했다. 05 수신/재검증/새 독립 수락/별도 최종 검증/통합 전 완료 판정 금지. Root 사용자 WIP·원격 상태·실제 개인 DB·주문 미변경.
