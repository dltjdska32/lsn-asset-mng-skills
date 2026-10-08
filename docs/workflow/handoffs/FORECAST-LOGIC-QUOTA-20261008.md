# FORECAST-LOGIC 계정 한도 중단 인계

2026-10-08 Codex. 사용자 승인 역할: Gemini CLI 구현/local commit, Codex 설계·독립 검토. Gemini3.1ProHigh/high의 session-only --dangerously-skip-permissions. 전역 권한 변경, push, 배포, 개인 DB, 주문은 없음. 현재 자동화 예약은 만들지 않았다.

## 실제 중단 원인

Antigravity CLI 1.2.12에서 API `RESOURCE_EXHAUSTED (code429): Individual quota reached` 발생. 12:37~12:39 KST에 reset까지3h6~8m 안내. 인증 문제가 아니다. 세 foreground sessions93377/97154/86795는 모두 종료됨. CORE04/DATA03 부분 수정은 커밋 전에 quota로 끝났고 integrity03은 실질 수정 전 끝났다. Gemini3.8FlashHigh 목록 존재는 확인했지만 계정 한도 사용 가능 여부나 전환 승인은 아직 없다. 사용자 선택 질문: 3.8FlashHigh 전환 또는3.1Pro reset 후 재개.

## 정확한 worktree와 마지막 commit

| 담당 | 경로(프로젝트 workspace/cache 아래) | branch | 마지막 commit |
|---|---|---|---|
| Core | forecast-v7-logic-fix | codex/forecast-v7-logic-fix |9de304163f60706c1b58ffd4be2fde4add10a337|
| Data | forecast-v7-data-fix | codex/forecast-v7-data-fix |a124234e876a2f9ec34ba82ef761a92425cbda83|
| Integrity | forecast-v7-integrity-fix | codex/forecast-v7-integrity-fix |6a1ecc2de6bc4befdcf2cfbdff3cc59892aef6fe|

Core dirty owned: contracts/engine/ensemble/scenario, test_v7_logic_core, CORE04 handoff. Codex design/review docs도 dirty/untracked이므로 별도 소유권 준수. Data dirty owned: dataset/tabular_ml/train CLI, new tests/test_e2e_forecast. Integrity 코드 clean, handoff01/02 및 Codex review untracked. 기존 루트 미커밋 personal/ledger·materiality·portfolio/recent_events 변경은 이 작업과 무관하며 유지했다.

## 직접 실행한 최신 검사

- Core 부분 수정: 기존+독립66 PASS,1warning1.84s(`independent-core-review-06.log`). 추가 반례3개 중 ROIC growth 경고는 PASS, covariate timestamps가 history와 실제 일치하지 않아도 통과하고 adapter 미래 as_of가 COMPLETE로 남아 실패. 독립41개39PASS/2FAIL .72s(`independent-core-review-07.log`). 전체 최종 통과 아님.
- Data 부분 수정: forecasting + new native E2E + 독립7개를 실행하여39PASS/2FAIL,8warnings9.14s(`independent-data-review-04.log`). 두 신규 미래cutoff/다른target 차단은 통과. 실패1은 timezone-naive 기존 fixture가 strict API와 불일치; 실패2는 data분기 ModelForecast에 validation_level이 없어 E2E가 XGB 단계에서 중단됨. 또한 E2E request history origin2020-12-31, asof2023-01-01,target2028-01-01이 최종core target계약과 불일치하므로 올바른 aware history/origin으로 Gemini 통합 때 수정해야 함. nativeLightGBM까지 train→infer 완료했다고 보고하면 안 됨.
- Integrity6a1ecc2: native runDB 및 독립 반례10개8PASS/2FAIL1.09s(`independent-integrity-review-02.log`). Chronos/Kronos 요청5step/2020인데2030 단일행도COMPLETE. independent_integrity_probes.py에 forecast/caller종목불일치·일반booleanmetadata·prototypeDB 차단3개를 더 추가했고 아직 새8개 전체 실행은 하지 않았다.

로그/readonly Codex probes/정확한 Gemini prompts는 각 worktree ignored workspace/cache에 보존. 깨끗한 독립Python은 프로젝트 workspace/cache/forecast-review-venv/Scripts/python.exe(환경 수정 금지). PYTHONPATH=<branch>/runtime, PYTEST_DISABLE_PLUGIN_AUTOLOAD=1, PYTHONDONTWRITEBYTECODE=1. basetemp는 OS Temp 밖이 아니라 **체크아웃 밖 OS Temp**에 지정: repo 내부 synthetic DB는 noDB packaging/structure tests를 깨뜨린다.

최종 추가 독립 검사 실행: Integrity8개 **3PASS/5FAIL**,1.17s(`independent-integrity-review-03.log`). 종목 Y forecast를 인자 X로 저장해도 오류가 없고, boolean metadata는 blanket bool rejection으로 실패하며, matching prototypeDB는 canonical 사전 검증 없이 INSERT까지 진입 후 no such table OperationalError로 실패한다. 후자는 성공 저장이 아니라 잘못된 역할/스키마에 사전 fail-closed하지 않는 오류다. 위 미실행 표시를 이 최신 실행 결과로 대체한다.

## 재개할 작업

1. 사용자 모델 선택 후 기존 부분 코드를 존중하며 이어서 Gemini 수정(같은 exactownership/localcommit; 작업 ID와 기준 SHA 명시). Core04 두 실패 추가 수정, Data03 실제두 native모델 E2E/API/단위·currency·basis·target schema 정합, Integrity03 assignment 전 항목 수행. 마지막 assignment files: gemini-corrections-04.txt, gemini-data-corrections-03.txt, gemini-integrity-corrections-03.txt.
2. Integrity 미완료: mandatory pinned revision/tokenizerweights/bootstrap local-only zeroGitnetwork, explicit source verify beforeimport/allcachedchildpaths, fullpredictionpath/time/ID, nativecanonicalvalidator beforewrites, semanticUTCasof/caller binding, booleansallowed metadata, recursivefiniteJSON, atomic save_bundle withvalidsame-runcomponentlinks. 기존 run migration SQL-only등록은 구현됨. evidence.manager의 REQUIRED_RUN_TABLES catalog 등록만 최소범위 확장 허용.
3. 세 frozen acceptable commit을 Gemini integrator가 합치고 constructor/status/validation_level/pricebasis/target기간을 일치시킨다. engine이 save_bundle을 호출하고 assessment와 linked componentids를 저장해야 한다. Codex docs는 Codex가 별도 관리하고 Gemini가 stage하지 않는다.
4. 동일 exact integrated SHA에서 forecasting+독립 반례, 전체 기존 회귀, fresh wheel/sdist/packaging 실행. 새 Codex 독립 최종 검증 세션에서 다시 검증한 뒤 수락/루트통합. 현재 어느 수정본도 최종 통합/수락하지 않았다.

원본 감사 보고서 `reviews/FORECAST-V7-DESIGN-AUDIT-20261008.md`, 진행 검토 `reviews/FORECAST-LOGIC-PROGRESS-20261008.md`, 설계 및 parallel배정 문서 참조. 실weights금융추론/실데이터5년OOS/7mode자동실행/실전Top10유효성은 검증되지 않았고 이 사실은 수정 후에도 구별한다.
