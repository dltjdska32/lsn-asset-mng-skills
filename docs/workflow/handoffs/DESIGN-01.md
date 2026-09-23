# DESIGN-01 인계

- 완료일: 2026-09-23. 결과: **설계 초안 작성 완료, 구현 승인·독립 검토·최종 검증 미완료**.
- 요구사항: REQ-2026-09-23-v1 / R01–R17.
- 설계 버전: DESIGN-2026-09-23-v0.1.
- 코드 기준: `3d4a95ba33d582f67a99de7b410b160e62645961` (HEAD 직접 확인).
- 작업 방식: worktree 생성 대기 후 원본 폴더에서 문서별 단일 작성자로 복구. 총괄 파일은 읽기만 했다. 다른 작업/하위 에이전트 생성 없음.

## 작성 파일

1. `C:/Users/lsn/lsn-asset-mng-skills/docs/workflow/design.md` — 공통 계약 C01–C07, 요구사항 17개, 7개 모드 실행·복합 요청, 검증 매트릭스, 구현 파일 소유권, 참조 35개 추적표.
2. `C:/Users/lsn/lsn-asset-mng-skills/docs/workflow/decisions.md` — 확정 경계 B01–B06과 제안/미결정 D01–D16.
3. `C:/Users/lsn/lsn-asset-mng-skills/docs/workflow/handoffs/DESIGN-01.md` — 이 인계.

초기 확인 시 design/decisions/이 인계 파일은 없었다. 기존 내용 덮어쓰기 없이 새로 작성했다. requirements/tasks/AGENTS/baseline, 투자 runtime·스킬·테스트·설치/설정 파일은 수정하지 않았다. commit/push/merge 없음.

## 읽은 범위

- 총괄 AGENTS.md, requirements.md, tasks.md, 작업 중 전달된 baseline.md.
- README.md, IMPLEMENTATION_STATUS.md, ARCHITECTURE.md, 현재 `skills/*/SKILL.md` 8개.
- 외부 설계 원문 `C:/Users/lsn/Downloads/investment-stack-canonical-final-v1.3.md`와 이전 검토 `C:/Users/lsn/Documents/ChatGPT/이성남 자산관리/스킬셋-v1.3.1-검토결과.md`.
- requirements에 지정된 참조 SKILL.md 35개: stock-analysis-skill 1개, Claude-Skills finance 2개, Morningstar 3개, Daloopa 21개, skills 아래 8개. 본문 방법론/수식/예시/출력 규칙을 분석했으며 개별 경로·반영·보류는 design §10에 기록했다. 하위 references/scripts/data-access 전체를 검증하거나 참조 명령을 실행한 것은 아니다.
- 관련 runtime: deep_research, research, providers 모델/어댑터/execution/registry, freshness, evidence/research, equity/valuation 계산, asset_analysis, reporting 모델 및 builder 주요 경로, router/planner/CLI, run migration v2; manager/storage/personal ledger API와 schema 구조는 관련 선언·검색 범위로 확인했다. runtime 모든 파일의 전수 감사는 아니다.
- 테스트: phase4 providers/freshness-web, live_deep_research integration, phase8 request modes/determinism 본문 및 관련 테스트 목록. pyproject, provider/freshness config, sync_agent_skills도 확인했다.

## 현재 코드 확인과 반영

STALE 현재가 유입, 기간 무시·입력 순서 선택, invalid scale의 1 대체, SEC 중첩 facts 미변환, usable 응답 후 조기 종료, 매수 키워드 라우팅을 현재 소스에서 확인했다. 합성 실행 결과 6종과 기존 targeted 22 tests OK는 **총괄 baseline의 결과**이며 이 설계 세션의 새 테스트 통과 보고가 아니다.

