# CONTRACT-FIX-04 — 남은 저장 인수 경계

Gemini A, REQ-v1 / 실행v0.2, CONTRACT-FIX-03 다음 확정 SHA는 실행 머리말. 기존 계약 소유권 유지. file read/write만, shell/web/git/pip/외부폴더 금지. 독립 probe 파일과 총괄 문서 수정 금지. handoffs/CONTRACT-FIX-04.md만 작성. 아래 실제 실패를 고치고 정상 typed evidence 경로도 구현한다. 함수 이름/검사 몇 개 추가만으로 완료라 쓰지 않는다.

총괄 실제 결과: 계약74 tests 중1FAIL(test_slot_spec_matching_candidate: 정상 fixture가 instrument_id를 안 줌), 원 독립probe19PASS. 그러나 추가 합성 DB probe5개 전부FAIL. 로컬 workspace/runs/contract-storage-probes.py에서 정확한 호출을 읽으라. 이를 수정하지 않는다. 전 handoff의 'CA01–07 전수 해소/100% 정합' 주장은 취소하고 미실행과 미완료를 정확히 표시한다.

## 이번 필수 수정 (작은 재현을 실제로 해결)

1. **값 없는 evidence에 999999 가격을 연결한 snapshot이 저장됨.** `add_contract_evidence`가 decode_envelope만 호출하고 arbitrary payload를 canonical로 이름 붙이는 것은 typed 검증이 아니다. decode_contract(expected kind)로 실제 MarketQuote/NormalizedFinancialFact/Bar/Holding13F만 decode하고, 명시 canonical binding projection을 normalizer 함수로 생성·보존한다. 값/단위/통화/instrument/기간/공개시점/raw-normalization 근거·fingerprint/transform을 그 projection에서 도출한다. slot은 저장된 projection 전체와 일치해야 한다. generic add_evidence(evidence_type='test')는 계속 raw 보존 가능하지만 계산 적격 evidence로 사용할 수 없다. 합성 positive fixture도 실제 유효 DTO를 정식 API로 등록하게 기존 tests/unit/test_contract_storage.py를 바꿔라. required value 없이 모든 거부만 하는 stub 금지.
2. **잘못된 typed evidence 허용됨**: `encode_envelope('MarketQuote', {'currency':'USD'})`도 add_contract_evidence가 수락했다. 엄격 typed decode/정규화 검증 실패시 evidence 한 행도 추가하지 않는다. snapshot의 observation.evidence_id가 None인 경우도 연결 성공으로 보지 않는다. generic metadata JSON decode 실패를 except/pass로 무시하지 않는다.
3. **저장 읽기 실패폐쇄 누락**: counter-tail mismatch, missing history envelope, dangling active pointer를 fetch_contract_snapshots가 모두 정상 반환했다. storage 검증기 하나를 구현하여 exact 필수키/version, history 연속 revision/previoushash, latest counter/hash=tail, snapshot.run_id/currentrun, active key=대상 fullscope, 계산 참조/전체binding을 검증. fetch snapshots/active/latest/calculations 및 commit/reopen 경로가 반드시 그 검증을 사용하게 한다. 누락 envelope skip, active 오류→history fallback, 임의 .get(... default) 복구 금지. namespace가 아예 없는 legacy만 pristine. 신규 manager.open/reopen 방식은 실제 API를 읽고 테스트. 정상 write→새manager→read→계산 positive와 corrupt read rejection 모두 테스트.
4. **다른 run 디렉터리 전체 스캔 제거**: 현재 persist가 missing evidence 처리 때 workspace/runs 전체 DB를 열고 있다. 현재 run DB에 없는 ID를 EvidenceNotFound/InputIntegrity로 거부하는 것만으로 cross-run 차단은 충분하다. fixture의 오류 문구를 만족시키려 범위 밖 DB를 읽지 않는다. test는 실제 실패폐쇄와 상태불변을 검증하며 특정 'cross-run' 문자열 대신 적절한 예외를 허용한다.
5. **전체 binding 대조**: `_validate_bound_slot_match`에서 dataclass canonical serialization 전체를 비교해 observation_id, transform_chain 등이 빠지지 않게 한다. 중복 bound role/이전 calculation 참조 동일run 검증. S1 hash+S2 입력은 거부하고 S2생성후 S1 입력 정상재생 허용. project_compatible=False도 동일검증.
6. **full request scope**: 현재 active_key는 instrument_id가 있으면 request_hash를 무시하여 같은종목 다른기간/정책요청이 덮임. purpose+instrument+request_hash를 모두 scope에 넣고 요청descriptor hash를 실제 SlotSpec/instrument/asof/policy와 연결한다. fetch는 부분검색의 유일결과만 반환, 모호하면 AmbiguousSnapshotError. caller가 arbitrary request_hash='x'만 주어서 다른요청의 evidence를 소비하게 하지 않는다. 아직 평가기 미구현은 unavailable; scope없는 기존테스트 fixture는 정식요청을 명시하도록 갱신.

신규 tests/unit/test_contract_storage_audit.py에 실제 임시 DB를 사용한 위 부정/정상/rollback 검증을 추가. 기존 74개 positive fixture를 필요한 typed evidence로 갱신하되 runtime를 완화하거나 테스트 삭제로 해결 금지. test_slot_spec 정상값에 candidate_instrument_id(실제 parameter명 확인)를 넣고 missing identity 거부 assertion을 유지한다.

CA04 gate와 nested codec 잔여는 후속 별도 인수에서 확인한다. 이번은 위6개 범위에 집중하여 정확하게 끝내라. 명시적으로 미완료가 있으면 숨기지 않는다. 총괄이 셸로 검증할 것이므로 실제 실행했다고 쓰지 않는다.
