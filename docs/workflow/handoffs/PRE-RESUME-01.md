# PRE-RESUME-01 — 외부 Gemini 한도 대기 중 독립 점검

2026-09-23 18:21 KST 기준. 총괄 작업 branch `codex/autonomous-integration`, 시작 HEAD `1734b31e47431f5013bbf5b3c2caa457808c2f4e`. 이 문서는 코드 인수나 통합 완료가 아니다.

## 고정 대상과 확인 결과

| 소유 | 대상 WIP SHA | 독립 확인 | 판단 |
|---|---|---|---|
| A 공통계약 | `49837ea3072914a00a7c65eff484789ea94d050a` | 기존 계약 99 tests / 17 ERROR. 새 Codex `CONTRACT-AUDIT-04` 12 probes / 10 PASS, 2 FAIL, 0 BLOCKED; 총괄 동일 probe 동일 결과 재실행 | 저장 public availability 오참조와 13F gate 목적/요구조건 우회 남음. 인수 불가 |
| B 시세 | `d2db94f5d46b6e2ea04d28be0384d8b0400a923b` | 25 담당 tests 통과(직전 체크포인트). 새 총괄 `market-fallback-checkpoint-probes.py` 공개 응답 오프라인 replay 6 cases / 5 PASS, 1 FAIL | BTC/EUR 요청에 BTC/USD 시세 반환. live E2E 아님 |
| C 13F | `377dbb4e7c3f29bfd011c049acf4dd9dd98def0f` | 26 담당 tests / 2 FAIL(직전 체크포인트). 코드·실패 테스트 대조 | 누락행+scale 경고 기대 수 수정 필요. synthetic report/문자열 승인으로 gate ENABLED 기대하는 테스트는 정책과 충돌 |

독립 Codex 검토 세션: `01a0cd29-c54f-7020-a9ec-abe51921f3ee`, 현재 검사 범위는 fixed SHA의 typed gate 메모리 소비 API만. 새 결과 `docs/workflow/reviews/CONTRACT-AUDIT-04.md`, 원 probe `scripts/workflow/contract-audit-04-probes.py`, 인계 `docs/workflow/handoffs/CONTRACT-AUDIT-04.md`. 기존 AUDIT-03은 옛 A SHA `84633e567c304735442749c24925a910b1694586`의 storage 29 probes / 7 PASS, 6 FAIL, 16 BLOCKED이며 현 A에서 이미 해결됐다고 가정하지 않는다. 전체 코드 독립 검토 REVIEW-CODE-01 및 다른 새 세션 최종 VERIFY-01과 분리한다.

## 한도 복구 후 배정

담당별 정확한 수정 범위와 재현은 `assignments/CONTRACT-FIX-06.md`, `assignments/IMPL-B-FIX-03.md`, `assignments/IMPL-C-FIX-03.md`. 기존 Gemini 3 conversation·개별 브랜치/worktree에 각각 전달한다. 제공자 한도 예상 reset은 약 21:38:45 KST이며 **21:40 KST 전에는 호출하지 않는다**. Codex heartbeat `gemini`가 ACTIVE이고 매시 45분 재개를 시도하도록 설정돼 있다. 현재 추가 로그인/직접 승인 요청 없음. 제공자 한도는 Codex 권한 차단과 다르다.

수정 후 첫 검증: A 99 tests와 AUDIT-03/04 및 정상 typed write→S1/S2→calc→reopen, B 담당 tests와 위6 cases 및 eligibility, C 담당 tests/안전 gate. 통과 시 공통계약 통합·세 도메인 후속 배정(IMPL-A, BRIEF, INTEGRATE, PACKAGE)·새 전체 CODE REVIEW·수정·새 최종 VERIFY를 계속한다. 아직 root runtime 통합 커밋, 개인 DB, 자동 주문, remote push/deploy는 없다.
