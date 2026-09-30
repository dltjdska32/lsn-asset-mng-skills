# CONTRACT-FIX-06 — A 계약 체크포인트 복구와 저장 인수

- 담당: Antigravity Gemini A, 기존 conversation `c2d86984-7d91-4fba-8723-9b3ec14ad098` / `codex/gemini-a` / 별도 worktree `C:/Users/lsn/lsn-asset-mng-worktrees/gemini-a`.
- 기준 코드: `49837ea3072914a00a7c65eff484789ea94d050a` (WIP, 인수 아님). 요구사항 REQ-2026-09-23-v1 R01–05/R09의 선행 공통계약, 설계 DESIGN-2026-09-23-v0.1 및 D17/D18.
- 소유 파일: `runtime/investment_stack/contracts/**`, `runtime/investment_stack/evidence/manager.py`, `runtime/investment_stack/providers/models.py`, `runtime/investment_stack/providers/contract_adapters.py`, A 계약 테스트 및 A 인계만. B/C 코드와 root workflow 기록은 편집하지 않는다.
- 의존성: CONTRACT-FIX-05 미완성과 `CONTRACT-AUDIT-03` 저장 반례 및 `CONTRACT-AUDIT-04` typed gate 반례. 실제 Gemini 재개는 제공자 한도 초기화 뒤 2026-09-23 **21:40 KST 이후**.

현재 체크포인트 99 계약 테스트 중 17 ERROR. 첫 오류 `contracts/storage.py:57/71/85`의 `PublicAvailability.available_at` 참조는 실제 DTO의 `public_available_at` 필드와 불일치한다. 같은 파일 line 123의 동일 패턴도 확인한다. EXACT/DATE_INTERVAL/UNKNOWN 의미를 보존하고 FinancialFact/Bar/Holding 경로를 모두 검증한다. `manager.py`의 Decimal import와 `CalculationRecord.preceding_calculation_ids` 저장/codec/직렬화 일관성을 확인한다. 이전 `AUDIT-03`은 옛 SHA `84633e5` 대상이므로 현 버전에서 이미 해결된 결함은 실행으로 확인해 구분한다.

빠른 fixture 수리 후 `docs/workflow/reviews/CONTRACT-AUDIT-03.md`의 29개 반례를 **수정하지 않고** 현 코드에서 재실행한다. 그 보고서의 P1-02 typed 원본 없는 `canonical_payload={contract_kind만}`이 임의 999 금액을 승인하는 결함, P1-03 잘못된 active pointer scope·객체 간 계산 read binding·evidence cache 불일치, 해석 불가능한 request hash 수용을 해결한다. 원 typed envelope에서 projection을 재도출하고 값·단위·통화·종목·공개시점·fingerprint·eligibility를 저장/재개/읽기 경계에서 검증한다. Request descriptor의 hash와 slot 요구를 연결한다. `open().valid`의 의미가 ledger validation을 보증하는지도 분리해 명시한다. 새 서명 시스템은 요구하지 않는다.

독립 Codex의 고정 49837ea gate 감사 `CONTRACT-AUDIT-04`는 12개 중 10 PASS / 2 FAIL / 0 BLOCKED이며 root가 그대로 재현했다. (1) purpose=`13F_WEIGHT` 계산이 다른 purpose=`UNRELATED_DIAGNOSTIC`의 ENABLED gate를 참조해 WEIGHT 결과를 소비한다. (2) 동일 DISABLED gate를 두고 formula_id=`portfolio_weight_v2`, requirement=`ARITHMETIC`으로 바꾸면 13F_WEIGHT를 소비한다. 신뢰된 formula/version 요구 등록과 gate purpose/policy identity binding으로 고치되 정상 일반산술·명시적 조건부 analyst scenario는 유지한다. 단순 formula 문자열 패턴 증가나 caller requirement 신뢰로 해결하지 않는다. `validate_calculation_for_use`는 현재 정의/export 외 저장/소비 호출자가 없어 integration 연결이 필요하다. 보고서와 probe는 root `docs/workflow/reviews/CONTRACT-AUDIT-04.md`, `scripts/workflow/contract-audit-04-probes.py`에 있다.

필수 정상 사례는 유효 MarketQuote/Holding 등록 → S1/S2 snapshot → 계산 저장(독립·atomic) → reopen/replay의 값·출처·시점 보존이다. 부정 사례가 예외가 아닌 우연한 AttributeError/NameError로 종료되면 PASS로 세지 않는다. CONTRACT-FIX-05의 codec/gate/typed output도 원래 독립 probe와 실제 새 소비 API로 검증한다. 테스트/독립 probe를 통과시키려고 금융 적격성이나 13F gate를 완화하지 않는다. 결과·정확한 HEAD·실행/미실행 검증·남은 오류를 `docs/workflow/handoffs/CONTRACT-FIX-06.md`에 인계한다.
