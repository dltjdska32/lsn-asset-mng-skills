# 작업 상태표

**최신 상태 — 2026-09-27 11:20 UTC, SEC parser 수직 통합:** A SEC-01은 자체 테스트 오류와 차원/정렬 결함으로 미인수 후 같은 Gemini 3.1 Pro High A에 SEC-02/03 수정 회송. 최종 A `962930d`에서 신규 SEC 5/5 PASS, 기존 빈-tag 기대가 R04와 충돌하는 1건을 총괄이 갱신했다. root parser 통합 commit `5d094a5`, 이후 B 현재 상태 문서 `fccbe84`를 root `7c8f8f4`에 반영. 총괄 root 전체 **475 OK, skip1** (B 문서 반영 직전 동일 코드 tree). R04는 SEC fact parser 수직 슬라이스뿐이고 실제 `deep_research` 재무 계산 소비/기간 비교 R02–04는 미완. B README 설치 안내와 A R05 structured fallback 수직 슬라이스 진행 중. repo-local 8스킬은 현재 Codex Available skills 목록에서 실제 인식됐지만 설치 wheel 대상 환경 UI 자동발견은 미확인. 독립 전체 코드 검토/별도 최종 검증 아직 미시작.

**최신 상태 — 2026-09-27 11:14 UTC, C ACTION 안전 전구체 통합·A SEC 수정 중:** C `1d5f2f2`의 `decisions/action.py`·테스트·인계를 root `a861b6b`에 cherry-pick했다. C ACTION-04 Gemini 응답은 provider ERROR였지만 실제 파일을 총괄이 검사했고 C 결정 테스트 **11/11 PASS**; root 전체 **470 OK, skip1**를 직접 실행했다. 공개 ActionProposal은 승인 정책 provenance registry가 없으므로 WAIT/수량 없음이며 R10–11 완료가 아니다. A SEC-01 Gemini 3.1 Pro High receipt는 SUCCESS/denied0, 11:08:43–11:10:22 UTC이나 총괄의 신규+기존 provider **10개 중 2 FAIL** 및 차원/입력 검증 결함으로 **미인수**, `GEMINI31-A-SEC-02` 같은 담당에 회송해 수정 중. Root 현재 통합 코드 SHA `a861b6b`이며 A SEC 변경은 미통합. 전체 독립 검토·다른 새 최종 검증 미시작.

**최신 상태 — 2026-09-27 11:03 UTC, A/B/C 선행 통합 검증:** `handoffs/GEMINI31-INTEGRATION-01.md` 참조. source A `65388c1`(계약 `d6ef79b` 포함), B `e2f709b`(R06–08·패키지), C `f7d7465`(13F·브리핑)를 소유 파일별로 root 통합 commit **`571101af3672eea900ebfae9321ace77f78f2473`**에 반영했다. 총괄 직접 전체 unittest **465 OK, skip1**, 별도 깨끗한 synthetic venv wheel 설치 뒤 패키징5/5 PASS. A 계약106/106, 통합 A가격19/19·B42/42·C32/32·기존 보고서25/25 PASS. 아직 R02–05/R09, 정식 R10–11 ACTION, 7모드, 전체 독립 검토/다른 새 최종 검증 미완. C ACTION 수정은 격리 branch에서 진행 중이며 통합하지 않았다.

