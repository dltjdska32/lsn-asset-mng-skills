# CODEX-TRANSFER-01 — Gemini 구현을 GPT-6 Luna Codex 작업으로 인계

2026-09-23 사용자 변경: Gemini 구현 담당을 별도 Codex 구현 작업으로 전환하고 해당 구현·스킬셋 작업 모델을 GPT-6 Luna로 지정한다. 기존 Gemini 3 conversation/브랜치/worktree는 WIP 증거로 보존한다. Gemini 재개 heartbeat `gemini`는 `PAUSED`로 변경해 이중 수정을 막았다. 이 변경은 사용자 지시이며 첫 실행 제한이나 Gemini 한도 대기 계획보다 우선한다.

| 작업 | 새 Codex 요청 모델 | 시작 WIP SHA | 새 브랜치 / 관리형 worktree | create_thread 준비 ID |
|---|---|---|---|---|
| A 공통계약/후속 IMPL-A | `gpt-6-luna` | `49837ea3072914a00a7c65eff484789ea94d050a` | `codex/impl-a-luna` / `C:/Users/lsn/.codex/worktrees/b108/lsn-asset-mng-skills` | `client-new-thread:611def96-ef6e-421b-95e8-83549c70554d` |
| B 시세/후속 스킬셋 패키지 | `gpt-6-luna` | `d2db94f5d46b6e2ea04d28be0384d8b0400a923b` | `codex/impl-b-luna` / `C:/Users/lsn/.codex/worktrees/da18/lsn-asset-mng-skills` | `client-new-thread:25289b75-2f9e-4d34-a43b-24e0d79a8c20` |
| C 13F/후속 BRIEF | `gpt-6-luna` | `377dbb4e7c3f29bfd011c049acf4dd9dd98def0f` | `codex/impl-c-luna` / `C:/Users/lsn/.codex/worktrees/c051/lsn-asset-mng-skills` | `client-new-thread:88c7204e-dcd8-4bdc-8a95-30f2d6590667` |

세 새 worktree에서 시작 HEAD를 직접 조회하고 서로 다른 branch로 `git switch -c`한 결과를 확인했다. `create_thread`는 아직 실제 `threadId` 대신 client 준비 ID만 반환했으므로 **새 Codex 세션 실행·모델 적용·병렬 활동은 미확인**이다. 준비 완료 뒤 실제 task ID, cwd, 모델, 작업·검증 로그를 이 문서와 tasks에 기록한다. 준비가 실패하면 중복 생성 전 상태를 확인하고 복구한다.

## 실행 가능한 복구 세션

관리형 worktree 준비 요청은 실제 task ID로 전환되지 않았다. 같은 폴더에 다른 작업을 연결하면 뒤늦게 준비 완료한 세션과 충돌할 수 있으므로, 각 Gemini WIP SHA에서 아래 **다른** 세 worktree/branch를 만들고 projectless Codex 작업을 생성했다. `create_thread`는 `model=gpt-6-luna`를 수락하고 실제 thread ID를 반환했다. `wait_threads` 즉시 상태에서 세 task 모두 `active/inProgress`, 시작 메시지와 대상 worktree 점검이 확인됐다. 따라서 새 Codex 구현 작업 세 개의 **실제 병렬 시작**은 확인됐지만 코드 변경·검증 통과는 아직 확인되지 않았다.

| 작업 | 실제 Codex task ID | 새 branch / worktree | 기준 SHA |
|---|---|---|---|
| A | `01a0cd9c-71fc-7b93-a08b-60eba72d8d01` | `codex/luna-a` / `C:/Users/lsn/lsn-asset-mng-worktrees/codex-luna-a` | `49837ea3072914a00a7c65eff484789ea94d050a` |
| B | `01a0cd9c-aff9-7122-b0cc-bd638dbf7f81` | `codex/luna-b` / `C:/Users/lsn/lsn-asset-mng-worktrees/codex-luna-b` | `d2db94f5d46b6e2ea04d28be0384d8b0400a923b` |
| C | `01a0cd9c-e908-7f30-9991-75cbd9d2004f` | `codex/luna-c` / `C:/Users/lsn/lsn-asset-mng-worktrees/codex-luna-c` | `377dbb4e7c3f29bfd011c049acf4dd9dd98def0f` |

관리형 준비 ID 3개는 여전히 실제 task ID가 확인되지 않았다. 뒤늦게 생성되면 별도 branch에 있는 중복 구현을 중단/보관하고 위 실제 task 세 개만 통합 대상으로 삼는다. 모델은 create_thread 인자 수락으로 확인했고, 실행 로그의 모델 표시는 추가 확인 대상이다. projectless task의 기본 cwd는 결과 폴더라서 코드 작업은 표의 대상 worktree를 명시했다. 파일시스템 쓰기가 sandbox 밖이면 각 task가 정확한 경로로 제한된 승인을 요청하도록 지시했다.

