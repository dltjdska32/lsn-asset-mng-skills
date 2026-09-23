# 작업 상태표

## 현재 실행 상태 — 2026-09-23 후속 승인

아래 초기 실행 표는 이력이다. 후속 사용자가 초기 범위 제한을 해제하고 설정부터 Gemini 3세션 병렬 구현·새 Codex 독립 검토·수정·다른 새 Codex 최종 검증까지 승인했다. 현 총괄은 `01a0ccca-ac21-7d93-8bd9-9900ee3ea7cf`이며 기존 총괄은 조회 시 idle이었다. 현재 설계 기준은 DESIGN-2026-09-23-v0.1, 요구사항은 REQ-2026-09-23-v1이다.

| 작업 | 담당·파일 소유 | 의존성 | 현재 상태/완료 조건 |
|---|---|---|---|
| SETUP-02 | 총괄 / workflow 상태·배정·연결 증거 | 사용자 후속 승인 | 연결 probe 완료. 세 conversation ID·모델 생성·파일 read/write·동시 시간대 확인, handoffs/SETUP-02.md. 구현 병렬은 후속 단계 |
| REVIEW-DESIGN-01 | 새 Codex / reviews/REVIEW-DESIGN-01.md | 설계 기준 사본 68fab98 | 완료. 별도 세션 01a0cd29-c54f-7020-a9ec-abe51921f3ee, P1 8건·16 자체테스트·합성반례. 수정계약 채택, 구현 검증과 구분 |
| CONTRACT-01 | Gemini A / contracts/** 및 evidence/manager.py·providers/models.py 호환 확장·신규 계약 테스트 | 독립 검토 수정 계약 | 최초 결과 f1b9caa, 32계약테스트 OK이나 총괄의 unknown-kind/missing dimension·period/metadata tamper 반례 실패. CONTRACT-FIX-01 A 수정 중. 테스트·commit 전 B/C 구현 시작 금지 |
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