**최신 상태 — 2026-09-27 10:25 UTC, Gemini 3.1 Pro High 3담당 구현 체크포인트:** A/B/C는 각 별도 branch/worktree에서 코드와 인계를 작성했다. A `d6ef79bc90bb08f0bd170b37653c65a927b029b3`는 실제 등록 요청 정상 저장/reopen·미등록 유효 SHA 거부 probe PASS 및 계약 `106/106` PASS. B `0edbea6f40dbc4bff18ba6fc9f554852b684494b`는 R06–08/패키징 담당 `16/16`, mirror byte `--check`, 실제 wheel/sdist build·격리 target install PASS; 8개 스킬 원본과 UI metadata가 wheel/sdist·설치 target에 있고 민감 파일 0을 확인. C `f7d74653b093ef2b13980658bedd72b66bc1696e`는 브리핑 담당 `6/6`, 기존 report 회귀 `25/25` PASS. A-05/B-04/C-03-R1 호출은 세 독립 Gemini 세션이 10:21:49–10:22:08 UTC에 동시에 실행 중이었고 각 실제 코드 변경을 남겼다. C-03-R1은 마지막 provider 응답 ERROR였으므로 총괄 직접 테스트 후 체크포인트했고 이 사실을 인계에 유지한다. **공통 root runtime 아직 미통합; A 도메인 R01–05/R09, 완전한 R10–11 판단, 7모드, 스킬 발견·설치 안내, 전체 독립 Codex 검토, 다른 새 Codex 최종 검증은 미완료.**

**최신 상태 — 2026-09-27 10:08 UTC, Gemini 3.1 Pro High B/C 교정 체크포인트:** B-02와 C-02 모델 실행은 각각 `status=SUCCESS`, `denied=0`, 서로 09:53:54–09:55:03 UTC에 겹쳤으며 두 담당의 실제 코드 변경을 확인했다. 총괄이 B 새 담당 15/15 및 8스킬 미러 `--check` PASS, C 새 담당4/4와 기존 보고서 회귀25/25 PASS를 직접 실행했다. 분리된 B HEAD `5d66cc784ad6c617b8429ba33c06f0ef7beb3181`, C HEAD `2b772fd584942d70636645958be1f020d879014d`로 체크포인트 commit. C는 A 계산 전의 선행 구조라 최종 판단 완료 아님; B wheel/sdist 실제 설치 검사는 아직. A-02는 마지막 `RunCommand` 거부/모델 stream interrupted로 exit3, 중간 코드 미인수; 새 짧은 대화로 재시도 중. **세 구현 세션 모두의 동시 정상 코드 작성은 아직 미확인.** root 통합/새 전체 독립 검토/다른 새 최종 검증 미시작.

**최신 상태 — 2026-09-27 09:55 UTC, Gemini 3.1 Pro High 구현/수정 진행:** 사용자 지시로 Codex Luna A 진행을 중단하고 stable A/B/C 구현 커밋만 각 새 `codex/gemini31-a/b/c` branch로 옮겼다. `agy models`와 세 setup 쓰기·모델 응답 확인. 세 실제 구현 호출은 겹쳤으나 A/C 첫 headless 요청은 `RunCommand` 거부, B는 코드 작성. C 재시도는 코드 작성 SUCCESS. A 새 conversation 재시도는 두 파일 변경 후 마지막 모델 API 연결 오류로 receipt ERROR지만 root 미등록 descriptor probe PASS와 관련 45/45 PASS 확인. B 새 기술 테스트 4 ERROR, C 새 테스트 4 PASS여도 5단계 브리핑을 5등급으로 오해한 설계 불일치가 있다. `GEMINI31-A/B/C-02` 각 담당 수정 요청을 겹쳐 실행 중; 완료/인수 아님. 정확한 기준 SHA·conversation·초기 호출/검증은 `handoffs/MODEL-SWITCH-02.md`, 각 배정 및 receipt 참조. root runtime 통합, 독립 전체 코드 검토, 다른 새 Codex 최종 검증은 미시작. 이전 기록은 이력이다.

**최신 상태 — A 저장 계약 추가 반례 발견 (2026-09-27):** A `codex/impl-a-luna` HEAD `16a22e0a789b3ce526934474ad3f271fee0cda33`에서 총괄 계약99/99, storage29/29, gate12/12를 재실행했으나, 새 `scripts/workflow/contract-request-descriptor-probe.py`는 FAIL: 등록되지 않은 임의 유효 64-hex request_hash를 snapshot이 수용. 기존 audit의 비 SHA 문자열 거부 1 PASS는 실제 descriptor 결속을 증명하지 않는다. `assignments/CONTRACT-FIX-07.md`로 A에 회송. B/C 담당 수정은 각 branch에서 검증됐지만 root 런타임 통합은 대기.