추가로 selected evidence와 provider_results 재선택 분리, CLOSED/HOLIDAY 종가 예외의 캘린더 검증 부족, date-only 공개시점/정정 vintage, live bridge의 DCF 가정 미전달, 계산 숫자별 계보 공백, 모드 계획과 실행의 차이를 설계에 반영했다. 차트·13F 전용 구현 검색과 현재 파일 구조를 확인했으며 일반 위험 시계열 기능을 해당 기능 완료로 간주하지 않았다.

참조의 beta/Rf/ERP/Rd/terminal 기본값, 분기 EPS 단순합, 현재 시총에 가중평균 희석주식 수 사용, OCF-capex의 무조건 FCFF 취급, 순부채 차감 뒤 현금 중복 가산, P/S 차원 오류, guidance의 일률적 +1분기와 발표일 근사는 그대로 채택하지 않았다.

## 실행한 검증

- HEAD 및 Git 상태 확인. tracked 파일 diff 없음. 총괄 작성 중인 AGENTS.md/docs/workflow는 untracked로 표시됨.
- `git diff --check` 결과 없음. 이 검사는 untracked 문서 검증을 대신하지 않으므로 신규 문서는 별도 구조/공백 확인 대상이다.
- 설계의 요구사항별 검증 행 **17개**, 참조 추적 행 **35개**, 미결정/제안 행 **16개** 확인.
- 신규 세 문서의 후행 공백·인코딩 대체문자 각각 0개. 추적표 참조 파일 35개 모두 존재하고 Daloopa 행 21개임을 별도 확인했다.
- 참조 파일 실제 존재·Daloopa 21개 목록과 본문 확인. 작성 문서의 R01–R17 포함, 소유권·승인 전 상태·금지 범위 점검.
- 설계/결정 문서 SHA256(인계 작성 직전): design `4352F84D328B9148267B9FEA5C600EBB727772DBAE5C9C3BEFC07A04BCAD9229`, decisions `36FC8DF486205EF10804616F5403393728F9EA2BDD7819B4B2C0632C46347C4E`.

## 미실행 검증과 제한

이 세션은 runtime unittest/전체 회귀/합성 실행을 새로 돌리지 않았다. 실제 개인 DB·금융 API·live 웹 수집·provider 접근성·SEC/13F 최신 공식 스키마·당시 공개 데이터셋·가중치 backtest·Gemini 모델/권한/동시성·Windows 설치/wheel·배포 검증은 미실행이다. 패키지를 설치하거나 환경을 바꾸지 않았다. 과거 테스트 수와 보고서의 완료 주장을 현재 완료 증거로 사용하지 않았다.

## 다음 담당에게

총괄은 요구사항 누락·역할/파일 충돌·승인 범위만 통합 확인하면 된다. 다음 독립 설계 검토에서 physical schema/계약 API, 공개시점/정정 정책, 실제 공급자 접근, 지표 파라미터, valuation assumptions, 13F 채택 기준, 안전마진·개인 위험/규모, 실행 dispatcher 및 배포 정책을 검토한다. 미확정 수치나 구조 제안을 승인된 값으로 간주하지 않는다.

후속 구현을 승인받으면 CONTRACT-01의 공통 파일 단일 담당을 먼저 지정하고 검토된 설계 버전·실제 코드 기준 커밋·담당 파일·의존성·완료조건을 다시 배정한다. A=R01–05, B=R06–07, C=R12와 후속 R08/09/13, R10–11/17, R14–16 분리는 design §9에 있다. 각 Gemini 세션은 별도 branch/worktree를 사용하며 READY만으로 3개 동시 실행을 가정하지 않는다.

## 2026-09-23 후속 사용자 지정

Gemini 구현 모델을 **3.8 Flash, High**(사용자 표기 `3.8flash high`)로 지정했다. design §9와 decisions B07/D15에 반영했다. 모델 선택은 확정했고 실제 CLI 모델 식별자·High 옵션 지원·권한·동시성은 미검증이다. 모델 실행이나 설정 변경은 하지 않았다. 위 SHA256은 최초 인계 직전 버전의 기록이며 이 후속 수정본의 해시가 아니다.
