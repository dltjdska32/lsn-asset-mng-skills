# CONTRACT-01 확정 배정

담당 Gemini A, model gemini-3.8-flash-high / high, worktree C:/Users/lsn/lsn-asset-mng-worktrees/gemini-a, branch codex/gemini-a. 기준 commit 68fab980fb26f207ce2abbb1f8d272c7b59690ea. REQ-2026-09-23-v1 R01–05·07·12·14·16, DESIGN-2026-09-23-v0.1 + 아래 검토 반영 기술 계약(실행 계약 v0.2).

의존성: SETUP-02 완료, 새 Codex REVIEW-DESIGN-01 직접 소스 검토의 P1 공통계약 모호성 해소. 총괄은 검토자 제안을 아래와 같이 채택한다. B/C 구현은 이 계약의 테스트와 commit 이후 시작한다. 현 작업은 공통 타입과 facade 구현만, IMPL-A 영역은 후속 배정에서 한다.

소유: runtime/investment_stack/contracts/** 신규, evidence/manager.py, providers/models.py의 호환 확장만, tests/unit/test_contract_*.py, docs/workflow/handoffs/CONTRACT-01.md. 개인 DB/schema, 기존 migrations, freshness evaluator/deep_research/routing/reporting 수정 금지. 필요 변경은 인계 요청. registry/factory는 실제 통합 단계에 변경한다.

기술적 확정:

1. contracts는 stdlib-only 타입과 strict codec을 소유. 구현 evaluator나 provider registry를 import하지 않는다. Decimal은 유한 정규 십진 문자열, kind/contract_version/payload envelope, unknown version/tag/extra required interpretation·NaN/Infinity·불명확한 숫자 차단. dataclass는 frozen, mutable dict 누출을 방지하거나 snapshot 시 깊은 복사를 검증한다. 직렬화 재복원 타입·hash 안정성.
2. RunContext(analysis_as_of aware timestamp/timezone/pinned personal version optional), PublicAvailability EXACT/DATE_INTERVAL/UNKNOWN; observed/published/retrieved 분리. Date interval upper bound까지 공개됨이 확인되지 않으면 point-in-time에서 제외. retrieve time 자체를 공개시각으로 사용 금지.
3. SlotSpec에는 purpose/instrument/metric/dimension/currency/기간/회계/연결/보고-adjusted/share basis/coverage 조건. EligibilityDecision은 상태·reason codes·allowed purpose·policy version. SelectedInputSet에는 슬롯별 bound input, source observation/evidence ref, value/units/time, selection revision, immutable snapshot hash. 함수/API가 typed 인자를 받아 실패 이유를 명시.
4. FinancialFact/FinancialSet: instant/duration, start/end, annual/quarter/YTD/TTM/fiscal/basis/units/availability/accession/tag/restatement, source refs. Market Quote/OHLCV Bar/BarSet: identity/venue/currency/timezone/session/completion/adjustment/split/coverage/source refs. Institutional filing/holding/holding-set: manager/accession/period/availability/amendment type/scope/SH-PRN/put-call/value units/identity/coverage. 기존 ProviderObservation.metadata 호환 adapter를 제공하거나 정확한 연결 API를 인계. 과도한 mandatory field로 관측 보존을 막지 말고 missing 정보는 eligibility에서 차단한다.
5. 계산 binding/formula/version/assumptions/선택 snapshot hash/output lineage와 execution/data/decision 상태를 분리. 미승인 정책은 UNAVAILABLE, 검증된 명시 가정으로 조건부 계산할 때만 CONDITIONAL. B/C·보고·valuation이 snapshot bound inputs를 검증할 수 있어야 한다.
6. 저장은 기존 run.db JSON을 사용하고 개인 schema·기존 migration checksum은 바꾸지 않는다. RunDatabaseManager facade에서 typed evidence/selection/calculation snapshot을 한 transaction으로 보존, expected revision CAS, append-only snapshot hash, immutable history 및 슬롯별 binding을 보장. 기존 observation_selections는 market FK를 가진 호환 projection이며 재무/13F 공통 ledger로 재사용하지 않는다. evidence.selection_state도 호환 projection만. manager.update_metadata가 contract history를 지워버리지 않도록 보존/거부 규칙을 함께 구현한다. 쓰기 실패 rollback, stale revision conflict, read-only reload에서 같은 선택·hash 확인. JSON 크기 무제한 원문 저장 금지; 원문 대신 정규화 typed payload/참조만 저장한다.
7. 투자 정책 수치를 발명하지 않는다. scalar 함수/enum 최소에만 그치지 말고 후속 A/B/C가 실제 사용할 구체적 타입과 API를 제공한다. 물리 필드 설계는 위 원칙 아래 담당자의 기술적 판단으로 확정하고 handoff에 모두 적는다.

완료 조건: strict codec roundtrip/invalid version/nonfinite/timezone/unknown public time, stable snapshot hash 및 tamper detection, SlotSpec coherence/currency/period mismatch와 coverage, atomic persistence/rollback/CAS/history preservation, synthetic run DB only. 신규 tests/unit/test_contract_*.py를 작성하라. 총괄이 .venv Python으로 실행하고 결과를 피드백한다. Gemini는 shell/git/pip를 호출하지 말고 file read/write 도구로 작업한다. 실행하지 않은 테스트는 미실행이라고 기록하라. 변경한 파일/정확한 API/필수 후속 연결/미완료를 인계에 적고 종료하라. commit/push·타 worktree 수정 금지.