**최신 상태 — B/C 담당 수정 직접 재검증:** B `codex/luna-b` HEAD `9252038100cf748e77f35996fde1cd1ae4d53cfd`에서 담당 unittest 19 PASS와 공개응답 사본 fallback probe 6 PASS를 총괄 재실행. C `codex/luna-c` HEAD `e2b185f847a02aeb3cab313cef102981f4cf1967`에서 담당 unittest 26 PASS 재실행. 각 결과·미실행 live/전체 suite는 `handoffs/CODEX-B-FIX-01.md`, `CODEX-C-FIX-01.md` 및 `CODEX-TRANSFER-01.md` 참조. A 공통계약 `codex/impl-a-luna`는 AUDIT-03 저장 잔여 수정 중이므로 B/C를 root runtime에 통합하지 않았다. 전체 7모드·스킬셋 패키지·새 전체 독립 검토·다른 새 최종 검증도 미완료.

**최신 상태 — 중복 세션 정리 및 C 첫 수정 확인:** 관리형 준비 ID도 뒤늦게 실제 세션으로 활성화됐음을 확인. 후속 주 담당은 관리형 A `01a0cd99-1059-7d73-b623-be991696c65d` (`codex/impl-a-luna`), 복구 B `01a0cd9c-aff9-7122-b0cc-bd638dbf7f81` (`codex/luna-b`), 복구 C `01a0cd9c-e908-7f30-9991-75cbd9d2004f` (`codex/luna-c`). 중복 복구 A는 중단 후 archive, 관리형 B/C는 종료 후 archive. 상세 매핑은 `handoffs/CODEX-TRANSFER-01.md`. C commit `e2b185f`의 26 담당 unittest를 총괄도 26 PASS 재실행; root 통합은 미완료. B 진행 중, A 공통계약 감사 잔여 수정 중. B 초안 두 갈래 모두 root 독립 오프라인 probe 6/6 PASS이나 전체 인수 전. 새로운 전체 독립 검토/다른 새 최종 검증은 아직 시작하지 않았다.

**최신 상태 — Codex Luna 복구 세션 병렬 시작:** 관리형 worktree 준비 ID 3개가 실제 task ID로 전환되지 않아, 다른 별도 worktree/branch에서 projectless Codex `gpt-6-luna` A/B/C 세 task를 생성했다. 실제 ID `01a0cd9c-71fc-7b93-a08b-60eba72d8d01` / `01a0cd9c-aff9-7122-b0cc-bd638dbf7f81` / `01a0cd9c-e908-7f30-9991-75cbd9d2004f`; `wait_threads`에서 세 작업 active/inProgress 확인. 각 기준 SHA/branch/worktree는 `handoffs/CODEX-TRANSFER-01.md`. 코드 변경·테스트 통과는 아직 미확인. 준비 ID가 뒤늦게 활성화되면 중복 작업을 중단하고 복구 세션만 인수한다.

**최신 상태 — 사용자 모델·담당 변경:** Gemini 구현을 별도 Codex GPT-6 Luna 작업 A/B/C로 이관 요청. `handoffs/CODEX-TRANSFER-01.md`에 각 원 WIP SHA, 새 branch/worktree, 준비 client ID 기록. Gemini 재개 자동화 `gemini`는 PAUSED. 세 새 branch/worktree 생성은 확인했으나 create_thread가 실제 threadId를 아직 반환하지 않아 Codex 세션 실행·모델 적용·병렬 구현은 **미확인**. 기존 18:21 KST 포인터의 Gemini 재개 계획은 이력으로만 읽는다. 다음은 실제 task ID·cwd·모델·실행 로그 확인 후 각 수정 검증 및 후속 도메인/통합/새 독립 검토/새 최종 검증이다.

