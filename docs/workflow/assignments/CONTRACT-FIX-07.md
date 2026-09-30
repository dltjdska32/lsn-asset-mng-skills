# CONTRACT-FIX-07 — 실제 SelectionRequest descriptor 결속

- 담당: Codex GPT-6 Luna A, task `01a0cd99-1059-7d73-b623-be991696c65d`, `codex/impl-a-luna`, worktree `C:/Users/lsn/.codex/worktrees/b108/lsn-asset-mng-skills`.
- 기준: `16a22e0a789b3ce526934474ad3f271fee0cda33` (CONTRACT-FIX-06 결과), REQ-2026-09-23-v1, DESIGN-2026-09-23-v0.1 `SelectionRequest`/`SelectedInputSet` 계약, AUDIT-03 request descriptor 지적. A 파일 소유권과 합성 DB 제약 유지.
- 총괄 독립 재검증: 계약 unittest 99/99, storage audit 29/29, gate audit 12/12가 위 SHA에서 통과. 그러나 `scripts/workflow/contract-request-descriptor-probe.py --repo <A>`는 **FAIL**: 등록된 SelectionRequest가 없는 새 synthetic run에서 `request_hash="0"*64`인 빈 SelectedInputSet을 `persist_contract_snapshot`가 승인한다. 기존 storage audit의 `request_hash_requires_resolvable_descriptor`는 `"unregistered-request"`만 넣어서 SHA 형식 검사를 검증할 뿐 descriptor 결속을 검증하지 않는다. 이 PASS를 요구사항 완료로 해석하지 않는다.

구현 조건: snapshot에 request_hash가 있으면 같은 run에서 해석 가능한 실제 `SelectionRequest` descriptor를 등록·저장하고, 저장/재개 시 descriptor를 decode해 hash 재계산, purpose/instrument/as_of/policy/요청 slot metric·기간·단위·통화 등 요구와 선택 입력의 관계를 검증한다. 빈/부분 coverage 허용 여부는 명시적으로 표현하고 모호한 암묵 허용을 피한다. caller가 임의 64 hex를 붙이거나 서로 다른 descriptor hash를 대체해도 거부해야 한다. 레거시 request_hash=None의 의미는 문서화한다. 불필요한 서명 체계나 미결정 투자 정책 기본값은 추가하지 않는다.

신규 부정 probe와 정상 descriptor 등록→snapshot→S1/S2→calc→reopen, 다른 metric/period/currency/as_of, descriptor 손상·hash 교체를 검사한다. 정상 신규 API 때문에 기존 독립 probe가 깨지면 원본을 임의 수정하지 않고 정확한 API/기대 변경을 인계한다. 총괄이 독립 probe를 의미동등하게 수정·재실행한다. 결과·정확한 SHA·실행/미실행 검증은 `docs/workflow/handoffs/CODEX-A-FIX-02.md`에 기록하고 자기 branch에 로컬 commit한다. 다음 IMPL-A 도메인 구현은 이 계약 인수 후 배정한다.
