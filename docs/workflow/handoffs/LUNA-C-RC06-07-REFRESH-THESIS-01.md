# LUNA-C-RC06-07-REFRESH-THESIS-01 인계

- 작업 ID: LUNA-C-RC06-07-REFRESH-THESIS-01
- 검토 항목: RC06, RC07, RC09, RC10, R17 사용자 출력 보완
- 요구사항: REQ-2026-09-23-v1, R14/R17
- 설계 기준: DESIGN-2026-09-23-v0.1 (초안; 검토 지적에 대한 fail-closed/표현 보완)
- 코드 기준 커밋: `45e93bbd82855ed3316d158b03cdacfa9520f910`
- 브랜치: `codex/luna-c-rc06-07-refresh-pin`

## 변경

- **RC06:** delegated report identity metadata에서 새 enriched `report_ref`가 원본 manifest에 의해 덮이지 않도록 병합 순서를 고쳤다. 원래 delegated ref는 `source_report_ref`로 보존하고, wrapper가 돌려준 ref와 저장 manifest가 일치하는 synthetic run.db 회귀를 추가했다.
- **RC07:** thesis 첫 실행 단계에서 요청 run ID, bound run.db ID, 저장된 `THESIS_REVIEW` 모드, timezone-aware pinned clock을 검증한다. 불일치 시 unsupported로 중단하여 evidence/calculation/report가 다른 run.db에 쓰이지 않는다. 다른 run ID와 다른 저장 모드 사례에서 source/request DB 양쪽의 evidence, calculation, report section 부재를 확인했다.
- **RC09:** REPORT_REFRESH의 `PIN_PERSONAL_STATE`를 전용 refresh pin 검증 핸들러에 연결했다. refresh resolver가 재실행 후 `typed_portfolio_request` 누락을 만들어내지 않는지 테스트한다.
- **Replay pin 연결:** fixed-mode rerun payload에 실제 `PinnedRefreshContext`를 `refresh_context`로 전달하고, 내부 `execute_mode` 요청에서 run ID/시계/state version/snapshot ref를 검증했다.
- **RC10:** 부분 단계/누락 입력이 있으면 보고서에 한국어 완료 제한 문구를 넣고, 누락/부분 단계의 내부 ID는 구조화된 section metadata에 둔다. 자료 확인 상태에도 partial을 반영해 정상 자료라는 상충 문구를 막았다.
- **R17:** 이 번들이 소유한 네 모드 본문에서 사용자 문구·섹션 제목을 한국어로 정리하고, snapshot/claim/assumption 식별자는 본문에서 감췄다. 근거와 계산 참조는 `상세 근거`/`상세 계산 근거`로 표시하고 run.db 구조화 기록에 유지한다. 긴 수치는 쉼표와 제한된 소수 자리로 출력한다. 다른 모드 delegated report handler의 출력이 바뀌지 않는 회귀도 추가했다.

## 검증

- 집중 테스트: portfolio/thesis bundle, thesis refresh, dispatcher, Phase 6 report runtime — 22 tests PASS; 이후 비대상 모드 출력 회귀를 추가해 portfolio/thesis bundle 3 tests PASS.
- 전체 테스트: `python -m unittest discover -s tests -q` — 579 tests PASS, 1 skipped.
- 패키징 검증용 로컬 wheel/sdist 빌드 성공.
- `git diff --check` PASS.
- synthetic run.db만 사용했다. 개인 DB, 외부 네트워크, 자동 주문은 사용하지 않았다.

## 남은 사항

- 새 Codex 세션의 독립 검토와 통합 후 최종 검증은 총괄 세션에서 수행한다.
- R17 표현 정리는 이 C bundle이 렌더링하는 사용자 본문에 한정된다. reporting 공통 renderer 및 저장된 상세 provenance 구조는 수정하지 않았다.