**최신 상태 — 2026-09-23 18:21 KST:** 제공자 한도 대기 중 A/B/C 고정 체크포인트의 독립 재검증 완료. `handoffs/PRE-RESUME-01.md` 및 신규 배정 CONTRACT-FIX-06 / IMPL-B-FIX-03 / IMPL-C-FIX-03 참조. A 49837ea의 별도 Codex typed-gate AUDIT-04 12개 중 10 PASS/2 FAIL(총괄 동일 재현), B d2db94f의 실제 provider 공개응답 오프라인 replay 6개 중 5 PASS/1 FAIL(BTC/EUR가 BTC/USD 가격 수용), C 377dbb4의 기존 26tests/2 FAIL 원인 확인. 셋 다 WIP이며 root runtime 통합·새 전체 독립 검토·다른 새 최종 검증은 아직 미완료. Gemini는 21:40 KST 이후 재개, 자동화 `gemini` ACTIVE.

**최신 상태 — 2026-09-23 18:10 KST: Gemini 외부 사용량 한도로 중단.** 세 프로세스는429 재시도 후exit3으로모두종료. 자동화`gemini` ACTIVE,21:40 KST이전호출금지/매시45분확인으로21:45 KST부터재개예정. 상세인계는 handoffs/QUOTA-01.md가현재권위다. A49837ea/Bd2db94f/C377dbb4의WIP체크포인트보존. A99tests17ERROR, B25PASS, C26tests2FAIL. 연결·세병렬코드작성은실제로확인했지만전체통합·새전체독립검토·다른새최종검증은미완료. 아래진행중포인터는이력이다.

최신 포인터(08:53UTC): 첫3Gemini병렬구현 실행완료, handoffs/PARALLEL-01.md의 실제교집합약298초/각코드버전확인. 전체인수는아님. A84633e5에서CONTRACT-FIX-05, B82310ef에서IMPL-B-FIX-01, C97db90d에서IMPL-C-FIX-01을각같은conversation으로다시병렬실행중. A계약84중17ERROR/추가storage5PASS, B23중1FAIL1ERROR+실제source반례3개, C8중1FAIL1ERROR. 독립Codex는고정84633e5의CA01/02/06만CONTRACT-AUDIT-03으로검토중. rootruntime통합없음; IMPL-A/BRIEF/INTEGRATE/PACKAGE/최종새REVIEW/VERIFY는미실행. 다음은각수정종료→담당테스트·반례→필요재수정→공통확정및도메인통합이다.

CONTRACT-AUDIT-02 완료: 독립 고정 fdd64f0, 28개 메모리probe9PASS/19FAIL/0BLOCKED, P1 네 묶음(codecstrictness, typedgate/calculation, typedoutputs/diagnostics, providersemantics/units). reports/handoff/scripts를 인수하고 CONTRACT-FIX-05 배정 작성(아직 미실행). 저장FIX-04와 분리해 확인했으며 원주문/renderer/storage 우회까지 증명한 것으로 확대하지 않는다. 감사세션은idle; 이후 전체코드검토/최종검증은 각각새세션유지.

최신 포인터(08:43UTC, D18): A의 CONTRACT-FIX-04와 B의 IMPL-B, C의 IMPL-C를 실제 동시 실행 중. B 시작08:42:53.445UTC/PID29560/conversation f358e983-746e-4dd7-92f6-26a0fea2cb12, C 시작08:42:54.540UTC/PID13456/conversation a0efd37f-f4f2-4e2b-b7bc-8378c4a29926. A는08:34:48UTC 시작/PID6000. 세 모델 gemini-3.8-flash-high high, 별도 브랜치/worktree, 기준 fdd64f05e3c8eb717a6ed2444cc5fb4b9727559e. B/C의 독립 parser/계산 구현만 초안 계약에서 진행하며 저장·공통gate를 우회하지 않는다. 완료/통합은 공통계약 인수와 수정본 재검증 후. IMPL-A 도메인, BRIEF/INTEGRATE/PACKAGE 및 최종새REVIEW/VERIFY는 아직 미실행.

