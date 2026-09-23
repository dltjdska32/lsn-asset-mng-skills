# CODEX-TRANSFER-01 — Gemini 구현을 GPT-6 Luna Codex 작업으로 인계

2026-09-23 사용자 변경: Gemini 구현 담당을 별도 Codex 구현 작업으로 전환하고 해당 구현·스킬셋 작업 모델을 GPT-6 Luna로 지정한다. 기존 Gemini 3 conversation/브랜치/worktree는 WIP 증거로 보존한다. Gemini 재개 heartbeat `gemini`는 `PAUSED`로 변경해 이중 수정을 막았다. 이 변경은 사용자 지시이며 첫 실행 제한이나 Gemini 한도 대기 계획보다 우선한다.

| 작업 | 새 Codex 요청 모델 | 시작 WIP SHA | 새 브랜치 / 관리형 worktree | create_thread 준비 ID |
|---|---|---|---|---|
| A 공통계약/후속 IMPL-A | `gpt-6-luna` | `49837ea3072914a00a7c65eff484789ea94d050a` | `codex/impl-a-luna` / `C:/Users/lsn/.codex/worktrees/b108/lsn-asset-mng-skills` | `client-new-thread:611def96-ef6e-421b-95e8-83549c70554d` |
| B 시세/후속 스킬셋 패키지 | `gpt-6-luna` | `d2db94f5d46b6e2ea04d28be0384d8b0400a923b` | `codex/impl-b-luna` / `C:/Users/lsn/.codex/worktrees/da18/lsn-asset-mng-skills` | `client-new-thread:25289b75-2f9e-4d34-a43b-24e0d79a8c20` |
| C 13F/후속 BRIEF | `gpt-6-luna` | `377dbb4e7c3f29bfd011c049acf4dd9dd98def0f` | `codex/impl-c-luna` / `C:/Users/lsn/.codex/worktrees/c051/lsn-asset-mng-skills` | `client-new-thread:88c7204e-dcd8-4bdc-8a95-30f2d6590667` |

세 새 worktree에서 시작 HEAD를 직접 조회하고 서로 다른 branch로 `git switch -c`한 결과를 확인했다. `create_thread`는 아직 실제 `threadId` 대신 client 준비 ID만 반환했으므로 **새 Codex 세션 실행·모델 적용·병렬 활동은 미확인**이다. 준비 완료 뒤 실제 task ID, cwd, 모델, 작업·검증 로그를 이 문서와 tasks에 기록한다. 준비가 실패하면 중복 생성 전 상태를 확인하고 복구한다.

배정 기준은 root `docs/workflow/assignments/CONTRACT-FIX-06.md`, `IMPL-B-FIX-03.md`, `IMPL-C-FIX-03.md`로 유지한다. 문서 안의 Gemini 담당과 21:40 KST 한도 문구는 이 전환에 한해 Codex GPT-6 Luna 담당/즉시 진행으로 대체된다. 파일 소유권·요구사항·검증 조건은 그대로다. A 공통계약 인수 전 B/C는 독립 소유 파일만 수정한다. 이후 IMPL-A, BRIEF, INTEGRATE, PACKAGE도 담당 Codex GPT-6 Luna 작업에서 진행하고, 전체 독립 검토와 최종 검증은 구현 작업과 서로 다른 새 Codex 작업으로 유지한다.

개인 DB·인증정보·자동 주문·원격 push/deploy는 사용하지 않는다. 이전 Gemini 체크포인트나 독립 gate 부분 검토를 전체 구현·최종 검증으로 표시하지 않는다.
