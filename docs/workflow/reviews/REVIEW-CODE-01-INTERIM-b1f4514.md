# REVIEW-CODE-01 추가 번들 중간 검토 — b1f4514

- 검토 task: `01a0e30c-b115-7db0-9a6c-b05a962b2d8c`, 독립 worktree `89b8`.
- 직접 검토/실행한 SHA: `b1f451454f2c2bbfe5092d064ebe1b6a92b80fe0`.
- 기준: REQ-2026-09-23-v1, DESIGN-2026-09-23-v0.1 및 D17/D18. 이전 중간 기준 `979cc5efb5d8bbb54e198ed9cb02ec891444c7de` 이후 B R15 패키지 및 C 네 모드 번들 변경을 중심으로 검토했다.
- 구현/기존 테스트 수정, commit/push 없음. 합성 입력과 임시 DB만 사용. 이 기록은 최종 전체 검토 또는 별도 VERIFY 통과가 아니다.

## 결과

기존 전체 **576 tests OK, skipped=1**. 독립 반례 **5 tests, 5 FAIL**. 새 P1 세 건(RC06/07/10), P2 두 건(RC08/09)을 소유자에게 회송했다. 이전 RC04-R1·RC05-R1의 후속 수정은 이 SHA에 포함되지 않았으며 이 문서는 그 수정의 통과 판정을 하지 않는다.

### RC06 [P1] 위임된 보고서의 반환 참조가 저장된 manifest에 존재하지 않음

- 요구사항: R14, R16. 담당 C.
- 위치: `runtime/investment_stack/execution/portfolio_thesis_modes.py:795–807`, 특히 805.
- `_attach_refresh_identity`는 원 manifest의 `report_ref`를 유지한 채 `metadata={"report_ref": enriched_ref, **manifest}`를 기록한다. 뒤의 기존 값이 새 참조를 덮어쓰지만 반환값은 새 참조다.
- 재현: 기존 실제 equity bundle fixture의 단일 FANUC 분석 서비스를 `portfolio_thesis_services(base_services=...)`로 합성하고 target/assumptions를 지정한다. 정상적으로 보고서를 생성하지만 반환된 `run-report:review-enriched:sha256:...`와 일치하는 manifest가 run.db task_states에 없다.
- 영향: 반환 참조로 이전 보고서를 조회하는 후속 갱신 경로가 원 보고서를 찾지 못한다. 합성 서비스로 감싸기 전 정상인 단일 자산 모드도 손상된다.
- 기대: 반환 참조와 저장 manifest의 identity가 일치하고 그 참조로 prior report를 다시 조회할 수 있어야 한다. hash 입력과 report_ref 생성 규칙도 일관되어야 한다.
- 독립 probe: `test_rc06_delegated_report_ref_resolves_in_run_db`, FAIL.

### RC07 [P1] 다른 run의 논지 요청을 연결된 run의 시각/DB로 처리함

- 요구사항: R01, R14, R16, run.db 분리/고정 기준시각 계약. 담당 C.
- 위치: `portfolio_thesis_modes.py:376–385`, `:412`, `:423–445`.
- run registry는 dispatcher가 요청 run을 허용하게 하지만 thesis handler는 request.run_id와 bound run_db를 일치시키지 않는다. 증거/계산/보고서를 bound DB에 쓰고 cutoff도 bound DB에서 읽는다.
- 재현: bound `source` run의 cutoff를 2026-09-27 12:00 UTC, registry의 `requested` run cutoff를 2026-09-26 12:00 UTC로 설정한다. `requested`에 논지 검토를 요청하면서 9월 27일 11:01 공개된 지지 증거를 제공한다.
- 실제: ModeResult.run_id=`requested`, availability=COMPLETE. 그러나 계산/보고서는 `source` DB에 저장된다. 계산의 cutoff는 9월 27일이고 verdict=SUPPORTED다. 요청 DB에는 해당 계산이 없으며 요청 시각 이후 정보를 사용했다.
- 기대: 서비스 결합이 특정 run 전용이면 첫 변경 전에 불일치를 거부한다. 다중 run 지원이면 모든 시각 조회·증거/계산/보고서 저장을 요청 run으로 라우팅해야 한다. mode pin도 같은 경계에서 확인해야 한다.
- 독립 probe: `test_rc07_cross_run_thesis_cannot_use_wrong_clock_or_write_wrong_db`, FAIL.

