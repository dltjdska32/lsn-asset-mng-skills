# LUNA-C-THESIS-REFRESH-01 인계

## 배정과 기준

- 요구사항: R14 `THESIS_REVIEW`, `REPORT_REFRESH`; C reporting 서비스만 구현
- 기준 root/source SHA: `81dcda89b31dc52ac4e765b672e72c066badad91` (`codex/autonomous-integration`)
- 구현 branch: `codex/luna-c-thesis-refresh-01`
- 허용 파일: `runtime/investment_stack/reporting/thesis_refresh.py`, `tests/unit/test_r14_thesis_refresh.py`, 본 handoff
- 실행하지 않는 작업: dispatcher/router 및 A 소유 파일, B freshness 파일, personal.db 사용, posting, 원격 push

## 서비스 API와 안전 경계

- `review_thesis(request, evidence, analysis_as_of=...)`는 사용자 `ThesisClaim` 문장·중복 없는 claim ID·구조화된 반증 조건·기존 근거 refs가 빠지면 WAIT를 반환한다. claim matrix는 claim별로 최신 `SELECTED`·`ELIGIBLE`·`FRESH/CURRENT` 근거만 사용하며 observed/public 시각이 모두 분석 기준시각 이하여야 한다. 같은 최신 시각 값 충돌, 근거 부족, 반증되지 않았지만 명시적 지지 조건도 없는 경우는 UNCONFIRMED다. 명시적 지지 조건을 충족할 때만 SUPPORTED, 반증 조건 충족 시 REFUTED다. 결과는 `ReportSectionInput`으로 A 고정 router에 주입 가능하다.
- `refresh_report(request, services)`는 prior run/report ref와 원래 mode/대상/가정이 저장된 snapshot과 일치해야 한다. `ASSET_UPDATE`, `THESIS_REVIEW`, `REPORT_REFRESH` 재귀를 막고 portfolio/single/comparison/scenario 분석의 고정 runner만 허용한다. 새 run ID, 뒤의 timezone-aware clock, IANA timezone, positive state version, state ref를 요구하고 injected `verify_pinned_run`이 run storage에서 실제 pin을 확인한다. replay callback에 posting/refresh 플래그가 모두 false인 `FixedModeReplay`만 전달한다. 결과 section fingerprint별 CHANGED/UNCHANGED/UNKNOWN delta와 `ReportSectionInput`을 만든다.
- 기존과 새 run의 적합성 검증·run storage 접근·고정 원 모드 서비스는 callback 계약으로 분리했다. A router는 정적 allowlist runner, 실제 prior report resolver, 새 run/state pin 생성기 및 저장소 pin verifier를 주입해야 한다. dispatcher 구현 또는 라우터 변경은 이 배정 범위가 아니다.

## 검증

- 명령: `$env:PYTHONPATH='runtime'; C:/Users/lsn/lsn-asset-mng-skills/.venv/Scripts/python.exe -m unittest tests.unit.test_r14_thesis_refresh tests.unit.test_phase6_report_review tests.integration.test_phase6_report_runtime tests.acceptance.test_phase8_request_modes -v`
- 결과: **26 tests PASS** (신규 7개, 기존 Phase 6/reporting/R14 route 19개), 2026-09-27.
- 전용 refresh 통합 테스트는 임시 경로의 synthetic `RunDatabaseManager` run.db 두 개를 만들고 run clock·state pin·report section ref를 읽어 검증했다. temp 경로의 personal.db 존재 여부도 확인했고 실제 personal DB는 사용하지 않았다.
- `git diff --check`: PASS. 독립 dispatcher 전체 통합/네트워크/provider 테스트 및 전체 저장소 테스트는 실행하지 않았다.

## 남은 통합 작업

- A는 reporting 모듈에서 명시적 API(`review_thesis`, `refresh_report`, request/evidence/service contracts)를 가져와 고정 route에 주입한다. 사용자의 free-text thesis를 자동 생성하지 말고 적격 근거 collector의 typed result를 넘긴다.
- refresh runner allowlist는 posting capability가 없는 원 분석 서비스만 포함해야 한다. 상태 pin verifier는 run.db에서 새 run_id, analysis clock/timezone, pinned state_version/snapshot reference를 확인해야 한다.
- 다음 담당자가 새 branch에서 통합 검증한다. 개인 database bridge, transaction writer, recursive refresh runner를 주입하면 안 된다.
