# VERIFY-01 인계 — 명시 구현 범위 최종 검증 통과

- 직접 checkout/검증한 SHA: **`2a078da91ddfd761a1785ee482f3cd23eb1acaf7`**. 마지막 runtime SHA **`4e55a560b4245ad5fb63cf4de8a2ce9813a2752a`**와 runtime diff 없음.
- 별도 격리 worktree: `C:/Users/lsn/.codex/worktrees/bfbc/lsn-asset-mng-skills`. REVIEW-CODE-01과 다른 새 세션에서 수행했다.
- 판정: **문서에 명시된 구현 범위의 최종 VERIFY 통과**. 이번에 발견한 새 P1/P2 런타임 결함 없음. R01–R17 전체 기능 완성, 미확정 투자 정책 승인, 실계좌/배포 승인이 아니다.

## 실행 결과

| 검사 | 결과 |
|---|---|
| 현 wheel/sdist 직접 재빌드 | 성공 |
| 소스 전체 unittest | 600 OK / skip1, 86.619초 |
| clean installed-wheel 전체 unittest | 600 OK / skip0, 86.708초 |
| 기본 discover 제외 폴더 추가 검사 | providers8 + calculations4 OK |
| 보존 독립 반례 | 첫5 + 중간3 + b1 5 + a1 3 + dcd3 + RC12 1 = 20/20 PASS |
| RC10-R2 manifest 경계 | 10/10 subtests PASS |
| RC12 저장·재open·이전/현재 내용/hash·실제 refresh | 2/2 PASS |
| clean wheel R15 | 11/11 OK / skip0, pip check·IANA/import assertion 성공 |
| 풀린 현 sdist 자체 재빌드/R15 | 11 OK / skip1; 과거 RC08 반례 통과 |
| 소스/설치 artifact payload | runtime116 파일·skill32 파일 byte equality; 8스킬/미러/UI 동일, invariant11 PASS |
| 새 VERIFY 합성 real-ledger fault/retry | 실제 게시 후 상태 기록 실패에도 POSTED 영수증 유지; 재시도 ALREADY_POSTED, state1 불변 |
| 새 default factory 고정 cutoff replay + 공개 시세 | 두 원천 모두 LAST_VALID_CLOSE→Phase4 저장→Phase5 소비, 비실시간 고지 |

공개 조회는 KST **2026-09-28 00:49**(UTC 9/27 15:49), 분석 cutoff는 **2026-09-27T12:00:00+00:00**로 고정했다. Yahoo AAPL 341.07 USD/9월25일, Naver 005930 286500 KRW/9월23일 종가를 선택했다. 둘 다 valuation PARTIAL이며 실시간 가격·완전 live 재무분석이 아니다. 실제 HTTP는 공개 시장 두 URL만 허용했고 금융/웹 자료는 빈 합성 입력, credential은 빈 mapping이다.

## 남은 제한과 미실행

- configured host에 ledger/provider/typed loader/callback 주입 필요; 기본 CLI 자동 구성이 아니다.
- 5항목 WAIT 저장/ref/history는 연결됐지만 R08 차트·13F evidence→action 자동 결속, 승인 정책/가중치·안전마진·자동 규모는 미완이다. UNVALIDATED/DISABLED·WAIT·비게시를 유지한다.
- NASDAQ 9/24–28, KRX 9/22–28 pinned 일정 밖 일반 calendar 지원 없음. 공식 달력 원문 재조사, 모든 vendor live/SEC archives/OpenDART 인증 호출 미실행.
- Naver adjustment receipt 진위·raw Sequence[Bar] provenance·일반 corporate actions는 기존 제한이다.
- 일반 보고서 전체 한국어/내부 ID 분리·가독성 및 전체 numeric binding은 완료 아님. IMPLEMENTATION_STATUS의 a1a41b0 옛 'current/in-progress' 표현은 해당 역사 checkpoint로 읽어야 한다.
- Windows Python3.14.6만 실행. dependency는 로컬 tzdata/truststore 복사 후 offline 설치했으며 broad 다운로드 없음. 다른 OS/Python, 임의 venv Codex UI 자동발견은 미검증.
- 개인 DB/실제 인증정보/주문·commit/push/배포 없음. runtime·기존 테스트·스킬은 수정하지 않았다.

## 산출물과 인수

1. `docs/workflow/reviews/VERIFY-01.md` — 상세 판정, R01–R17 범위, 직접 실행/미실행, artifact SHA256.
2. `docs/workflow/handoffs/VERIFY-01.md` — 본 인계.
3. `docs/workflow/reviews/verify_01_execution_evidence.txt` — 현재 세션 실행 요약 원출력.
4. `docs/workflow/reviews/verify_01_independent_checks.py` — 신규 합성 ledger fault/retry 및 pinned 시장 경로 재현. 기본은 합성, `--live`만 공개 시세 호출.
5. `workspace/verify-01/` — 상세 원로그·build/install helper·clean venv·풀린 sdist. **venv/build payload/workspace 전체를 커밋하지 말 것.** 인수 대상은 위 문서와 재현/evidence 파일이다.

총괄은 이 결과를 REVIEW-CODE-01의 코드 검토 통과와 구별해 최종 상태에 반영할 수 있다. 별도 runtime 변경이 발생하면 새 SHA에 이번 통과를 자동 적용하지 않는다. 검증 산출물 작성 뒤 HEAD를 다시 확인했고 runtime/tests/skills/build 설정의 기존 tracked diff는 없다.