### RC08 [P2] 배포한 sdist 테스트가 배포에서 제외된 문서를 요구함

- 요구사항: R15. 담당 B.
- 위치: `tests/test_packaging.py:115`; 같은 파일의 sdist allowlist 및 `MANIFEST.in`.
- sdist에는 두 R15 검증 파일을 넣지만 version 테스트가 읽는 `ARCHITECTURE.md`는 정확한 allowlist에서 제외한다.
- 재현: 이 SHA에서 다시 만든 tar.gz를 임시 디렉터리에 안전하게 풀고 포함된 `TestPackaging.test_distribution_and_runtime_versions_are_not_conflated`를 직접 실행한다. `ARCHITECTURE.md` FileNotFoundError.
- 영향: 저장소 원본에서는 통과한 검증이 배포 소스에서는 실행되지 않는다. wheel import/설치 실패와는 구별된다.
- 기대: 배포 대상 테스트가 사용하는 비민감 문서를 포함하거나, 저장소 전용 확인과 배포 소스 확인을 명시적으로 분리한다.
- 독립 probe: `test_rc08_sdist_version_test_has_its_required_architecture_resource`, FAIL.

### RC09 [P2] 보고서 갱신에 별도 구현한 pin handler가 연결되지 않음

- 요구사항: R14. 담당 C.
- 위치: `portfolio_thesis_modes.py:512`의 `pin_refresh_state`, `:616` handler mapping.
- `pin_refresh_state`가 구현되어 있으나 사용되지 않는다. 갱신 모드의 `PIN_PERSONAL_STATE`도 `pin_portfolio`로 실행된다.
- 재현: 기존 네 모드 E2E fixture 그대로 실행한다. refresh resolver가 새로운 state_version=8/snapshot/clock의 portfolio_request를 제공하고 갱신 재실행이 끝났는데, 외부 refresh 요청은 portfolio_request를 중복 전달하지 않으므로 pin step이 `PARTIAL`, missing=`typed_portfolio_request`를 생성한다.
- 영향: 유효한 갱신도 불필요한 입력 누락을 포함한다. 향후 하위 보고서가 완전해져도 상위 갱신 COMPLETE가 차단된다. 기존 테스트는 PARTIAL만 기대하여 잘못된 원인을 검출하지 않는다.
- 기대: 갱신 모드에서는 검증한 새 run/pin 결과를 전용 handler로 이어받고, 실패 원인과 실제 부족 입력만 보고한다.
- 독립 probe: `test_rc09_refresh_pin_does_not_require_outer_portfolio_payload`, FAIL.

### RC10 [P1] 필수 입력이 부족한 실행을 사용자 보고서에서는 확인 완료로 표시함

- 요구사항: R14, R17. 담당 C.
- 위치: `portfolio_thesis_modes.py:566–578`, `:590`, `:602–612`.
- render_report는 기존 step의 missing_inputs/PARTIAL을 Phase6 보고서 생성에 반영하지 않는다. 보고서와 manifest를 생성·저장한 뒤 ModeResult만 PARTIAL로 낮춘다.
- 재현: 기존 네 모드 fixture의 시나리오 결과는 `PARTIAL`, missing_inputs=`approved_materiality_selector`. 실제 report.availability와 manifest는 AVAILABLE이고 본문은 **보고서 상태: 확인 완료**, **정보 신뢰도: 높음**, Data Quality에는 `No material stale, conflicting, missing-provider, or unavailable input was detected in the run evidence.`가 나온다.
- 영향: API 메타데이터만 보면 누락을 알 수 있지만 최종 사용자에게 제공하는 보고서에서는 필수 입력과 불확실성이 사라진다. 개인 포트폴리오 fixture에서도 전체 PARTIAL 표시와 별개로 Data Quality가 누락 없음이라고 주장한다.
- 기대: 상위 단계의 실질적인 누락/partial을 설명 가능한 사용자 문구로 보고서에 전달하고 보고서 상태·신뢰도·manifest·ModeResult를 일치시킨다. 필수 입력 부족을 해소하지 않고 COMPLETE로 올리지 않는다.
- 독립 probe: `test_rc10_partial_scenario_cannot_render_available_high_confidence_report`, FAIL.

