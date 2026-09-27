# GEMINI31-INTEGRATION-01 — A/B/C 소유 파일 통합 체크포인트

2026-09-27 총괄 Codex. 기준 root HEAD `255deeab9c757776eb0328338d94783bc25e4717`에서 통합 시작. 단순 마지막 cherry-pick은 root가 A 계약 선행 파일을 갖고 있지 않아 충돌했으므로 즉시 abort해 clean 상태로 되돌렸다. 이후 각 branch의 **전체 소유 파일**을 아래 고정 SHA에서 `git restore --source --overlay`로 가져왔다. A의 새 contracts/evidence/providers 공통 계약을 유지하고 B/C의 더 오래된 공통 계약 사본을 덮어쓰지 않았다. B는 market_quotes/ohlcv/web_research/technical/배포 파일만, C는 institutional/sec_13f/decisions/briefing/reporting만 가져왔다. 각 handoff는 원 branch 버전 그대로 보존했다.

| 담당 | 통합한 source SHA | 핵심 범위 |
|---|---|---|
| A | `d6ef79bc90bb08f0bd170b37653c65a927b029b3`, R01 후속 `65388c1a8b2813982c52148d52cb2b069924a05e` | 공통 typed 계약·request descriptor 결속, deep_research의 stale/mismatch 가격 차단 |
| B | `0edbea6f40dbc4bff18ba6fc9f554852b684494b`, 배포/회귀 후속 `e2f709bbb36898989e370b43e966f48f50204802` | R06–08 공급자·차트 fail-closed, 8 skills+UI byte mirror, wheel/sdist allowlist |
| C | `f7d74653b093ef2b13980658bedd72b66bc1696e` | R12–13 13F 안전 경계, 5섹션 non-posting 브리핑 선행·결속 |

## 총괄 직접 실행

- A 계약 `106/106` PASS; 등록 request 정상 저장/reopen probe PASS, 미등록 유효 SHA request 거부 probe PASS (A worktree).
- 통합 tree에서 A R01/기존 deep research·freshness `19/19`, B R06–08 `42/42`, C 13F/브리핑 `32/32`, 기존 보고서 `25/25` PASS.
- 통합 tree `python -m unittest discover -s tests -q`: **465개, OK, skip 1**. skip은 root 개발 venv에 wheel-installed skills가 없는 packaging installation 검사다. 별도 깨끗한 synthetic venv에 통합 wheel을 설치한 `tests.test_packaging`: **5/5 PASS**, 원본/미러 8개 SKILL.md+agents/openai.yaml byte equality 확인.
- 통합 tree wheel/sdist 실제 빌드 PASS. B worktree에서 빌드 실패 → 허용목록 수정 → 격리 설치 회귀를 여러 번 실행했고 최종 B-07 파일 검사 5/5 PASS. 실제 개인 DB·인증정보를 테스트에 쓰지 않았다. 원격 push/deploy/자동 주문 없음.

## 미완·다음 의존성

- 이 체크포인트는 전체 v1.3 완료가 아니다. A R01은 기존 Phase4 SelectedEvidence의 current-price 안전 수직 경로이며 정식 `SelectedInputSet`을 모든 deep research 가격/재무 계산 소비 지점에 연결한 것은 아니다. R02–05, R09 DCF/시나리오/민감도도 미완.
- C의 ACTION-01~04는 독립 branch에서 별도 수정 중이며 **이 통합 tree에는 넣지 않았다**. 완전 R10–11 판단/개인 정책 registry·검증된 pin/규모 계산은 미완. B의 Codex UI 실제 스킬 발견은 wheel 파일/격리 venv 테스트로 대체하지 않는다.
- 7개 고정 모드 실행 결과 R14, 끝단 R16–17, 사용자 문서/스킬 최종 정렬·깨끗한 배포 안내, 새 Codex 전체 독립 검토와 다른 새 Codex 최종 검증은 후속. 위 테스트는 이 부분의 구현을 증명하지 않는다.
- 대상 root commit SHA는 총괄이 이 체크포인트를 commit한 뒤 tasks.md에서 확정한다.