최신 포인터(2026-09-23 08:35UTC): Gemini A `fdd64f05e3c8eb717a6ed2444cc5fb4b9727559e`에서 CONTRACT-FIX-04 실행 중(08:34:48UTC 시작, supervisor6000, conversation c2d86984-7d91-4fba-8723-9b3ec14ad098). FIX-03은 원 독립probe19PASS/계약74개중1FAIL, 추가 실제 DB반례5FAIL로 인수 미완료. 저장/evidence/fullscope를 A에 회송했다. 독립 감사 세션01a0cd29-c54f-7020-a9ec-abe51921f3ee는 고정 fdd64f0에서 CA03/04/07 잔여를 CONTRACT-AUDIT-02로 확인 중. root 런타임 통합 및 IMPL-A/B/C 본 병렬 구현은 아직 대기. 아래08:21 이전 포인터는 이력이다.

## 현재 실행 상태 — 2026-09-23 후속 승인

아래 초기 실행 표는 이력이다. 후속 사용자가 초기 범위 제한을 해제하고 설정부터 Gemini 3세션 병렬 구현·새 Codex 독립 검토·수정·다른 새 Codex 최종 검증까지 승인했다. 현 총괄은 `01a0ccca-ac21-7d93-8bd9-9900ee3ea7cf`이며 기존 총괄은 조회 시 idle이었다. 현재 설계 기준은 DESIGN-2026-09-23-v0.1, 요구사항은 REQ-2026-09-23-v1이다.