## 지연 생성 확인과 최종 담당 선택

전역 task/workspace 매핑을 다시 조회해 준비 ID의 실제 task ID를 찾았다. 관리형 A=`01a0cd99-1059-7d73-b623-be991696c65d`, B=`01a0cd99-4ec0-7bc1-9b41-8f8596912ec9`, C=`01a0cd99-81dc-70e2-97c6-312c203086ec`. 모두 위 관리형 worktree의 별도 `codex/impl-*-luna` 브랜치를 사용했다. A는 실제 코드 편집과 AUDIT-04 12 PASS, AUDIT-03 22 PASS/7 FAIL까지 진행했다. B는 별도 미커밋 수정 후 종료했으며 C는 오래된 Gemini 한도 문구 때문에 코드 작업을 시작하지 않고 종료했다. 따라서 **관리형 A, 복구 B, 복구 C**를 후속 구현 담당으로 확정한다.

복구 A `01a0cd9c-71fc-7b93-a08b-60eba72d8d01`에는 중복 중단을 지시했고 실제로 추가 편집/커밋 없이 종료했다. 해당 별도 `codex/luna-a` 미커밋 수정과 99 계약 테스트 98 PASS/1 FAIL 인계는 보존하되 자동 통합하지 않는다. 관리형 B/C와 복구 A 작업은 archive해 UI 중복을 줄였다. 관리형 A에는 사용자 모델 전환·최신 지침·검증 환경을 전달했고 계속 활성 상태다. 복구 B/C는 별도 폴더에서 진행한다. 모델 `gpt-6-luna`는 여섯 create_thread 요청 인자로 수락됐으나 토큰별 provider 실행 텔레메트리는 확인하지 않았다.

복구 C `01a0cd9c-e908-7f30-9991-75cbd9d2004f`는 `codex/luna-c`에 구현 `c6a4431`, 인계 `e2b185f847a02aeb3cab313cef102981f4cf1967`을 commit하고 clean 상태로 종료했다. 담당 13F 테스트 26개 통과를 총괄이 같은 worktree와 root venv에서 독립 재실행했다. 변경은 `institutional/compare.py`와 C 전용 두 테스트, 인계뿐이며 자세한 내용은 `handoffs/CODEX-C-FIX-01.md`. C branch는 아직 root에 통합하지 않았고 실제 SEC archive XML 및 전체 repository suite 검증은 남았다.

복구 B `01a0cd9c-aff9-7122-b0cc-bd638dbf7f81`는 `codex/luna-b`에 구현 `b23ec247e9ffbcf9b7d6bc49b8c5db3a2fe96762`, 인계 `9252038100cf748e77f35996fde1cd1ae4d53cfd`를 commit하고 clean 상태로 종료했다. 총괄은 최종 commit에서 B 담당 unittest 19/19와 공개 Coinbase/Kraken 사본을 사용하는 fallback probe 6/6을 독립 재실행했다. BTC/EUR→USD 오승인, Kraken 응답 쌍, helper 조회시각, 실제 provider eligibility fallback을 보완했다. `handoffs/CODEX-B-FIX-01.md`가 인계 사본이다. 관리형 B의 별도 미커밋 수정을 자동 합치지 않는다. B branch도 아직 root에 통합하지 않았고 live API E2E/전체 suite는 미실행이다.

배정 기준은 root `docs/workflow/assignments/CONTRACT-FIX-06.md`, `IMPL-B-FIX-03.md`, `IMPL-C-FIX-03.md`로 유지한다. 문서 안의 Gemini 담당과 21:40 KST 한도 문구는 이 전환에 한해 Codex GPT-6 Luna 담당/즉시 진행으로 대체된다. 파일 소유권·요구사항·검증 조건은 그대로다. A 공통계약 인수 전 B/C는 독립 소유 파일만 수정한다. 이후 IMPL-A, BRIEF, INTEGRATE, PACKAGE도 담당 Codex GPT-6 Luna 작업에서 진행하고, 전체 독립 검토와 최종 검증은 구현 작업과 서로 다른 새 Codex 작업으로 유지한다.

개인 DB·인증정보·자동 주문·원격 push/deploy는 사용하지 않는다. 이전 Gemini 체크포인트나 독립 gate 부분 검토를 전체 구현·최종 검증으로 표시하지 않는다.
