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