| 작업 | 담당·파일 소유 | 의존성 | 현재 상태/완료 조건 |
|---|---|---|---|
| SETUP-02 | 총괄 / workflow 상태·배정·연결 증거 | 사용자 후속 승인 | 연결 probe 완료. 세 conversation ID·모델 생성·파일 read/write·동시 시간대 확인, handoffs/SETUP-02.md. 구현 병렬은 후속 단계 |
| REVIEW-DESIGN-01 | 새 Codex / reviews/REVIEW-DESIGN-01.md | 설계 기준 사본 68fab98 | 완료. 별도 세션 01a0cd29-c54f-7020-a9ec-abe51921f3ee, P1 8건·16 자체테스트·합성반례. 수정계약 채택, 구현 검증과 구분 |
| CONTRACT-01 | Gemini A / contracts/**·evidence/manager.py·providers/models.py·providers/contract_adapters.py·신규 계약 테스트 | 독립 검토 수정 계약 | 최초 f1b9caa(32테스트 OK, 별도반례 실패) → 73d376e(37테스트 중2fail/10error) → 1462fb6(55테스트 중2error, 독립반례17FAIL/2PASS). CONTRACT-FIX-03 A 수정 중. 계약 인수 전 B/C 본구현 대기 |
| IMPL-A, ANALYSIS-09 | Gemini A / design §9의 A·R09 파일 및 A 전용 테스트 | CONTRACT-01 | 대기. R01–05·09, 현재 경로 연결과 적격성·계보 회귀 |
| IMPL-B, ANALYSIS-08 | Gemini B / design §9의 B·R08 파일 및 B 전용 테스트 | CONTRACT-01 | 대기. R06–08, 실제 source 접근과 fixture 구분 |
| IMPL-C, ANALYSIS-13 | Gemini C / design §9의 C·R13 파일 및 C 전용 테스트 | CONTRACT-01 | 대기. R12–13, 공개시점·정정·UNVALIDATED gate |
| BRIEF-01 | Gemini C / decisions/**, reporting/** 및 신규 전용 테스트 | A/B/C typed 결과 | 대기. R10–11·17, 수치 binding·non-posting |
| INTEGRATE-01 | Gemini A / routing/**, pipelines/**, execution/**, cli.py, asset_analysis.py, 공통 연결 및 신규 통합 테스트 | A/B/C/BRIEF 인계 | 대기. R14·16 실제 7모드 결과까지 |
| PACKAGE-01 | Gemini B / README·IMPLEMENTATION_STATUS·ARCHITECTURE·pyproject·skills/**·동기화 스크립트·신규 설치 테스트 | 통합 API 전달 | 대기. R15 설치·배포 allowlist·미러 |
| REVIEW-CODE-01 | 또 다른 새 Codex / reviews/REVIEW-CODE-01.md | 통합 commit | 대기. 직접 코드·테스트 검토, 문제가 있으면 소유 Gemini에 회송 |
| VERIFY-01 | 검토자와 다른 새 Codex / reviews/VERIFY-01.md·handoffs/VERIFY-01.md | 수정 완료 commit | 대기. 최종 SHA에서 직접 검증, 미확인 live와 정책 제한 명시 |

각 Gemini는 별도 `codex/gemini-a`, `codex/gemini-b`, `codex/gemini-c` 브랜치와 worktree를 사용한다. 총괄만 commit·cherry-pick·공유 문서 갱신을 한다. 세션은 지정 파일과 자신의 인계만 편집하며 공통 파일 변경 요청은 인계로 전달한다. 정확한 worktree·배정 기준 SHA·세션 결과는 SETUP-02 및 개별 assignment에 기록한다. 테스트는 임시 합성 DB만 사용한다. 과거 별도 승인 문구는 이번 사용자 승인으로 대체되며, 미확정 투자 정책은 출력 불가/조건부 상태로 구현하고 임의 값을 정하지 않는다.

설정 중 최초 sandbox 조회는 로그 쓰기/인증 접근 제한으로 실패했다. 동일 `agy models`를 권한 경계 밖에서 재조회하여 모델 목록을 받았다. 전역 권한 정책은 변경하지 않았다. 아직 구현 성공·3개 병렬 실행 성공으로 간주하지 않는다.

2026-09-23 후속 실행: Antigravity print는 외부 worktree read_file 및 read_url을 soft-deny하면서 SUCCESS/빈 response를 반환함을 확인했다. driver가 denied_actions와 실제 응답까지 검사하도록 수정했다. 검토 문서를 자기 worktree로 복사하고 외부수집은 총괄이 수행하여 범위를 좁힌 뒤 A 수정 재개, B/C의 로컬 PREP는 exit0·denied0·실제 인계 작성 완료(07:52:47–07:54:09UTC). 전역 승인 설정 변경 없음. B/C runtime 구현은 아직 시작하지 않았다.

공개 live 수집·TLS 진단은 source-checks-2026-09-23.md에 별도 기록. truststore0.10.4 scoped SSLContext로 TLS/hostname 검증 유지 상태에서 SEC CompanyFacts·submissions, Naver basic/OHLCV, Yahoo chart, Coinbase ticker HTTP200 확인. Investing와 SEC archive 원문은403. 전체 수집→계산 E2E 성공과 혼동하지 않는다.

CONTRACT-AUDIT-01: 같은 별도 검토 세션이 고정 `73d376e32437bf78f8534d040c68db106e59acb7` 작업 폴더 C:/Users/lsn/lsn-asset-mng-worktrees/contract-audit를 직접 감사했다. 추가 P1 CA01–07, 보고서·인계와 scripts/workflow/contract-audit-probes.py를 인수했다. 검토자 자신의 실행은18FAIL/1BLOCKED, 총괄이 이후1462fb6에 실행한 것은17FAIL/2PASS다. 부정경계 감사 결과이며 전체 suite 통과 수가 아니다. 신뢰 가능한 canonical evidence와 전체 binding 대조·strict bool/enum/type·gate·저장 재개·lossless adapter·semantic scope를 FIX-03으로 회송했다. 전체 구현 후 새 REVIEW-CODE-01/VERIFY-01은 아직 미실행이다.

현재 실행 포인터(2026-09-23 08:21UTC): root 통합 브랜치 `codex/autonomous-integration`에는 workflow/자동화 문서만 반영되어 있으며 Gemini runtime commit은 아직 통합하지 않았다. A 브랜치 최신 확정코드는 `1462fb682c10364fb9510b42593ac352b6dca523`, 그 위에서 CONTRACT-FIX-03 작성 중. A conversation `c2d86984-7d91-4fba-8723-9b3ec14ad098`, 실행 receipt `gemini-a/workspace/runs/CONTRACT-FIX-03.receipt.json`, supervisor PID13304, 08:17:51UTC 시작. B/C는 SETUP/PREP 완료 후 계약 인수 대기. 계약 감사 Codex는 완료·idle이며 후속 전체 REVIEW-CODE/VERIFY는 각각 새 작업으로 생성한다. 사용자의 자율 진행 승인은 유지되므로 추가 지시를 기다리지 않는다.

다음 실행 순서: FIX-03 종료/파일 소유 확인 → 같은 worktree의 test_contract 및 독립 probe → 필요한 Gemini 수정 → 전체회귀 → 계약 커밋/통합 → root가 검토한 같은 계약과 최신 배정을 A/B/C 각각 전달(복사 문서와 기존 인계를 보존) → IMPL-A/B/C 동시 실행과 receipt 시간대 확인 → 분석/BRIEF/INTEGRATE/PACKAGE → 새 REVIEW-CODE → 수정 → 다른 새 VERIFY. 실제 오류가 남아 있으면 준비/테스트 수를 완료로 바꾸지 않는다.

---

관리: 총괄 Codex. 갱신: 2026-09-23. 요구사항: REQ-2026-09-23-v1.
초기 코드 기준: `3d4a95ba33d582f67a99de7b410b160e62645961` (main, 로컬 origin/main과 동일; 원격 fetch 미실행).
시작 시 작업 트리 깨끗함, 기존 AGENTS.md와 workflow 문서 없음.

| 작업 ID | 범위 / 담당 | 의존성 | 상태 | 브랜치 / 기준 |
|---|---|---|---|---|
| INIT-01 | 자료·현재 코드 확인, 요구사항·상태·지침 / 총괄 | 사용자 첫 실행 요청 | 완료 | main / 위 코드 기준 |
| DESIGN-01 | 17개 구현 명세 초안·데이터 계약·결정 기록 / 별도 Codex 설계 | REQ-v1 및 기준 코드 | 초안 작성 완료·미승인 | main / 위 코드 기준; 문서별 단일 작성자 |
| REVIEW-DESIGN-01 | 설계 독립 검토 / 새 Codex 검토 | DESIGN-01 | 미시작·후속 단계 | 미배정 |
| SETUP-01 | Gemini 모델·권한·동시성의 단계별 검증 / 사용자+총괄 | 사용자 다음 설정 | 미시작 | 저장소 구현 없음 |
| CONTRACT-01 | 공통 타입·저장 계약·registry/config / 단일 Gemini 통합 구현자 지정 예정 | 독립 설계 검토, 사용자 후속 구현 지시, SETUP-01 | 미시작·담당 미지정 | 공통 파일 단일 소유, 새 기준 커밋 확정 후 전달 |
| IMPL-A | R01–05 계산·데이터 신뢰성 / Gemini A 예정 | CONTRACT-01, SETUP-01 | 미시작 | 별도 브랜치/worktree 예정 |
| IMPL-B | R06–07 웹 시세·OHLCV / Gemini B 예정 | CONTRACT-01, SETUP-01 | 미시작 | 별도 브랜치/worktree 예정 |
| IMPL-C | R12 13F 수집·비교 / Gemini C 예정 | CONTRACT-01, SETUP-01 | 미시작 | 별도 브랜치/worktree 예정 |
| ANALYSIS-01 | R08 차트, R09 적정가, R13 점수 검증 / Gemini 후속 | 각각 B, A, C 및 승인 계약 | 미시작 | 세부 분할 미배정 |
| BRIEF-01 | R10–11 판단, R17 브리핑 / Gemini 후속 | 적격 가격·분석·개인위험 계약 | 미시작 | 미배정 |
| INTEGRATE-01 | R14–16 실행·문서·통합 / 담당 후속 지정 | 각 구현·독립 검토 | 미시작 | 공통 파일 단일 담당 |
| VERIFY-01 | 최종 코드 직접 테스트 / 새 Codex 최종 검증 | 통합 최종 커밋·검증 자료 | 미시작 | 검토자와 별도 새 세션 |

DESIGN-01 외 구현 배정은 예약 계획이며 실행 지시가 아니다. 각 실제 배정 시 설계 버전·파일 소유권·기준 커밋을 재명시한다. 설계 초안은 구현 착수 승인을 뜻하지 않는다.

## 설계 세션과 생성 복구 기록

- 활성 설계 작업: `투자 스킬셋 설계 초안 작성`, ID `01a0ccca-ac21-7d93-8bd9-9900ee3ea7cf`, host `local`.
- 최초 worktree 생성 요청은 client ID `client-new-thread:bb0a3a07-4753-4929-ac58-a48e1ff5632a`만 반환했다. `C:/Users/lsn/.codex/worktrees/f4e8/lsn-asset-mng-skills`의 detached HEAD는 위 기준 커밋이나 실행 가능한 세션 ID는 확인되지 않았다. 사용자는 앱에 오류·대기 표시가 없다고 답했다. 실패 원인은 확정하지 않는다.
- 복구: 독립 새 Codex 작업을 기존 프로젝트에서 생성했다. 설계는 design.md·decisions.md·handoffs/DESIGN-01.md만, 총괄은 AGENTS.md·requirements.md·tasks.md·baseline.md만 작성한다. 코드 병렬 구현이 아니므로 문서 소유권 분리로 진행하며 Gemini 구현의 별도 브랜치/worktree 요구는 유지한다.
- 최초 생성 요청이 뒤늦게 활성화되면 중복 설계 실행을 중단하도록 메시지를 보내고 해당 worktree 내용은 검토 없이 통합하지 않는다. 이번에는 worktree를 삭제하지 않는다.

## 이번 산출물과 다음 순서

- `AGENTS.md`: 역할·읽을 자료·현재 범위·인계 규칙.
- `requirements.md`: REQ-2026-09-23-v1, 요구사항 17개와 완료 조건.
- `design.md`: DESIGN-2026-09-23-v0.1, 공통 계약 C01–C07·17개 검증 행·35개 참조 방법 추적·모듈 소유권.
- `decisions.md`: 사용자 경계 B01–B06와 제안/미결정 D01–D16. 초안은 구현 계약 승인과 다름.
- `baseline.md`: 현재 코드 결함 재현·기존 테스트 22개 통과·설치 환경·미검증 범위.
- `handoffs/DESIGN-01.md`: 실제 설계 작업의 완료 인계. 아직 검토 작업을 하지 않았으므로 reviews 파일은 만들지 않음.

총괄의 문서 통합 확인은 요구사항 행 수, 기준 커밋·버전, 역할 분리, 참조 추적, 편집 범위에 대한 확인이다. 별도 독립 검토나 최종 검증을 대신하지 않는다. 런타임/기존 스킬/기존 테스트 변경 없음, commit/push 없음.

다음 사용자 설정 한 단계는 baseline.md의 `agy.exe models` 조회다. 이어서 모델 지정·제한된 권한 실증·단일 실행·격리된 동시 실행을 단계별 확인한다. 모델/권한/병렬 한도는 현재 미검증이며 A/B/C를 시작하지 않는다.

구현 전에는 공통 데이터·저장·공개시점·가격 적격성 계약과 파일 소유권을 먼저 확정한다. 차트/13F 가중치·판단 임계값·개인 위험 정책은 해당 기능 활성화 전 별도 결정한다. 미결정 목록을 숨기거나 임의 기본값을 넣지 않는다. 세부 제안 소유 파일과 후속 의존성은 design.md §9가 기준이다.
