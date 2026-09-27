# GEMINI31-A-01 — SelectionRequest descriptor 실제 결속

- 담당: Antigravity Gemini `gemini-3.1-pro-high`, effort high. 새 conversation은 `handoffs/MODEL-SWITCH-02.md` 참조. branch `codex/gemini31-a`, worktree `C:/Users/lsn/lsn-asset-mng-worktrees/gemini-a`, 기준 HEAD `077ee538e13ff470900cb628ac3caa40ceee8581`.
- 요구사항 REQ-2026-09-23-v1 R05/R16, 설계 DESIGN-2026-09-23-v0.1 및 `CONTRACT-FIX-07.md`. 소유는 contracts/**, evidence/manager.py, A 계약 테스트 및 `handoffs/GEMINI31-A-01.md`뿐. B/C·공유 workflow 원본은 편집하지 않는다. shell/git/pip/web 사용 금지, worktree 파일 read/write만.
- Codex A의 완료된 계약 FIX06 커밋을 기준에 반영했다. 총괄이 그 기반에서 계약99/99, storage audit29/29, gate audit12/12를 재실행했다. 하지만 미등록 `"0"*64` request_hash를 snapshot이 승인한다. 로컬 `workspace/runs/contract-request-descriptor-probe.py`가 재현 스크립트이며 현재 FAIL이다. 이전 29 audit 중 해당 항목은 짧은 non-SHA 문자열만 거부하므로 진짜 descriptor 결속 통과로 세지 않는다.
- 같은 run에 실제 SelectionRequest를 등록/저장하고 snapshot write/reopen 때 descriptor decode·hash 재계산·purpose/instrument/as_of/policy/slot metric·기간·단위·통화 결속을 검증한다. 등록되지 않은 유효 64-hex hash, 다른 descriptor hash 교체, 손상된 저장 descriptor, 요청에 맞지 않는 선택 입력을 거부한다. 빈/부분 coverage와 `request_hash=None`의 legacy 의미를 명시하되 정책 숫자를 임의 만들지 않는다. 정상 descriptor→snapshot→S1/S2→계산→reopen도 유지한다.
- 중단된 Codex A FIX07 미커밋 코드는 이 worktree에 포함하지 않았다. 그 세션의 마지막 변경 뒤 테스트를 다시 돌리지 않았으므로 통과 코드로 가정하지 않는다. 독립 root probe 원본을 고쳐서 통과시키지 말고 새 API가 필요한 이전 probe의 변경 요구를 인계하라.
- `docs/workflow/handoffs/GEMINI31-A-01.md`에 실제 변경, 공개 API, 실행한/하지 않은 검증, 남은 결함과 기준 HEAD를 기록한다. 총괄이 test/probe를 실행하고 실패를 회송한다. 개인 DB·인증정보·자동 주문·원격 push/deploy 없음.
