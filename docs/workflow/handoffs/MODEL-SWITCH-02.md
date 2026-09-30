# MODEL-SWITCH-02 — Gemini 3.1 Pro High 재연결

2026-09-27 사용자 최신 지시로 구현 담당을 Codex Luna에서 Antigravity Gemini 3.1 Pro High로 다시 전환했다. 진행 중이던 Codex A task `01a0cd99-1059-7d73-b623-be991696c65d`는 편집을 중단하고 idle을 확인했다. 그 task의 FIX07 미커밋 파일은 Codex worktree에 보존하되 마지막 변경 뒤 재검증이 없으므로 Gemini 기준으로 옮기지 않았다. 완료된 A/B/C 구현 commit만 각 옛 Gemini worktree의 새 branch에 cherry-pick했다. 이전 `gemini` heartbeat는 PAUSED로 두어 별도 중복 실행을 막는다.

Antigravity `agy models`가 `gemini-3.1-pro-high`를 `Gemini 3.1 Pro (High)`로 반환했다. `--model gemini-3.1-pro-high --effort high --mode accept-edits`로 세 독립 새 conversation의 setup probe를 실행했다. 각 결과 status SUCCESS, 정확한 응답 및 자기 worktree `workspace/runs/SETUP-G31-*.txt` 실제 쓰기를 확인했다. B/C는 동시에 호출해 시간이 겹쳤다. A probe의 raw JSON은 저장하지 않아 denied_actions 수는 기록하지 않는다. B/C 저장 JSON은 denied_actions 0이다. 이 probe는 **연결·읽기·쓰기 확인**이지 세 구현 세션의 병렬 코드 변경 검증은 아니다.

| 역할 | 새 conversation | branch / worktree | 코드 기준 HEAD | setup 결과 |
|---|---|---|---|---|
| A | `55adcf9a-ebcd-4c8e-9f22-2d69440758fb` | `codex/gemini31-a` / `C:/Users/lsn/lsn-asset-mng-worktrees/gemini-a` | `077ee538e13ff470900cb628ac3caa40ceee8581` | `G31_A_OK` |
| B | `7ffdd361-f295-4d32-9b68-fcc0af4c65e1` | `codex/gemini31-b` / `C:/Users/lsn/lsn-asset-mng-worktrees/gemini-b` | `07e8b0be876da7635e1c2c0bdbc040acbd04970c` | `G31_B_OK`, denied 0 |
| C | `9e9a0b36-5f2d-47e8-800e-7fcf67da351b` | `codex/gemini31-c` / `C:/Users/lsn/lsn-asset-mng-worktrees/gemini-c` | `006b2b09de5fed2dfffbd8c6c52703d44963210b` | `G31_C_OK`, denied 0 |

실제 구현 배정은 `assignments/GEMINI31-A-01.md`, `GEMINI31-B-01.md`, `GEMINI31-C-01.md`. 총괄은 성공 영수증·실제 파일 변경·테스트를 확인해 단계별 상태와 코드 SHA를 갱신한다. 외부 모델 응답 `SUCCESS`만으로 완료를 선언하지 않는다.

## 09:55 UTC 구현 호출과 직접 검사 (진행 중)

- A 원 conversation의 A-01/A-01-R1은 `RunCommand` headless 거부. 새 conversation `a2bfd0ab-ac92-4a4a-8917-6110f28a94fd`에서 파일 읽기 SUCCESS, A-01-R2가 `contracts/storage.py`, `evidence/manager.py`와 인계를 실제 작성했다. 마지막 provider API 연결 오류로 receipt `status=ERROR, exit=2`, 코드 인수 아님. 총괄은 독립 유효 SHA 미등록 request probe PASS 및 계약/저장/게이트/슬롯 45/45 PASS 확인. 요청 종목 None, as_of, 필수 slot 등 미결속을 찾아 A-02로 회송.
- B-01은 동일 B conversation에서 `status=SUCCESS, denied=0`이며 `pyproject.toml`, `MANIFEST.in`, skill sync script, B 전용 테스트와 인계를 실제 작성했다. 총괄 provider 8/8 및 패키징 정적 3/3 PASS, 새 technical 4 ERROR (`PublicAvailability.unknown` 잘못된 fixture). 임의 `caller_approved=True`와 문자열 정책 ID만으로 거래 신호 AVAILABLE이 되는 위험도 발견해 B-02로 회송. 실제 wheel/sdist 설치 확인은 아직 안 했다.
- C-01 최초는 headless 거부, C-01-R1은 `status=SUCCESS, denied=0`이며 `decisions/**`, `reporting/**`, 전용 테스트와 인계를 실제 작성. 총괄 전용 4/4 PASS지만 설계의 다섯 **출력 섹션**을 다섯 **투자 등급**으로 잘못 구현하고, 입력 부족에도 HOLD/AVAILABLE을 반환한다. C-02로 회송.
- B-01과 C-01-R1 실행 시간은 겹쳤고 각 코드 변경이 확인됐다. 세 세션 **모두**의 동시 코드 작성이나 병렬 구현 완료는 아직 확인되지 않았다. A/B/C-02 교정 호출은 각각 별도 worktree·branch·conversation에서 겹쳐 실행 중이며 결과 대기.

## 10:25 UTC 현재 체크포인트 (위 09:55 기록 이후)

| 담당 | 구현 체크포인트 | 총괄 독립 검증 | 모델 실행 상태·남은 제한 |
|---|---|---|---|
| A | `d6ef79bc90bb08f0bd170b37653c65a927b029b3` | 등록 요청 정상 저장/reopen probe PASS, 미등록 유효 SHA 거부 probe PASS, 계약 unit `106/106` PASS | 앞선 A-01-R2 API ERROR/A-02 중단/A-03 도구 거부 후 새 짧은 A4·A-05·A-06 SUCCESS/denied0. 원천 계약 체크포인트, R01–05/R09 도메인은 아직 없음. |
| B | `0edbea6f40dbc4bff18ba6fc9f554852b684494b` | 담당 `16/16`, skill mirror byte `--check` PASS, 실제 wheel/sdist build PASS, 격리 target wheel install PASS; wheel·sdist 각각 8개 skills 원본/미러 및 UI metadata, 민감 패턴 0 확인 | B-03 첫 재빌드 `runtime\\skills` 오류를 B-04로 수정. wheel 설치 target에는 파일이 있으나 Codex가 일반 venv 설치 경로에서 repo-local skill을 자동 발견하는지 미검증. sdist 전체 허용목록은 추가 확인 필요. |
| C | `f7d74653b093ef2b13980658bedd72b66bc1696e` | 담당 `6/6`, 기존 보고서 회귀 `25/25` PASS | C-03 처음 503, C-03-R1 파일 변경·handoff 후 최종 provider `ERROR`; 직접 실행으로 통과 확인. 5섹션 구조·결속 선행 단계. A 도메인/승인 정책 없는 최종 BUY·규모 계산은 보류. |

세 별도 worktree/branch/conversation의 A-05(10:19:17–10:22:43), B-04(10:21:49–10:23:25), C-03-R1(10:20:39–10:22:08) 모델 호출은 10:21:49–10:22:08 UTC 동시에 실행 중이었고 각각 담당 코드 파일을 실제 변경했다. 따라서 연결과 세 세션 병렬 **실행**은 확인했다. 구현 전체 완료나 독립 전체 검토·최종 검증을 뜻하지 않는다. root 통합은 위 정확한 SHA를 기준으로 진행한다.