## 직접 실행한 검증

동일 인터프리터: `C:/Users/lsn/lsn-asset-mng-skills/.venv/Scripts/python.exe`, Python 3.14.6. 소스 테스트에는 `PYTHONPATH=runtime`을 설정했다.

| 검증 | 결과 |
|---|---|
| 신규 네 모드 E2E + skill sync | 5 tests OK |
| 현재 SHA의 `python -m build --no-isolation` | wheel/sdist 재생성 성공 |
| 원본 작업 폴더 packaging + skill sync | 10 tests OK, skipped=1 (기존 interpreter에는 설치 skill tree 없음) |
| `python -m unittest discover -s tests -q` | 576 tests OK, skipped=1, 58.004초 |
| 깨끗한 임시 venv에 해당 wheel `pip install --no-index --no-deps` 후 R15 검증 | 10 tests OK, skipped=0, 0.508초 |
| sdist를 푼 후 포함된 version 검증 직접 실행 | FileNotFoundError, RC08 |
| `review_code_01_b1f4514_probes.py` | 5 tests, 5 FAIL, 6.476초 |
| 기존 네 모드 fixture의 실제 report.markdown 확인 | RC10 및 아래 R17 잔여 범위 확인 |

임시 venv는 system-site-packages 없이 생성했고 `PYTHONPATH`를 제거했다. 설치된 `investment_stack.__file__`이 임시 venv의 `Lib/site-packages` 아래임을 assertion으로 확인했다. 네트워크 의존성 설치 대신 로컬의 tzdata 2026.4와 truststore 0.10.4 패키지/배포 메타데이터만 복사했다. 테스트의 scripts import를 위해 저장소 root만 추가했으며 runtime 경로는 추가하지 않았다. wheel/설치 payload의 8개 스킬, 원본/미러 32개 파일, UI 메타데이터, 5개 config 및 정확한 경로 allowlist가 통과했다. 이는 인터넷 의존성 해석이나 Codex의 임의 venv 자동 발견을 검증한 결과가 아니다.

재현 명령(PowerShell):

```powershell
$env:PYTHONPATH='runtime'
& 'C:/Users/lsn/lsn-asset-mng-skills/.venv/Scripts/python.exe' docs/workflow/reviews/review_code_01_b1f4514_probes.py
```

## 남은 범위와 판정 한계

- 신규 네 모드 E2E의 심층조사는 합성 callback이다. 실제 credential 기반 기본 심층조사와 실제 personal.db snapshot loader의 연결이 검증되었다고 보지 않는다. 임의 실제 개인 DB를 열지 않았다.
- 실제 렌더링에서 영어 제목/품질 문구, `state_version`, snapshot/claim/assumption/calc ID, 30자리 이상의 비중이 본문에 노출된다. R17의 쉬운 한국어·본문/상세근거 분리 완료로 판정할 수 없다. RC10은 이 가독성 문제와 별개인 상태/불확실성 은폐 오류다.
- 네 모드가 handler에 연결되고 일부 합성 결과를 run.db에 남긴 사실과 R14 전체 생산 경로 완료는 별개다. 갱신은 지원 runner와 저장 prior identity에 의존하며 RC06/09 수정 검증이 필요하다.
- 패키지 경로 allowlist는 통과했다. 허용된 텍스트 내부의 우발적 비밀값까지 탐지하는 검증은 아니며 배포 문서도 이 한계를 명시한다.
- 이번 단계에서 live 공급자 호출을 반복하지 않았다. 이전 979cc5e의 Yahoo/Naver 실제 HTTP→Phase4→Phase5 확인 기록을 최신 SHA의 신규 live 결과로 재표기하지 않는다.
- 새 최종 통합 SHA를 받은 뒤 기존/신규 독립 반례, 최종 변경 diff 및 요구사항별 증거를 재검토해야 한다. 별도 새 세션의 최종 VERIFY는 아직 수행되지 않았다.
