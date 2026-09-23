# CONTRACT-FIX-03 — 독립 인수검토 반례 해소

Gemini A, verified base1462fb6, REQ-v1/실행v0.2. 현재 소유권 유지. shell/git/pip/web/외부폴더 접근 금지. 총괄 실행 결과를 자신의 작업폴더에서 읽고 수정한다. 장문 보고보다 코드를 고치고 간결한 handoff 후 종료하라. 테스트는 총괄이 반복 실행한다.

입력 파일(모두 자기 worktree 안):
- docs/workflow/reviews/CONTRACT-AUDIT-01.md: 별도 Codex가73d376e를 직접 독립 검토한 CA01–CA07.
- workspace/runs/contract-audit-probes.py: 독립 검토자가 만든 실제 반례. **이 파일은 수정하지 않는다.**
- workspace/runs/CONTRACT-FIX-02-audit.log: 총괄이 현재1462fb6에 실행한 결과17FAIL/2PASS. API 수정으로 probe가 실행 안 되는 상태를 통과로 보지 않는다.
- workspace/runs/CONTRACT-FIX-02-check.tests.log: 55tests, errors2(아래).

우선 실행 오류2건: manager의 bound_value 오타를 canonical_value로만 바꿔 끝내지 말고 CA02 전체 binding 비교를 구현. cross-run fixture가 다른 run_id 행을 현재DB에 직접INSERT하다 FK오류로 멈춤: PRAGMA/FK끄기 금지, 별도의 합성 RunDatabaseManager에 evidence를 만들고 현재 run에서 참조를 거부하는 정상 test fixture로 수정한다.

반드시 처리할 실제 부정경계:
1. bool/int/enum/date strictness: CalculationAssumption.is_approved='false', CoverageDecision.is_complete='false', missing+completeTrue, SlotSpec ALIEN purpose/dimension·bad date·duration bool, required instrument None을 거부. bool(payload)·int(bool) 강제변환 대신 모든 decoder 공통 strict helper를 사용. 모든 nested DTO는 expected_kind 확인. unknown key/duplicate JSON key/nonfinite 정책도 닫는다. CoverageDecision complete는 coherent required/fulfilled/missing/conflicted 불변식에 연결.
2. 공통 gate/output: unapproved TRADING/13F policy가 bare CONDITIONAL로 활성화되지 않도록 GateDecision이 purpose별 승인/검증참조·전제 의미를 검증하고 CalculationRecord에 gate_ref/hash/용도를 연결. 단순 산술과 명시 analyst scenario는 허용 가능하나 미승인 투자신호/안전마진/위험/13F가중치는 disabled. UNAVAILABLE/FAILED의 result_payload에 buy_price 같은 소비가능 numeric을 숨길 수 없도록 typed output/gate 검증. dict 출력에 문구·reason은 유지 가능하되 numeric binding으로 소비할 수 없음.
3. raw candidate 보존≠validated coverage. invalid scale/raw-normalized 불일치/통화·기간 혼합 FinancialSet이 covered_metrics로 완료 선언하면 안 된다. 일반 collection이면 coverage완료를 갖지 않고 A의 후속 evaluator가 검증한 coherent subset만 계산에 소비하게 한다. FinancialSet 정상 여러기간 보존은 허용하되 계산별 typed receipt 없이 적격 선언 금지. BarSet은 bar.interval 일치와 verified/unknown adjustment/completion·coverage 경계를 표현. A evaluator 미구현은 unavailable; 전체 SEC/YTD/fallback 구현까지 이번 계약에 넣을 필요는 없다.
4. storage strict read: schema_version999/null namespace/counter-history-tail mismatch/active 잘못된scope/run/hash/missing envelope를 fail-closed. extract, fetch snapshots, active, calculations, 새 manager reopen이 같은 검증을 거치게 한다. legacy namespace 없음만 pristine 허용. generic metadata update 보호 유지. history중 corrupt entry skip/fallback 금지.
5. adapters/lossless: normalized 2,000,000을 USD million unit으로 재전달하여 double-scale 위험 만들지 말고 canonical unit+raw provenance 분리. Bar close unit이 SHARES여서는 안 됨. Holding voting fields·PRN/SH basis·value_scale 정보 왕복 보존, 공급 schema 근거 없는 default1000 금지. explicit absent scale은 unknown/raw상태로, 값을 임의 적용 금지. typed 공시/holding availability/accession/period/source 정상왕복.
6. semantic hash에 purpose/request/instrument/기간/공개version/단위/정상화basis/input fingerprint 포함. runlocalUUID·created/retrieved clock은별도 identityhash로 구분. 서로다른purpose/publicavailability/fingerprint가 같은 semantic identity로 충돌하면 안됨.
7. CA01/CA02 핵심: add_contract_evidence가 expected_kind typed decode+normalized payload 적격경계를 검사. source-normalizer가 만든 canonical payload(value/unit/currency/instrument/period/basis/publicavailability/normalization-version/transformation)를 evidence에 보존. snapshot commit은 저장된 payload와 BoundInput 전체 의미를 대조하고 observation.evidence_id도 일치시킨다. 값 없는 evidence_type=test 행에 임의price binding 허용 금지. request scope descriptor/hash를 저장된 슬롯 요구와 연결하여 A evidence에 B request를 붙이지 못하게 한다. trusted는 임의approved/source_tier bool로 만들지 않는다. 후속 normalizer가 미구현이면 unavailable로닫고 합성 valid contract evidence는 정식검증API로 등록하는 positivefixture를 제공한다.
8. bundled/standalone calculation 공통 validator는 **calculation이 실제참조한** immutable snapshot을 읽어 canonical binding 전체/필수 역할/중복 slot/이전 calculation 참조·동일run을 검사. S1hash에 S2inputs 붙이기, USD→JPY만변조, eligibility/fingerprint/transform변조 거부. 정상 S1 계산은 S2가 생겨도 S1inputs로 재생 가능. project_compatible True/False 모두같은검증.

신규 tests/unit/test_contract_audit_*.py에 독립 반례와 정상 positivecases를 추가하고 기존55tests도 올바른 typed evidence fixture로 갱신. DB검사는 합성 임시run만. 추가 DB회귀: 정상 write→새 manager reopen→read→calculation, corrupt namespace→읽기거부, forged evidence/calcbinding→snapshot·active·projection 변화0, rollback. wire0.2변경은 아직 B/C가 시작안했으므로 가능하나 공개API가 서로어긋나지않게 실제imports/constructors를확인. 단순stub/all-reject/테스트삭제로통과하지 않는다. 기존 financial/domain positive roundtrip을 유지.

종료시 handoffs/CONTRACT-FIX-03.md에 CA01–07 대응파일/API, 실행미실행, 남은이슈를 간결히기록. probe와총괄문서는수정금지. 정상코드+불필요한권한완화없이계약인수가목표다.
